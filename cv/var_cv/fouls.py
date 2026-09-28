"""Foul / red-card evidence (IFAB Law 12) for one analysed window.

python -m var_cv.fouls --analysis var_data/ID/12.0-17.0/analysis.json --video var_data/ID/video.mp4 \
    --out var_data/ID/12.0-17.0/fouls.json [--debug-dir DIR]

This module MEASURES; it never decides. backend/var_fouls.py turns the measurements into Law 12
verdicts. Every indicator carries a confidence and says "not observable" when the evidence is missing.

Method
1. Candidates (from analysis.json, sampled frames): opponents (team A vs B, referees excluded) whose
   ground positions are <= CONTACT_M apart in a calibrated frame, or whose boxes overlap with feet at
   a similar image depth (any frame, so close-up replays qualify). Consecutive hits of the same pair in
   the same shot merge into one candidate; the MAX_CANDIDATES closest are examined.
2. Pose at the full video frame rate over the candidate span (+-PAD_S, never across a cut): both
   players' boxes are interpolated between sampled frames, the union is cropped, upscaled and run
   through a COCO-17 pose model (ultralytics YOLO pose, local weights); detections are matched to the
   two players by IoU.
3. Contact frame: the frame where one player's striking points (feet, knees, hands, elbows) come
   closest to the other's body segments, in units of the struck player's box height. The player doing
   the striking is the challenger; ties are broken by who was further from the ball (the victim usually
   has it) and then by who was closing faster.
4. Metres: where the window is calibrated, the per-frame camera (K, R, t) is recovered from the
   homography (square pixels, principal point at the centre) and heights come from intersecting the
   keypoint's ray with the vertical above the player's tracked ground position. Otherwise heights come
   from the victim's own skeleton (standard proportions of a 1.80 m upright body) at lower confidence.
5. DOGSO factors (IFAB 2026/27: distance to goal, general direction of play, likelihood of keeping or
   gaining control, location and number of defenders and attackers) from the calibrated ground-plane
   positions nearest the contact, with the camera's view footprint so off-screen areas are flagged.
"""

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

CPU_THREADS = 4  # shared M2: CPU thread cap for BLAS/OpenMP/torch/onnxruntime/video decode (models run on MPS/CoreML)
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, str(CPU_THREADS))  # before numpy/cv2/torch load their thread pools

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# This OpenCV build parallelises with Apple GCD, which ignores setNumThreads(n > 1) (getNumThreads stays 8):
# the only effective cap is 0 = run OpenCV's own loops on the calling thread (ultralytics sets the same on
# import). Video decoding has its own FFmpeg threads, capped per capture with CAP_PROP_N_THREADS (open_video).
cv2.setNumThreads(0)


def open_video(path):
    return cv2.VideoCapture(str(path), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, CPU_THREADS])

WEIGHTS = Path(__file__).resolve().parent.parent / "weights"
POSE_WEIGHTS = "yolo11m-pose.pt"  # ultralytics release asset; auto-downloads into cv/weights on first run
# RTMPose-x, Halpe26 keypoints (COCO-17 + head/neck/hip + big toe, small toe, heel per foot), ONNX via rtmlib;
# downloaded by setup.sh. Run top-down on the two players around the contact only.
FOOT_WEIGHTS = "rtmpose-x-halpe26-384x288.onnx"
BALL_WEIGHTS = "football-ball-detection.pt"  # roboflow/sports, as in analyze.py
H26 = {"lbt": 20, "rbt": 21, "lst": 22, "rst": 23, "lheel": 24, "rheel": 25}
LOC_FLOOR_PX = 1.5     # keypoints are never localised better than this on broadcast video
LOC_DEFAULT_PX = 3.0   # assumed keypoint error when a second pose model cannot measure it
LOC_SCALE_M = 0.2      # localisation error (m) at which image-plane contact geometry is worthless
BALL_REACH_M = 1.2     # challenger's foot this close to the ball around the contact = challenging for it
KP_CONF = 0.5          # keypoint visibility threshold
CONTACT_M = 1.2        # ground distance for a contact candidate
MAX_CANDIDATES = 6
PAD_S = 0.4            # pose span around the candidate
MERGE_GAP_S = 0.5      # candidate hits of one pair closer than this are one candidate
CROP_TARGET_PX = 512   # crops are upscaled so the pair fills the pose model's input
CLOSEUP_MAX_PLAYERS = 6  # uncalibrated shots tracking fewer people per frame get a pose-model person pass
CLOSEUP_MIN_PX = 60     # people smaller than this in a close-up are background
CLOSEUP_ID_BASE = 1000  # close-up track ids start here so they never collide with the analysis' ids
MAX_ANKLE_LIFT_M = 1.0  # higher ankles in a challenge are pose/identity errors
MAX_SPEED_MPS = 10.5   # faster ground speeds are tracking errors
NEAR_SAMPLE_S = 0.25   # a full-rate frame borrows the homography of a calibrated sample this close (same shot)
COARSE_HZ = 15         # first pose pass rate; the closest approach is then refined at the full frame rate
TOUCH = 0.06           # striking point within 6% of body height (~11 cm) of a segment = touching
NEAR = 0.15            # within 15% = contact possible but not resolved
BODY_M = 1.80          # assumed stature for skeleton-relative heights
LIMB_OFFSET_M = 0.4    # a limb can sit this far horizontally from the tracked foot anchor
PITCH_L, PITCH_W = 105.0, 68.0
GOAL_HALF_W, BOX_L, BOX_HALF_W = 7.32 / 2, 16.5, 40.32 / 2

K = dict(nose=0, leye=1, reye=2, lear=3, rear=4, lsho=5, rsho=6, lelb=7, relb=8, lwri=9, rwri=10,
         lhip=11, rhip=12, lkne=13, rkne=14, lank=15, rank=16)
# Victim body segments (a, b); single-point parts use a == b. Height along the segment for an
# upright 1.80 m body (standard proportions) gives skeleton-relative heights when uncalibrated.
SEGMENTS = [
    ("head", ("nose", "nose")), ("head", ("leye", "reye")), ("head", ("lear", "rear")),
    ("torso", ("lsho", "rsho")), ("torso", ("lsho", "lhip")), ("torso", ("rsho", "rhip")), ("torso", ("lhip", "rhip")),
    ("upper arm", ("lsho", "lelb")), ("upper arm", ("rsho", "relb")),
    ("forearm/hand", ("lelb", "lwri")), ("forearm/hand", ("relb", "rwri")),
    ("thigh", ("lhip", "lkne")), ("thigh", ("rhip", "rkne")),
    ("shin", ("lkne", "lank")), ("shin", ("rkne", "rank")),
    ("foot/ankle", ("lank", "lank")), ("foot/ankle", ("rank", "rank")),
]
LEVEL_M = dict(nose=1.68, leye=1.70, reye=1.70, lear=1.66, rear=1.66, lsho=1.46, rsho=1.46, lelb=1.10, relb=1.10,
               lwri=0.85, rwri=0.85, lhip=0.95, rhip=0.95, lkne=0.50, rkne=0.50, lank=0.08, rank=0.08)
STRIKERS = {"lank": "left foot", "rank": "right foot", "lkne": "left knee", "rkne": "right knee",
            "lwri": "left hand", "rwri": "right hand", "lelb": "left elbow", "relb": "right elbow"}
ABOVE_ANKLE_S = 0.85   # on the shin, the lowest 15% counts as the ankle
PART_RANK = {"foot/ankle": 0, "shin": 1, "thigh": 2, "forearm/hand": 2, "upper arm": 3, "torso": 3, "head": 4}


# ---------- small geometry ----------

def ind(label, value, confidence, observable=True, detail="", **extra):
    """One indicator. Not observable => value None, confidence 0."""
    if not observable:
        value, confidence = None, 0.0
    out = {"label": label, "value": value, "confidence": round(float(max(0.0, min(1.0, confidence))), 2),
           "observable": bool(observable), "detail": detail}
    out.update(extra)
    return out


def seg_dist(p, a, b):
    """Distance from p to segment ab and the parameter s in [0, 1] of the nearest point."""
    p, a, b = (np.asarray(v, float) for v in (p, a, b))
    ab = b - a
    denom = float(ab @ ab)
    s = 0.0 if denom < 1e-9 else float(np.clip((p - a) @ ab / denom, 0, 1))
    return float(np.linalg.norm(p - (a + s * ab))), s


def iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def overlap(a, b):
    """Intersection over the smaller box (1 = one player's box inside the other's)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1e-6, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def camera_from_homography(G, width, height):
    """Camera from a pitch->image homography G (pitch metres [x, y, 1] -> pixels).

    Model: K = [[f, 0, w/2], [0, f, h/2], [0, 0, 1]], G ~ K [r1 r2 t] (Zhang). f from the two
    orthogonality constraints on r1, r2 (least squares in 1/f^2). Returns {"P": 3x4, "C": centre,
    "up": +1/-1} (world height = up * z; the pitch frame is left-handed seen from the camera, so the
    sign is fixed by requiring the camera above the grass) or None when degenerate.
    """
    G = np.asarray(G, float)
    T = np.array([[1, 0, width / 2], [0, 1, height / 2], [0, 0, 1.0]])
    A = np.linalg.solve(T, G)
    a1, a2 = A[:, 0], A[:, 1]
    # (a1x a2x + a1y a2y) w + a1z a2z = 0 ; (|a1xy|^2 - |a2xy|^2) w + (a1z^2 - a2z^2) = 0, w = 1/f^2
    M = np.array([[a1[0] * a2[0] + a1[1] * a2[1]], [a1[0] ** 2 + a1[1] ** 2 - a2[0] ** 2 - a2[1] ** 2]])
    y = -np.array([a1[2] * a2[2], a1[2] ** 2 - a2[2] ** 2])
    w = float(np.linalg.lstsq(M, y, rcond=None)[0][0])
    if not np.isfinite(w) or w <= 0:
        return None
    f = 1 / math.sqrt(w)
    Kc = np.diag([f, f, 1.0])
    B = np.linalg.solve(Kc, A)
    lam = 1 / math.sqrt(np.linalg.norm(B[:, 0]) * np.linalg.norm(B[:, 1]))
    if B[2, 2] * lam < 0:  # the pitch origin must be in front of the camera
        lam = -lam
    r1, r2, t = B[:, 0] * lam, B[:, 1] * lam, B[:, 2] * lam
    U, _, Vt = np.linalg.svd(np.c_[r1, r2, np.cross(r1, r2)])
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R[:, 2] *= -1
    C = -R.T @ t
    if abs(C[2]) < 1.0:  # camera less than 1 m above the grass: not a broadcast camera, decomposition failed
        return None
    # Projection that reproduces G exactly on the grass (the SVD-orthonormalised R does not): the
    # height column c follows from P C = 0, so only the camera centre comes from the decomposition.
    c = -(G[:, 2] + C[0] * G[:, 0] + C[1] * G[:, 1]) / C[2]
    P = np.c_[G[:, 0], G[:, 1], c, G[:, 2]]
    return {"P": P, "C": C, "up": 1.0 if C[2] > 0 else -1.0, "f": f}


def height_above_ground(cam, uv, X, Y):
    """Height (m) of the image point uv on the vertical above pitch point (X, Y)."""
    P = cam["P"]
    base = P @ np.array([X, Y, 0.0, 1.0])
    dz = P[:, 2]
    u, v = uv
    a = np.array([dz[0] - u * dz[2], dz[1] - v * dz[2]])
    b = -np.array([base[0] - u * base[2], base[1] - v * base[2]])
    z = float(a @ b / (a @ a)) if a @ a > 1e-12 else float("nan")
    return cam["up"] * z


def ray_tan(cam, X, Y):
    """tan of the camera ray's depression angle at ground point (X, Y): a horizontal offset d of the
    measured point along the view direction turns into a height error of about d * tan."""
    C = cam["C"]
    return abs(C[2]) / max(1e-6, math.hypot(X - C[0], Y - C[1]))


def project(G, xy):
    p = G @ np.array([xy[0], xy[1], 1.0])
    return p[:2] / p[2]


def skeleton_height(kps, name_a, name_b, s):
    """Standard-body height (m) at parameter s along a segment (upright body assumption)."""
    return LEVEL_M[name_a] + s * (LEVEL_M[name_b] - LEVEL_M[name_a])


def visible(kps, name):
    return kps is not None and kps[K[name], 2] >= KP_CONF


def pt(kps, name):
    return kps[K[name], :2]


def body_height_px(kps, box):
    """Image height of a body: box height, or head-to-ankle span if larger (box clipped by occlusion)."""
    h = box[3] - box[1]
    if kps is not None:
        ys = kps[kps[:, 2] >= KP_CONF, 1]
        if len(ys) >= 2:
            h = max(h, float(ys.max() - ys.min()))
    return max(h, 1.0)


def nearest_contact(striker, struck, struck_h, strikers=STRIKERS):
    """Closest (striking point -> body segment) pair between two poses.

    Returns {"d": distance / struck body height, "striker": keypoint name, "part": body part,
    "seg": (a, b), "s": param, "point": image point on the struck body, "conf": keypoint confidence}
    or None when too few keypoints are visible."""
    best = None
    for sname in strikers:
        if not visible(striker, sname):
            continue
        p = pt(striker, sname)
        for part, (a, b) in SEGMENTS:
            if not (visible(struck, a) and visible(struck, b)):
                continue
            d, s = seg_dist(p, pt(struck, a), pt(struck, b))
            if part == "head":
                d = max(0.0, d - 0.06 * struck_h)  # head keypoints sit inside a ~11 cm radius head
            d /= struck_h
            better = best is None or d < best["d"] - 1e-6 or (abs(d - best["d"]) <= 1e-6 and PART_RANK[part] > PART_RANK[best["part"]])
            if better:
                A, B = pt(struck, a), pt(struck, b)
                best = {"d": d, "striker": sname, "part": part, "seg": (a, b), "s": s,
                        "point": (A + s * (B - A)).tolist(),
                        "conf": float(min(striker[K[sname], 2], struck[K[a], 2], struck[K[b], 2]))}
    return best


def above_ankle(part, s, seg):
    """Is the contact above the ankle? shin: parameter from knee (0) to ankle (1)."""
    if part == "foot/ankle":
        return False
    if part == "shin":
        return (s if seg[0].endswith("kne") else 1 - s) < ABOVE_ANKLE_S
    return True


def sole_facing(ankle, heel, toe, target):
    """cos of the angle between the sole's outward normal and the direction from the sole to the target.

    The sole is the heel -> toe line (Halpe26 heel and toe keypoints); its normal points away from the
    ankle, which sits above the sole. 1 = sole square-on to the target, 0 = foot edge-on or toe-first."""
    heel, toe, ankle, target = (np.asarray(v, float) for v in (heel, toe, ankle, target))
    f = toe - heel
    if np.linalg.norm(f) < 1e-6:
        return None
    f /= np.linalg.norm(f)
    n = np.array([-f[1], f[0]])
    mid = (heel + toe) / 2
    if n @ (mid - ankle) < 0:
        n = -n
    d = target - mid
    return 1.0 if np.linalg.norm(d) < 1e-6 else float(n @ d / np.linalg.norm(d))


def loc_quality(body_px, disagreement_px=None):
    """Confidence factor for image-plane contact geometry at this body size.

    Keypoint error in metres = max(LOC_FLOOR_PX, measured disagreement between two independent pose
    models, else LOC_DEFAULT_PX) / body height px * 1.80 m; the factor falls linearly to 0 at LOC_SCALE_M."""
    px = LOC_DEFAULT_PX if disagreement_px is None else max(LOC_FLOOR_PX, disagreement_px)
    err_m = px / max(1.0, body_px) * BODY_M
    return float(np.clip(1 - err_m / LOC_SCALE_M, 0.0, 1.0)), err_m


def knee_angle(kps, side):
    h, k, a = (pt(kps, side + n) for n in ("hip", "kne", "ank"))
    u, v = h - k, a - k
    c = u @ v / max(1e-6, np.linalg.norm(u) * np.linalg.norm(v))
    return math.degrees(math.acos(float(np.clip(c, -1, 1))))


# ---------- analysis.json helpers ----------

def _tracks(analysis):
    """{(shot, track_id): [(t, player dict, frame dict)]} sorted by t."""
    out = {}
    for f in analysis["frames"]:
        for p in f.get("players") or []:
            out.setdefault((f["shot"], p["track_id"]), []).append((f["t"], p, f))
    for v in out.values():
        v.sort(key=lambda e: e[0])
    return out


def _interp(track, t, key, max_gap=0.25):
    """Linear interpolation of a player field (list or scalar) between bracketing samples."""
    vals = [(tt, p[key]) for tt, p, _ in track if p.get(key) is not None]
    if not vals:
        return None
    before = [v for v in vals if v[0] <= t]
    after = [v for v in vals if v[0] >= t]
    if before and after:
        (t0, a), (t1, b) = before[-1], after[0]
        if t1 - t0 > 2 * max_gap:
            return None
        w = 0 if t1 == t0 else (t - t0) / (t1 - t0)
        return (np.asarray(a, float) * (1 - w) + np.asarray(b, float) * w).tolist()
    near = min(vals, key=lambda v: abs(v[0] - t))
    return near[1] if abs(near[0] - t) <= max_gap else None


def _xy(track, t):
    """Ground position at t: the per-frame foot anchor (v2 raw_x/raw_y) when present, since heights are
    measured against this frame's image; else x/y."""
    raw = any(p.get("raw_x") is not None for _, p, _ in track)
    x, y = _interp(track, t, "raw_x" if raw else "x"), _interp(track, t, "raw_y" if raw else "y")
    return None if x is None or y is None else (float(x), float(y))


def _velocity(track, t):
    """Ground velocity (m/s) near t: the analysis' own vx/vy (v2) or a finite difference over <= 0.6 s."""
    near = min(track, key=lambda e: abs(e[0] - t))
    p = near[1]
    if p.get("vx") is not None and p.get("vy") is not None and abs(near[0] - t) <= 0.2:
        return (float(p["vx"]), float(p["vy"])), "tracked velocity (analysis vx/vy)"
    pts = [(tt, q["x"], q["y"]) for tt, q, _ in track if q.get("x") is not None and abs(tt - t) <= 0.3]
    if len(pts) >= 2 and pts[-1][0] - pts[0][0] >= 0.15:
        (t0, x0, y0), (t1, x1, y1) = pts[0], pts[-1]
        v = ((x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0))
        if math.hypot(*v) <= MAX_SPEED_MPS:  # faster than a sprinter = track swap or calibration jump
            return v, "finite difference of tracked ground positions"
    return None, None


def find_candidates(analysis, contact_m=CONTACT_M, max_candidates=MAX_CANDIDATES):
    """Opposing-player proximity episodes in the sampled frames (see module docstring)."""
    hits = {}
    votes = {}  # per-box team labels flicker in v1 analyses: a pair counts as opponents by track majority
    for f in analysis["frames"]:
        for p in f.get("players") or []:
            if p.get("team") in ("A", "B"):
                votes.setdefault((f["shot"], p["track_id"]), Counter())[p["team"]] += 1
    team = {k: v.most_common(1)[0][0] for k, v in votes.items()}
    for f in analysis["frames"]:
        ok = bool((f.get("calibration") or {}).get("ok"))
        players = [p for p in f.get("players") or [] if p.get("role") in ("player", "goalkeeper") and (f["shot"], p["track_id"]) in team]
        for i, a in enumerate(players):
            for b in players[i + 1:]:
                if team[(f["shot"], a["track_id"])] == team[(f["shot"], b["track_id"])]:
                    continue
                if ok and None not in (a.get("x"), b.get("x")):
                    d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                    hit, score = d <= contact_m, d
                else:
                    ha, hb = a["bbox"][3] - a["bbox"][1], b["bbox"][3] - b["bbox"][1]
                    # feet at a similar image depth (loose: a lunging or falling player's box bottom leaves the grass)
                    same_depth = abs(a["bbox"][3] - b["bbox"][3]) <= 0.5 * max(ha, hb)
                    o = overlap(a["bbox"], b["bbox"])
                    hit, score = o > 0 and same_depth, contact_m * (1 - o)  # comparable ranking scale
                if hit:
                    key = (f["shot"],) + tuple(sorted((a["track_id"], b["track_id"])))
                    hits.setdefault(key, []).append((f["t"], score, ok))
    cands = []
    for (shot, ta, tb), hs in hits.items():
        hs.sort()
        run = [hs[0]]
        for h in hs[1:] + [None]:
            if h is not None and h[0] - run[-1][0] <= MERGE_GAP_S:
                run.append(h)
                continue
            cands.append({"shot": shot, "track_ids": [ta, tb], "t0": run[0][0], "t1": run[-1][0],
                          "min_score": min(r[1] for r in run), "calibrated": any(r[2] for r in run), "hits": len(run),
                          "closeness": sum(contact_m - r[1] for r in run)})
            run = [h] if h is not None else []
    # sustained close interaction first: one-frame overlaps are usually players crossing in depth
    cands.sort(key=lambda c: -c["closeness"])
    return cands[:max_candidates], len(cands)


# ---------- DOGSO ----------

def attacked_goal(analysis, shot, challenger_team, victim_vel=None):
    """x of the goal line the victim's team attacks (the challenger's team defends) + basis + confidence."""
    keepers = [p["x"] for f in analysis["frames"] if f["shot"] == shot for p in f.get("players") or []
               if p.get("role") == "goalkeeper" and p.get("team") == challenger_team and p.get("x") is not None]
    if keepers:
        return (0.0 if np.median(keepers) < PITCH_L / 2 else PITCH_L), "defending goalkeeper's position", 0.9
    xs = [p["x"] for f in analysis["frames"] if f["shot"] == shot for p in f.get("players") or []
          if p.get("team") == challenger_team and p.get("x") is not None]
    if len(xs) >= 6 and abs(np.mean(xs) - PITCH_L / 2) > 5:
        return (0.0 if np.mean(xs) < PITCH_L / 2 else PITCH_L), "defending team's mean position (heuristic)", 0.5
    if victim_vel is not None and abs(victim_vel[0]) >= 2:
        return (PITCH_L if victim_vel[0] > 0 else 0.0), "the fouled player's running direction (heuristic)", 0.4
    return None, "could not infer which goal is attacked", 0.0


def in_triangle(p, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def goal_corridor(victim, goal_x, margin=3.0):
    """Triangle from the victim to the goalposts, widened by `margin` m at the goal line."""
    return (tuple(victim), (goal_x, PITCH_W / 2 - GOAL_HALF_W - margin), (goal_x, PITCH_W / 2 + GOAL_HALF_W + margin))


def view_fraction(G, width, height, tri, n=200):
    """Share of the corridor triangle that the camera actually sees (points inside the image)."""
    rng = np.random.default_rng(0)
    a, b, c = (np.asarray(v, float) for v in tri)
    r = rng.random((n, 2))
    r[r.sum(1) > 1] = 1 - r[r.sum(1) > 1]
    pts = a + r[:, :1] * (b - a) + r[:, 1:] * (c - a)
    img = np.c_[pts, np.ones(n)] @ G.T
    ok = img[:, 2] > 1e-9
    uv = img[:, :2] / np.where(ok, img[:, 2], 1)[:, None]
    ok &= (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    return float(ok.mean())


def dogso_factors(frame, G, size, challenger, victim, goal, victim_vel):
    """IFAB DOGSO considerations from one calibrated frame. `challenger`/`victim`: player dicts."""
    goal_x, basis, gconf = goal
    na = lambda label, why: ind(label, None, 0, False, why)
    labels = ["Distance to goal", "Direction of play", "Likelihood of control", "Defenders between attacker and goal",
              "Attackers in support", "Offence inside the offender's penalty area"]
    if frame is None or G is None:
        why = "No calibrated frame near the contact, so pitch positions are unknown."
        return {k: na(lab, why) for k, lab in zip(("distance_to_goal", "direction_of_play", "control", "defenders_between", "attackers", "in_penalty_area"), labels)}, None
    if goal_x is None:
        why = "Which goal is being attacked could not be inferred."
        return {k: na(lab, why) for k, lab in zip(("distance_to_goal", "direction_of_play", "control", "defenders_between", "attackers", "in_penalty_area"), labels)}, None
    v = np.array([victim["x"], victim["y"]])
    goal_c = np.array([goal_x, PITCH_W / 2])
    dist = float(np.linalg.norm(goal_c - v))
    out = {"distance_to_goal": ind("Distance to goal", round(dist, 1), 0.8 * gconf, detail=f"Goal attacked: x={goal_x:g} ({basis}).", unit="m")}
    if victim_vel is None:
        out["direction_of_play"] = na("Direction of play", "The fouled player's velocity is unknown (track too short).")
    else:
        vv = np.asarray(victim_vel, float)
        speed = float(np.linalg.norm(vv))
        cos = float(vv @ (goal_c - v) / max(1e-6, speed * dist))
        val = "towards_goal" if cos >= 0.5 and speed >= 1.0 else "away_from_goal" if cos < 0 else "across"
        out["direction_of_play"] = ind("Direction of play", val, min(0.85, 0.3 + speed / 8) * gconf,
                                       detail=f"Fouled player moving {speed:.1f} m/s, {math.degrees(math.acos(np.clip(cos, -1, 1))):.0f} deg off the line to goal.",
                                       cos_to_goal=round(cos, 2), speed_mps=round(speed, 1))
    ball = frame.get("ball")
    if not ball or ball.get("x") is None:
        out["control"] = na("Likelihood of control", "Ball not located in the calibrated frame nearest the contact.")
    else:
        bd = float(math.hypot(ball["x"] - v[0], ball["y"] - v[1]))
        airborne = ball.get("airborne")
        conf = 0.7 * min(1.0, ball.get("confidence", 0.5) + 0.3) * (0.6 if airborne is None else 1.0 if not airborne else 0.5)
        out["control"] = ind("Likelihood of control", round(bd, 1), conf, unit="m",
                             detail=f"Ball {bd:.1f} m from the fouled player" + (" (ball may be in the air; ground projection)" if airborne is not False else "") + ".")
    tri = goal_corridor(v, goal_x)
    seen = view_fraction(G, *size, tri)
    players = [p for p in frame.get("players") or [] if p.get("x") is not None and p.get("role") != "referee"]
    defenders = [p for p in players if p.get("team") == challenger["team"] and p["track_id"] != challenger["track_id"]
                 and in_triangle((p["x"], p["y"]), *tri)]
    attackers = [p for p in players if p.get("team") == victim["team"] and p["track_id"] != victim["track_id"]
                 and abs(p["x"] - goal_x) < abs(v[0] - goal_x) + 2]
    locs = [{"track_id": p["track_id"], "role": p["role"], "x": p["x"], "y": p["y"],
             "distance_m": round(float(math.hypot(p["x"] - v[0], p["y"] - v[1])), 1)} for p in defenders]
    n_gk = sum(p["role"] == "goalkeeper" for p in defenders)
    out["defenders_between"] = ind(
        "Defenders between attacker and goal", len(defenders), (0.3 + 0.6 * seen) * gconf,
        detail=(f"{len(defenders)} opponent(s) besides the offender in the corridor to goal ({n_gk} goalkeeper); "
                f"{seen:.0%} of that corridor is in camera view" + ("" if seen >= 0.9 else ", so players off-screen cannot be counted") + "."),
        outfield=len(defenders) - n_gk, goalkeepers=n_gk, locations=locs, corridor_in_view=round(seen, 2))
    out["attackers"] = ind("Attackers in support", len(attackers), 0.5 * gconf, detail="Team-mates of the fouled player level with or nearer the goal (in view).")
    box = abs(v[0] - goal_x) <= BOX_L and abs(v[1] - PITCH_W / 2) <= BOX_HALF_W
    edge = min(abs(abs(v[0] - goal_x) - BOX_L), abs(abs(v[1] - PITCH_W / 2) - BOX_HALF_W))
    out["in_penalty_area"] = ind("Offence inside the offender's penalty area", bool(box), (0.9 if edge > 1.0 else 0.5) * gconf,
                                 detail="Location = fouled player's tracked ground position at the contact" + (" (within 1 m of the box line)" if edge <= 1.0 else "") + ".")
    return out, tri


# ---------- pose pass ----------

def _crop(frame, boxes, margin=0.6, target=None):
    target = target or CROP_TARGET_PX
    x1 = min(b[0] for b in boxes); y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes); y2 = max(b[3] for b in boxes)
    m = margin * max(b[3] - b[1] for b in boxes)
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = int(max(0, x1 - m)), int(max(0, y1 - m)), int(min(w, x2 + m)), int(min(h, y2 + m))
    crop = frame[y1:y2, x1:x2]
    s = float(np.clip(target / max(1, max(crop.shape[:2])), 1.0, 6.0))
    if s > 1.0:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return crop, (x1, y1), s


def _match(det_boxes, targets):
    """Greedy IoU assignment of pose detections to the two target boxes."""
    pairs = sorted(((iou(d, t), i, j) for i, d in enumerate(det_boxes) for j, t in enumerate(targets)), reverse=True)
    used_d, out = set(), [None] * len(targets)
    for o, i, j in pairs:
        if o < 0.25 or i in used_d or out[j] is not None:
            continue
        used_d.add(i)
        out[j] = i
    return out


def _shift(g0, g1):
    (dx, dy), _ = cv2.phaseCorrelate(g0, g1)
    return np.array([dx, dy]) * 4  # grays are 1/4 scale


def _gray(frame):
    h, w = frame.shape[:2]
    return np.float32(cv2.cvtColor(cv2.resize(frame, (w // 4, h // 4), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))


class Homographies:
    """pitch->image homography per full-rate frame: nearest calibrated sampled frame of the same shot
    (<= NEAR_SAMPLE_S away) whose homography is available, moved by the image shift between the two
    frames (camera pan). Never across a cut (same shot only)."""

    def __init__(self, analysis, pitch_model, device):
        self.frames = [f for f in analysis["frames"] if (f.get("calibration") or {}).get("ok")]
        self.pitch_model, self.device, self.cache = pitch_model, device, {}

    def sample_G(self, f, image):
        key = f["t"]
        if key not in self.cache:
            G = (f.get("calibration") or {}).get("homography")
            if G is not None:
                G = np.asarray(G, float)
            elif self.pitch_model is not None and image is not None:
                from . import pitch  # recompute: v1 analyses do not store the homography
                r = self.pitch_model.predict(image, device=self.device, verbose=False)[0]
                kps = r.keypoints.data[0].cpu().numpy() if r.keypoints is not None and len(r.keypoints.data) else None
                cal = pitch.calibrate_frame(image, kps) if kps is not None else {"ok": False}
                G = np.linalg.inv(cal["H"]) if cal["ok"] else None
            self.cache[key] = G
        return self.cache[key]

    def near(self, shot, t):
        return sorted((f for f in self.frames if f["shot"] == shot and abs(f["t"] - t) <= NEAR_SAMPLE_S),
                      key=lambda f: abs(f["t"] - t))


def decode_span(cap, fps, t0, t1, boxes_at, homs, shot):
    """Decode [t0, t1] at the full frame rate: frame, interpolated boxes and pitch->image homography."""
    f0, f1 = int(round(t0 * fps)), int(round(t1 * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    recs = []
    for i in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        t = i / fps
        recs.append({"t": t, "i": i, "boxes": boxes_at(t), "kps": [None, None], "posed": False, "gray": _gray(frame), "frame": frame})
    # per-frame homography: nearest calibrated sample, shifted by camera motion between the two frames
    for rec in recs:
        rec["G"] = rec["G_sample"] = None
        for f in homs.near(shot, rec["t"]):
            src = next((r for r in recs if abs(r["t"] - f["t"]) < 0.5 / fps), None)
            G = homs.sample_G(f, src["frame"] if src else None)
            if G is not None:
                break
        else:
            continue
        rec["G_sample"] = (f, G)
        if src is not None and src is not rec:
            dx, dy = _shift(src["gray"], rec["gray"])
            G = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]]) @ G
        rec["G"] = G
    return recs


def run_pose(recs, models):
    """Pose both players in each record: YOLO pose on one upscaled crop around the pair per frame (batched);
    a player YOLO does not return (small, blurred or tangled) gets RTMPose top-down on its tracked box."""
    model, device = models.pose, models.device
    todo = [r for r in recs if not r["posed"] and None not in r["boxes"]]
    for k in range(0, len(todo), 8):
        batch = todo[k:k + 8]
        crops = [_crop(r["frame"], r["boxes"]) for r in batch]
        results = model.predict([c[0] for c in crops], device=device, verbose=False, conf=0.2)
        for r, (_, (ox, oy), s), res in zip(batch, crops, results):
            r["posed"] = True
            if res.keypoints is None or not len(res.boxes):
                continue
            db = res.boxes.xyxy.cpu().numpy().astype(float) / s + [ox, oy, ox, oy]
            kd = res.keypoints.data.cpu().numpy().astype(float)
            kd[..., :2] = kd[..., :2] / s + [ox, oy]
            for j, di in enumerate(_match(db, r["boxes"])):
                if di is not None:
                    r["kps"][j] = kd[di]
    for r in todo:
        miss = [j for j in (0, 1) if r["kps"][j] is None]
        if miss and models.foot is not None:
            for j, w in zip(miss, models.whole_body(r["frame"], [r["boxes"][j] for j in miss])):
                r["kps"][j] = w[:17]
                r.setdefault("rtm", set()).add(j)
        if _same_person(*r["kps"]):  # two detections of one body: the pair is not resolved in this frame
            r["kps"] = [None, None]


def _same_person(a, b):
    if a is None or b is None:
        return False
    both = (a[:, 2] >= KP_CONF) & (b[:, 2] >= KP_CONF)
    if both.sum() < 4:
        return False
    span = max(1.0, float(np.ptp(a[both, 1])))
    return float(np.linalg.norm(a[both, :2] - b[both, :2], axis=1).mean()) < 0.1 * span


# ---------- per-candidate measurement ----------

class Models:
    """Everything measure() runs: YOLO pose (both players, every frame), RTMPose Halpe26 (feet, and a
    second opinion on keypoint positions, contact frames only) and the ball detector (contact frames only)."""

    def __init__(self, device):
        from ultralytics import YOLO
        self.device = device
        self.pose = YOLO(str(WEIGHTS / POSE_WEIGHTS))
        self.ball = YOLO(str(WEIGHTS / BALL_WEIGHTS)) if (WEIGHTS / BALL_WEIGHTS).exists() else None
        self.foot = None
        if (WEIGHTS / FOOT_WEIGHTS).exists():
            import onnxruntime as ort
            from rtmlib import RTMPose
            coreml = "CoreMLExecutionProvider" in ort.get_available_providers()
            self.foot = RTMPose(str(WEIGHTS / FOOT_WEIGHTS), model_input_size=(288, 384), backend="onnxruntime",
                                device="mps" if coreml else "cpu")
            so = ort.SessionOptions()
            so.intra_op_num_threads, so.inter_op_num_threads = CPU_THREADS, 1
            self.foot.session = ort.InferenceSession(str(WEIGHTS / FOOT_WEIGHTS), sess_options=so,
                                                     providers=self.foot.session.get_providers())

    def whole_body(self, frame, boxes):
        """Halpe26 keypoints (26 x 3, score clipped to 0..1) per box, or None without the model."""
        if self.foot is None:
            return [None] * len(boxes)
        k, sc = self.foot(frame, [list(map(float, b)) for b in boxes])
        return [np.c_[k[j], np.clip(sc[j], 0, 1)] for j in range(len(boxes))]

    def ball_near(self, recs, boxes_of):
        """Best ball detection per frame: ball model on an upscaled crop around the pair and on the full
        frame (imgsz 1280). Returns [(rec, (u, v), confidence)]."""
        if self.ball is None or not recs:
            return []
        crops, metas = [], []
        for r in recs:
            bx = boxes_of(r)
            crop, origin, s = _crop(r["frame"], bx, margin=1.5, target=640)
            crops.append(crop)
            metas.append((origin, s))
        out = []
        for k in range(0, len(recs), 8):
            rc = self.ball.predict(crops[k:k + 8], device=self.device, verbose=False, conf=0.2, imgsz=640)
            rf = self.ball.predict([r["frame"] for r in recs[k:k + 8]], device=self.device, verbose=False, conf=0.2, imgsz=1280)
            for r, a, b, ((ox, oy), s) in zip(recs[k:k + 8], rc, rf, metas[k:k + 8]):
                best = None
                for res, scale, off in ((a, s, (ox, oy)), (b, 1.0, (0, 0))):
                    if len(res.boxes):
                        j = int(res.boxes.conf.argmax())
                        x1, y1, x2, y2 = res.boxes.xyxy[j].cpu().numpy() / scale
                        c = float(res.boxes.conf[j])
                        if best is None or c > best[2]:
                            best = (r, ((x1 + x2) / 2 + off[0], (y1 + y2) / 2 + off[1]), c)
                if best:
                    out.append(best)
        return out


def _feet(kps, box, wb=None):
    """Image points of a player's feet: toes/heels (Halpe26) and ankles where visible, else the box bottom."""
    pts = [wb[i, :2] for i in H26.values() if wb is not None and wb[i, 2] >= KP_CONF]
    pts += [pt(kps, n) for n in ("lank", "rank") if visible(kps, n)]
    return pts or [np.array([(box[0] + box[2]) / 2, box[3]], float)]


def _foot_ball_m(r, j, uv, wb=None):
    """Nearest foot of player j to the ball image point, in metres at the player's own image scale."""
    kps, box = r["kps"][j], r["boxes"][j]
    d = min(float(np.linalg.norm(np.asarray(uv) - p)) for p in _feet(kps, box, wb))
    return d / body_height_px(kps, box) * BODY_M


def _studs(models, recs, ic, ci, side, target, loc_q):
    """Sole towards the opponent, from Halpe26 heel/big toe/small toe within ~0.1 s of the contact, using only
    frames where that foot is AT the struck point (sole midpoint within 0.2 body heights of it): earlier in the
    swing the foot is elsewhere and its orientation says nothing about the contact. Of those, the frame where
    the foot is both confidently detected and least foreshortened is used."""
    label = "Studs / sole towards the opponent"
    span = max(2, round(0.1 * _fps(recs)))
    best = None
    for r in recs[max(0, ic - span):ic + span + 1]:
        if r["kps"][ci] is None and r is not recs[ic]:
            continue
        w = models.whole_body(r["frame"], [r["boxes"][ci]])[0]
        idx = [K[side + "kne"], K[side + "ank"], H26[side + "heel"], H26[side + "bt"], H26[side + "st"]]
        q = float(w[idx, 2].min())
        knee, ankle = w[K[side + "kne"], :2], w[K[side + "ank"], :2]
        heel, toe = w[H26[side + "heel"], :2], (w[H26[side + "bt"], :2] + w[H26[side + "st"], :2]) / 2
        if np.linalg.norm((heel + toe) / 2 - np.asarray(target)) > 0.2 * body_height_px(w[:17], r["boxes"][ci]):
            continue  # the foot is not at the contact point in this frame
        ratio = float(np.linalg.norm(toe - heel)) / max(1.0, 0.6 * float(np.linalg.norm(ankle - knee)))  # boot ~0.6 shank
        score = q * min(1.0, ratio / 0.7)
        if best is None or score > best[0]:
            best = (score, q, ratio, ankle, heel, toe, r)
    if best is None or best[1] < 0.3:
        return ind(label, None, 0, False, "Heel and toes of the contact foot are not visible at the contact point (occluded or not resolved).")
    _, q, ratio, ankle, heel, toe, r = best
    if ratio < 0.35:
        return ind(label, None, 0, False, f"In every frame around the contact the foot points along the camera's line of sight "
                                          f"(heel-toe at most {ratio:.0%} of its expected length), so which way the sole faces "
                                          "cannot be read from this one view.")
    # the sole is judged against the opponent's body point that was struck, as seen in that frame
    cosv = sole_facing(ankle, heel, toe, target)
    conf = q * min(1.0, ratio / 0.7) * loc_q * (0.9 if abs(cosv - 0.6) > 0.2 else 0.6)
    return ind(label, bool(cosv >= 0.6), conf,
               detail=(f"Sole normal (heel-toe line, Halpe26 foot keypoints at {r['t']:.2f} s, min score {q:.2f}, foot "
                       f"{ratio:.0%} of its expected length) vs direction to the contact point: cos = {cosv:.2f} (>= 0.6 counts)."),
               sole_cos=round(cosv, 2), heel=[round(float(v), 1) for v in heel], toe=[round(float(v), 1) for v in toe],
               frame_t=round(r["t"], 3))


def _fps(recs):
    return 1.0 / max(1e-6, recs[1]["t"] - recs[0]["t"]) if len(recs) > 1 else 30.0


def _onset(posed):
    """(frame, striker index, contact) at the contact ONSET: the first frame where a striking point
    touches the other body (later frames are usually the tangle after impact). Without any touching
    frame, the closest approach. Frames must be sorted by time."""
    closest = (posed[0], 0, None)
    for r in posed:
        cs = [(j, nearest_contact(r["kps"][j], r["kps"][1 - j], body_height_px(r["kps"][1 - j], r["boxes"][1 - j]))) for j in (0, 1)]
        cs = [(j, c) for j, c in cs if c]
        if not cs:
            continue
        j, c = min(cs, key=lambda jc: jc[1]["d"])
        if c["d"] <= TOUCH:
            return r, j, c
        if closest[2] is None or c["d"] < closest[2]["d"]:
            closest = (r, j, c)
    return closest


def measure(cand, analysis, tracks, cap, fps, size, models, homs, debug_dir=None):
    shot = next(s for s in analysis["shots"] if s["id"] == cand["shot"])
    ta, tb = (tracks[(cand["shot"], tid)] for tid in cand["track_ids"])
    t0, t1 = max(shot["start"], cand["t0"] - PAD_S), min(shot["end"], cand["t1"] + PAD_S)
    boxes_at = lambda t: [_interp(ta, t, "bbox"), _interp(tb, t, "bbox")]
    recs = decode_span(cap, fps, t0, t1, boxes_at, homs, cand["shot"])
    # coarse-to-fine: pose at ~COARSE_HZ over the span, then every frame around the contact onset
    step = max(1, round(fps / COARSE_HZ))
    run_pose(recs[::step], models)
    both = lambda: [r for r in recs if r["kps"][0] is not None and r["kps"][1] is not None]
    if both():
        k = recs.index(_onset(both())[0])
        run_pose(recs[max(0, k - step):k + step + 1], models)
    posed = both()
    notes = []
    base = {"shot": cand["shot"], "t_range": [round(t0, 3), round(t1, 3)], "frames_examined": len(recs),
            "frames_with_both_poses": len(posed), "frames_with_rtmpose_fallback": sum(bool(r.get("rtm")) for r in posed), "candidate": {k: cand[k] for k in ("t0", "t1", "hits", "calibrated")}}
    if not posed:
        base.update(t=round((cand["t0"] + cand["t1"]) / 2, 3), players=_players(cand, ta, tb, None), notes=[
            "Neither pose could be recovered for both players in the same frame (occlusion or too small)."],
            indicators=_unobservable("Pose not recovered for both players."), dogso=dogso_factors(None, None, size, None, None, (None, "", 0), None)[0])
        return base

    # contact frame + direction
    best = _onset(posed)
    if best[2] is None:
        base.update(t=round(posed[len(posed) // 2]["t"], 3), players=_players(cand, ta, tb, None),
                    notes=["Too few keypoints visible to measure contact."],
                    indicators=_unobservable("Too few keypoints visible."), dogso=dogso_factors(None, None, size, None, None, (None, "", 0), None)[0])
        return base
    rec, j, contact = best
    # The same frame measured the other way round: symmetric foot-to-foot contact needs a tie-break.
    rev = nearest_contact(rec["kps"][1 - j], rec["kps"][j], body_height_px(rec["kps"][j], rec["boxes"][j]))
    t_c = rec["t"]
    ic = recs.index(rec)
    # ball detected directly in the full-rate frames just before/at the contact (not the analysis' samples)
    near = [r for r in recs if t_c - 0.3 <= r["t"] <= t_c + 0.1 and None not in r["boxes"]]
    balls = models.ball_near(near[::max(1, round(fps / 20))], lambda r: r["boxes"])
    at_contact = min(balls, key=lambda b: abs(b[0]["t"] - t_c)) if balls else None
    if at_contact and abs(at_contact[0]["t"] - t_c) <= 0.1 and at_contact[0]["kps"][0] is not None and at_contact[0]["kps"][1] is not None:
        ball_d = [_foot_ball_m(at_contact[0], k, at_contact[1]) / BODY_M for k in (0, 1)]
    else:
        ball_d = [_ball_image_dist(analysis, cand["shot"], t_c, box) for box in rec["boxes"]]
    basis = f"its {STRIKERS[contact['striker']]} is the striking point closest to the other player's body"
    if rev and abs(rev["d"] - contact["d"]) < 0.03 and PART_RANK[rev["part"]] == PART_RANK[contact["part"]]:
        if None not in ball_d and abs(ball_d[0] - ball_d[1]) > 0.3:
            vic = int(np.argmin(ball_d))  # the player nearer the ball is taken as the one fouled
            if vic == j:
                j, contact = 1 - j, rev
            basis = "contact is symmetric (limb to limb); the player further from the ball is taken as the challenger"
        else:
            basis += " (contact is nearly symmetric and the ball does not separate them: low confidence)"
    ci, vi = j, 1 - j
    chal_track, vic_track = (ta, tb) if ci == 0 else (tb, ta)
    ck, vk = rec["kps"][ci], rec["kps"][vi]
    vh = body_height_px(vk, rec["boxes"][vi])
    ch = body_height_px(ck, rec["boxes"][ci])
    # Second pose model (RTMPose, top-down on each box) re-measures the same contact on the same frame: how
    # far its striker-to-body distance differs from YOLO's is the measured error of the contact geometry
    # (instead of an error assumed from body size), and whether it lands on the same body part is checked.
    wb = models.whole_body(rec["frame"], [rec["boxes"][ci], rec["boxes"][vi]])
    c2 = dis = None
    if wb[0] is not None:
        c2 = nearest_contact(wb[0][:17], wb[1][:17], vh, strikers=[contact["striker"]])
        dis = None if c2 is None else abs(c2["d"] - contact["d"]) * vh
    size_q, loc_err_m = loc_quality(min(vh, ch), dis)
    part_agree = c2 is None or c2["part"] == contact["part"]
    G = rec["G"]
    cam = camera_from_homography(G, *size) if G is not None else None
    vxy, cxy = _xy(vic_track, t_c), _xy(chal_track, t_c)
    indicators = {}

    touching = contact["d"] <= TOUCH
    c_conf = contact["conf"] * size_q * (1.0 if contact["d"] <= TOUCH / 2 or contact["d"] >= NEAR else 0.7)
    detail = (f"{STRIKERS[contact['striker']]} of the challenger within {contact['d'] * BODY_M * 100:.0f} cm "
              f"(image plane, scaled to a 1.80 m body) of the victim's {contact['part']}.")
    if cam and vxy and cxy:
        gd = math.hypot(vxy[0] - cxy[0], vxy[1] - cxy[1])
        detail += f" Tracked ground positions {gd:.1f} m apart."
        if gd > 2.0:
            touching, c_conf = False, c_conf * 0.8
            detail += " Too far apart on the ground for contact: the overlap is a depth illusion."
    else:
        c_conf *= 0.85
        detail += " Depth not verified (no calibration): image-plane contact only."
    if c2 is not None:
        detail += (f" Second pose model: {c2['d'] * BODY_M * 100:.0f} cm to the {c2['part']}"
                   + ("" if part_agree else " (different body part)") + ".")
    if contact["d"] >= NEAR:
        touching = False
    indicators["contact"] = ind("Contact", bool(touching), c_conf if (touching or contact["d"] >= NEAR) else c_conf * 0.5,
                                detail=detail, body_part=contact["part"], striking_part=STRIKERS[contact["striker"]],
                                image_distance_body=round(contact["d"], 3))

    # contact height / above ankle
    s_param = contact["s"]
    aa = above_ankle(contact["part"], s_param, contact["seg"])
    h_model = skeleton_height(vk, *contact["seg"], s_param)
    if cam and vxy:
        h = height_above_ground(cam, contact["point"], *vxy)
        unc = LIMB_OFFSET_M * ray_tan(cam, *vxy) + 0.1
        indicators["contact_above_ankle"] = ind(
            "Contact above the ankle", aa, contact["conf"] * size_q * (0.9 if touching else 0.5) * (1.0 if part_agree else 0.6),
            detail=f"Victim's {contact['part']}; contact point {h:.2f} m +- {unc:.2f} m above the grass (camera geometry).",
            height_m=round(h, 2), height_uncertainty_m=round(unc, 2), method="camera")
    else:
        indicators["contact_above_ankle"] = ind(
            "Contact above the ankle", aa, contact["conf"] * size_q * (0.75 if touching else 0.45) * (1.0 if part_agree else 0.6),
            detail=f"Victim's {contact['part']}; about {h_model:.2f} m up an upright 1.80 m body (skeleton proportions; no calibration).",
            height_m=round(h_model, 2), height_uncertainty_m=0.25, method="skeleton")

    # challenger speed
    vel, how = _velocity(chal_track, t_c)
    if vel is None:
        indicators["challenger_speed"] = ind("Challenger speed at contact", None, 0, False,
                                             "No calibrated track around the contact, so ground speed in m/s is unknown.")
    else:
        sp = math.hypot(*vel)
        indicators["challenger_speed"] = ind("Challenger speed at contact", round(sp, 1), 0.7 if "vx/vy" in how else 0.55,
                                             detail=f"From {how}.", unit="m/s")

    # studs / sole
    foot = contact["striker"] in ("lank", "rank")
    side = contact["striker"][0]
    if not foot:
        indicators["studs_showing"] = ind("Studs / sole towards the opponent", False, contact["conf"] * size_q * 0.8,
                                          detail=f"Contact was made with the {STRIKERS[contact['striker']]}, not a foot.")
    elif not (visible(ck, side + "kne") and visible(ck, side + "ank")):
        indicators["studs_showing"] = ind("Studs / sole towards the opponent", None, 0, False, "Challenger's knee or ankle is occluded.")
    elif models.foot is None:
        indicators["studs_showing"] = ind("Studs / sole towards the opponent", None, 0, False,
                                          "Foot keypoint model not installed (run cv/setup.sh); COCO pose has no toes or heel.")
    else:
        indicators["studs_showing"] = _studs(models, recs, ic, ci, side, contact["point"], size_q)

    # both feet off the ground (lunge), in the 0.3 s up to the contact
    pre = [r for r in posed if t_c - 0.3 <= r["t"] <= t_c]
    indicators["both_feet_off_ground"] = _airborne(pre, ci, vi, chal_track, size)

    # straight leg + high foot
    if foot and all(visible(ck, side + n) for n in ("hip", "kne", "ank")):
        ang = knee_angle(ck, side)
        ank = pt(ck, side + "ank")
        if cam and cxy:
            fh = height_above_ground(cam, ank, *cxy)
            unc = LIMB_OFFSET_M * 2 * ray_tan(cam, *cxy) + 0.1  # an extended leg reaches ~0.8 m from the anchor
            high, how_h, conf_h = fh >= 0.5 + unc / 2, f"foot {fh:.2f} m +- {unc:.2f} m up (camera geometry)", 0.7
        else:
            vy = [pt(vk, n)[1] for n in ("lkne", "rkne") if visible(vk, n)]
            if vy:
                high, how_h, conf_h = bool(ank[1] < min(vy)), "foot compared with the victim's knee height in the image (players at similar depth)", 0.45
            else:
                high, how_h, conf_h = None, "", 0
        if high is None:
            indicators["straight_leg_high_foot"] = ind("Straight leg with a high foot", None, 0, False, "Victim's knees occluded; no height reference.")
        else:
            val = ang >= 155 and high
            indicators["straight_leg_high_foot"] = ind("Straight leg with a high foot", bool(val), conf_h * size_q * min(ck[K[side + n], 2] for n in ("hip", "kne", "ank")),
                                                       detail=f"Knee angle {ang:.0f} deg (>= 155 counts as straight); {how_h}.", knee_angle_deg=round(ang))
    elif not foot:
        indicators["straight_leg_high_foot"] = ind("Straight leg with a high foot", False, c_conf * 0.8, detail="Contact was not made with a leg.")
    else:
        indicators["straight_leg_high_foot"] = ind("Straight leg with a high foot", None, 0, False, "Challenger's hip, knee or ankle occluded.")

    # ball: is this a challenge for the ball?
    cb = _ball_ground_dist(analysis, cand["shot"], t_c, cxy)
    reach = [(_foot_ball_m(r, ci, uv), c, r["t"]) for r, uv, c in balls if r["kps"][ci] is not None and r["t"] <= t_c + 0.05]
    if reach:
        d_m, conf_b, t_b = min(reach)
        indicators["challenging_for_ball"] = ind(
            "Challenging for the ball", d_m <= BALL_REACH_M, conf_b * size_q * 0.85,
            detail=(f"Ball detected in the contact frames; closest to the challenger's foot {d_m:.1f} m at {t_b:.2f} s "
                    f"(<= {BALL_REACH_M:g} m counts; image plane at the player's own scale)."),
            ball_distance_m=round(d_m, 2), ball_frames=len(balls))
    elif cb is not None:
        d_m, conf_b = cb
        indicators["challenging_for_ball"] = ind("Challenging for the ball", d_m <= 2.5, conf_b,
                                                 detail=f"Ball {d_m:.1f} m from the challenger at the contact (<= 2.5 m counts as playable).", ball_distance_m=round(d_m, 1))
    elif ball_d[ci] is not None:
        d_b = ball_d[ci] * BODY_M
        indicators["challenging_for_ball"] = ind("Challenging for the ball", d_b <= 2.5, 0.4,
                                                 detail=f"Ball about {d_b:.1f} m from the challenger (image plane, scaled by body height).", ball_distance_m=round(d_b, 1))
    else:
        indicators["challenging_for_ball"] = ind("Challenging for the ball", None, 0, False, "Ball not detected near the contact.")

    # off-ball strike: hand/elbow to the head, with arm speed
    indicators["off_ball_strike"] = _arm_strike(posed, ci, vi, indicators["challenging_for_ball"])

    # DOGSO: calibrated sampled frame nearest the contact, same shot
    frame, fG = rec["G_sample"] or (None, None)  # positions are read in that sample's own image, so its own G
    cp = vp = None
    if frame is not None:
        cp = next((p for p in frame["players"] if p["track_id"] == (cand["track_ids"][ci])), None)
        vp = next((p for p in frame["players"] if p["track_id"] == (cand["track_ids"][vi])), None)
    vvel = _velocity(vic_track, t_c)[0]
    challenger_team = Counter(p["team"] for _, p, _ in chal_track if p.get("team")).most_common(1)[0][0]
    goal = attacked_goal(analysis, cand["shot"], challenger_team, vvel)
    if cp is None or vp is None or vp.get("x") is None:
        dogso, tri = dogso_factors(None, None, size, None, None, goal, None)
    else:
        dogso, tri = dogso_factors(frame, fG, size, cp, vp, goal, vvel)
    dogso["attempt_to_play_ball"] = _attempt(indicators, contact)
    dogso["attack_direction"] = {"goal_x": goal[0], "basis": goal[1], "confidence": goal[2]}

    if not cam:
        notes.append("No calibrated camera at the contact frame: heights use the victim's skeleton proportions and "
                     "ground speed / DOGSO factors are not observable.")
    notes.append(f"Challenger chosen because {basis}.")
    out = dict(base, t=round(t_c, 3), frame_index=rec["i"], calibrated=bool(cam),
               players=_players(cand, ta, tb, ci), indicators=indicators, dogso=dogso, notes=notes,
               pose_quality={"victim_height_px": round(vh), "challenger_height_px": round(ch), "size_factor": round(size_q, 2),
                             "keypoint_error_m": round(loc_err_m, 3), "pose_models_disagreement_px": None if dis is None else round(dis, 1),
                             "ball_frames": len(balls)})
    if debug_dir:
        _debug(debug_dir, rec, ci, vi, contact, out, tri)
    return out


def _players(cand, ta, tb, ci):
    def info(track):
        p = track[len(track) // 2][1]
        team = Counter(q["team"] for _, q, _ in track if q.get("team")).most_common(1)
        return {"track_id": p["track_id"], "global_id": p.get("global_id"), "team": team[0][0] if team else None, "role": p.get("role"),
                "jersey_number": p.get("jersey_number")}
    a, b = info(ta), info(tb)
    if ci is None:
        return {"challenger": None, "victim": None, "involved": [a, b]}
    return {"challenger": (a, b)[ci], "victim": (a, b)[1 - ci], "involved": [a, b]}


def _unobservable(why):
    keys = [("contact", "Contact"), ("contact_above_ankle", "Contact above the ankle"), ("challenger_speed", "Challenger speed at contact"),
            ("studs_showing", "Studs / sole towards the opponent"), ("both_feet_off_ground", "Both feet off the ground (lunge)"),
            ("straight_leg_high_foot", "Straight leg with a high foot"), ("challenging_for_ball", "Challenging for the ball"),
            ("off_ball_strike", "Hand / arm to the head")]
    return {k: ind(label, None, 0, False, why) for k, label in keys}


def _ball_frames(analysis, shot, t, max_dt=0.3):
    return [f for f in analysis["frames"] if f["shot"] == shot and f.get("ball") and abs(f["t"] - t) <= max_dt]


def _ball_image_dist(analysis, shot, t, box):
    """Ball image point to the player's feet, in body heights, at the sampled frame nearest t."""
    fs = _ball_frames(analysis, shot, t)
    if not fs or box is None:
        return None
    f = min(fs, key=lambda f: abs(f["t"] - t))
    u, v = f["ball"]["image"]
    foot = ((box[0] + box[2]) / 2, box[3])
    return math.hypot(u - foot[0], v - foot[1]) / max(1.0, box[3] - box[1])


def _ball_ground_dist(analysis, shot, t, xy):
    if xy is None:
        return None
    fs = [f for f in _ball_frames(analysis, shot, t) if f["ball"].get("x") is not None and (f.get("calibration") or {}).get("ok")]
    if not fs:
        return None
    f = min(fs, key=lambda f: abs(f["t"] - t))
    d = math.hypot(f["ball"]["x"] - xy[0], f["ball"]["y"] - xy[1])
    conf = 0.7 * (1 - abs(f["t"] - t) / 0.6) * (0.6 if f["ball"].get("airborne") in (None, True) else 1.0)
    return d, conf


def _airborne(pre, ci, vi, chal_track, size):
    """Both challenger ankles clear of the grass in >= 2 frames of the 0.3 s before contact.
    Physically implausible lifts (ankles > 1 m up: pose or identity errors) are discarded, not trusted."""
    label = "Both feet off the ground (lunge)"
    items, dropped = [], 0
    for r in pre:
        ck = r["kps"][ci]
        if not (visible(ck, "lank") and visible(ck, "rank")):
            continue
        G, cxy = r["G"], _xy(chal_track, r["t"])
        cam = camera_from_homography(G, *size) if G is not None else None
        size_q = min(1.0, body_height_px(ck, r["boxes"][ci]) / 150)
        kc = min(ck[K["lank"], 2], ck[K["rank"], 2]) * size_q
        if cam and cxy:
            hs = [height_above_ground(cam, pt(ck, a), *cxy) for a in ("lank", "rank")]
            unc = LIMB_OFFSET_M * ray_tan(cam, *cxy) + 0.1
            low = min(hs) - 0.08  # ankle keypoint sits ~8 cm above the sole
            item = (low, f"lower ankle {low:.2f} m +- {unc:.2f} m above the grass (camera geometry)", 0.65 * kc, low >= 0.15 + unc / 2)
        else:
            vk = r["kps"][vi]
            ys = [pt(vk, a)[1] for a in ("lank", "rank") if visible(vk, a)]
            if not ys:
                continue
            low = (max(ys) - max(pt(ck, "lank")[1], pt(ck, "rank")[1])) / body_height_px(vk, r["boxes"][vi]) * BODY_M
            item = (low, f"challenger's lower ankle {low:.2f} m above the victim's lower ankle (image, same-depth assumption)", 0.35 * kc, low >= 0.25)
        if low > MAX_ANKLE_LIFT_M:
            dropped += 1
            continue
        items.append(item)
    if not items:
        why = "The challenger's ankles are not both visible before the contact."
        if dropped:
            why = f"Ankle heights were implausible (> {MAX_ANKLE_LIFT_M:g} m) in {dropped} frame(s): pose or identity error."
        return ind(label, None, 0, False, why)
    flagged = [i for i in items if i[3]]
    best = max(flagged or items, key=lambda i: i[0])
    conf = float(np.mean([i[2] for i in items])) * (1.0 if len(flagged) != 1 else 0.5)  # a single-frame lift is weak evidence
    extra = f" {dropped} implausible frame(s) discarded." if dropped else ""
    return ind(label, len(flagged) >= 2, conf,
               detail=f"Both ankles clear of the grass in {len(flagged)}/{len(items)} frame(s) of the 0.3 s before contact; highest: {best[1]}.{extra}",
               lift_m=round(best[0], 2))


def _arm_strike(posed, ci, vi, ball_ind):
    label = "Hand / arm to the head"
    best = None
    seen_arms = False
    for idx, r in enumerate(posed):
        ck, vk = r["kps"][ci], r["kps"][vi]
        head = [pt(vk, n) for n in ("nose", "leye", "reye", "lear", "rear") if visible(vk, n)]
        arms = [n for n in ("lwri", "rwri", "lelb", "relb") if visible(ck, n)]
        if not head or not arms:
            continue
        seen_arms = True
        vh = body_height_px(vk, r["boxes"][vi])
        hc = np.mean(head, axis=0)
        for n in arms:
            d = max(0.0, float(np.linalg.norm(pt(ck, n) - hc)) - 0.06 * vh) / vh
            if best is None or d < best[0]:
                best = (d, n, idx, float(ck[K[n], 2]), vh)
    if not seen_arms:
        return ind(label, None, 0, False, "The challenger's arms or the victim's head are not visible.")
    d, n, idx, conf, vh = best
    speed = None
    if 0 < idx < len(posed) - 1:  # arm speed relative to the challenger's own shoulders, body-height scaled
        a, b = posed[idx - 1], posed[idx + 1]
        def rel(r):
            k = r["kps"][ci]
            sh = [pt(k, s) for s in ("lsho", "rsho") if visible(k, s)]
            return None if not visible(k, n) or not sh else pt(k, n) - np.mean(sh, axis=0)
        ra, rb = rel(a), rel(b)
        if ra is not None and rb is not None and b["t"] > a["t"]:
            speed = float(np.linalg.norm(rb - ra)) / vh * BODY_M / (b["t"] - a["t"])
    hit = d <= TOUCH
    detail = f"Closest {STRIKERS[n]} to the victim's head: {d * BODY_M * 100:.0f} cm (image plane)."
    if speed is not None:
        detail += f" Arm moving {speed:.1f} m/s relative to the shoulders at that moment."
    if ball_ind["observable"] and ball_ind["value"] is False:
        detail += " The ball was not playable (off-ball)."
    return ind(label, bool(hit), conf * min(1.0, vh / 150) * (0.9 if not TOUCH / 2 < d < NEAR else 0.6), detail=detail,
               arm=STRIKERS[n], arm_speed_mps=None if speed is None else round(speed, 1))


def _attempt(indicators, contact):
    """Was the offence an attempt to play / challenge for the ball? (penalty-area DOGSO downgrade)"""
    label = "Attempt to play the ball"
    ball = indicators["challenging_for_ball"]
    if contact["striker"] in ("lwri", "rwri", "lelb", "relb"):
        return ind(label, False, 0.5, detail="Contact made with the arm/hand (holding, pulling or pushing is not an attempt to play the ball).")
    if not ball["observable"]:
        return ind(label, None, 0, False, "Ball not located at the contact, so an attempt to play it cannot be judged.")
    return ind(label, ball["value"], ball["confidence"] * 0.8,
               detail="Taken from the ball being within playing distance of the challenger; intent itself cannot be measured.")


def _debug(debug_dir, rec, ci, vi, contact, out, tri):
    img = rec["frame"].copy()
    edges = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]
    for j, col in ((ci, (0, 0, 255)), (vi, (255, 200, 0))):
        k = rec["kps"][j]
        x1, y1, x2, y2 = (int(v) for v in rec["boxes"][j])
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 1)
        for a, b in edges:
            if k[a, 2] >= KP_CONF and k[b, 2] >= KP_CONF:
                cv2.line(img, tuple(int(v) for v in k[a, :2]), tuple(int(v) for v in k[b, :2]), col, 2)
        for p in k:
            if p[2] >= KP_CONF:
                cv2.circle(img, (int(p[0]), int(p[1])), 3, col, -1)
    cv2.circle(img, tuple(int(v) for v in contact["point"]), 7, (0, 255, 0), 2)
    for key in ("toe", "heel"):
        q = out["indicators"]["studs_showing"].get(key)
        if q:
            cv2.circle(img, (int(q[0]), int(q[1])), 4, (255, 0, 255), -1)
    if rec["G"] is not None and tri:
        pts = np.array([project(rec["G"], p) for p in tri], np.int32)
        cv2.polylines(img, [pts], True, (0, 255, 255), 1)
    lines = [f"t={out['t']:.3f} challenger(red)=#{out['players']['challenger']['track_id']} victim(cyan)=#{out['players']['victim']['track_id']}"]
    for key, v in out["indicators"].items():
        lines.append(f"{key}: {v['value']} ({v['confidence']:.2f})")
    for i, line in enumerate(lines):
        cv2.putText(img, line, (10, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
        cv2.putText(img, line, (10, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    x1 = int(min(rec["boxes"][0][0], rec["boxes"][1][0])); y1 = int(min(rec["boxes"][0][1], rec["boxes"][1][1]))
    x2 = int(max(rec["boxes"][0][2], rec["boxes"][1][2])); y2 = int(max(rec["boxes"][0][3], rec["boxes"][1][3]))
    m = int(0.5 * (y2 - y1))
    zoom = img[max(0, y1 - m):y2 + m, max(0, x1 - m):x2 + m]
    s = 400 / max(1, zoom.shape[0])
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    stem = f"{out['t']:.3f}_{out['players']['challenger']['track_id']}-{out['players']['victim']['track_id']}"
    cv2.imwrite(str(Path(debug_dir) / f"{stem}.jpg"), img)
    cv2.imwrite(str(Path(debug_dir) / f"{stem}_zoom.jpg"), cv2.resize(zoom, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST))


# ---------- CLI ----------

def write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


ASSUMPTIONS = [
    "One broadcast camera: limb positions are 2D keypoints; depth between two overlapping players is not measured directly.",
    "Foot orientation (studs/sole) from RTMPose Halpe26 heel and toe keypoints in 2D; a foot pointing along the camera's line of sight is not observable.",
    "Contact geometry error is measured by re-measuring the contact with a second pose model (RTMPose) on the same frame, floored at 1.5 px.",
    "Heights use camera geometry at the player's tracked ground position when calibrated, otherwise an upright 1.80 m body.",
    "Thresholds (touching <= ~11 cm, straight leg >= 155 deg, lunge >= 15 cm clear of the grass) are this system's choices, not IFAB numbers.",
    "Force, intent and the referee's view of the whole incident cannot be measured from pixels.",
]


def _is_closeup(analysis, shot):
    """An uncalibrated shot where the (wide-view) player detector tracked few people: usually a close-up
    or replay, where the challenge is best seen but the analysis has no players to pair."""
    fs = [f for f in analysis["frames"] if f["shot"] == shot["id"]]
    if not fs or any((f.get("calibration") or {}).get("ok") for f in fs):
        return False
    return np.mean([len(f.get("players") or []) for f in fs]) < CLOSEUP_MAX_PLAYERS


def _team_centres(analysis):
    cols = [((analysis.get("teams") or {}).get(k) or {}).get("color") for k in "AB"]
    if not all(isinstance(c, str) and len(c) == 7 for c in cols):
        return None
    bgr = np.array([[[int(c[5:7], 16), int(c[3:5], 16), int(c[1:3], 16)] for c in cols]], np.uint8)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[0].astype(np.float32)


def closeup_analysis(analysis, shots, cap, fps, model, device, sample_hz=10):
    """Players for close-up shots found by the pose model's own person detector: tracked per shot
    (track.assign_ids, fresh per shot), team = nearest window kit colour by track majority (ratio test;
    ambiguous kits stay null). No positions: these shots are uncalibrated."""
    from . import teams, track
    centres = _team_centres(analysis)
    frames = []
    for shot in shots:
        step = max(1, round(fps / sample_hz))
        f0, f1 = int(math.ceil(shot["start"] * fps)), int(math.floor(shot["end"] * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
        recs = []
        for i in range(f0, f1 + 1):
            ok, frame = cap.read()
            if not ok:
                break
            if (i - f0) % step:
                continue
            r = model.predict(frame, device=device, verbose=False, conf=0.4)[0]
            boxes = r.boxes.xyxy.cpu().numpy().astype(float) if len(r.boxes) else np.zeros((0, 4))
            boxes = boxes[(boxes[:, 3] - boxes[:, 1]) >= CLOSEUP_MIN_PX]
            feats = [teams.jersey_feature(frame, b) for b in boxes]
            recs.append((i / fps, boxes, feats))
        ids = track.assign_ids([(b, lambda q: q) for _, b, _ in recs])
        votes = {}
        for (_, _, feats), tids in zip(recs, ids):
            for f, tid in zip(feats, tids):
                if f is None or centres is None:
                    continue
                d = np.linalg.norm(centres - f, axis=1)
                if d.min() < 0.7 * d.max():  # ratio test: clearly one kit
                    votes.setdefault(int(tid), Counter())["AB"[int(d.argmin())]] += 1
        team = {tid: v.most_common(1)[0][0] for tid, v in votes.items()}
        ball = [f for f in analysis["frames"] if f["shot"] == shot["id"] and f.get("ball")]
        for (t, boxes, _), tids in zip(recs, ids):
            b = min(ball, key=lambda f: abs(f["t"] - t)) if ball else None
            frames.append({"t": round(t, 3), "shot": shot["id"], "calibration": {"ok": False},
                           "ball": b["ball"] if b and abs(b["t"] - t) < 0.06 else None,
                           "players": [{"track_id": CLOSEUP_ID_BASE + int(tid), "team": team.get(int(tid)), "role": "player",
                                        "x": None, "y": None, "bbox": [round(float(v), 1) for v in box], "source": "closeup_pose"}
                                       for box, tid in zip(boxes, tids)]})
    return {"shots": analysis["shots"], "frames": frames, "teams": analysis.get("teams")}


def run(args):
    t_start = time.time()
    out = Path(args.out)
    progress_path = out.with_name("fouls.progress.json")
    progress = lambda p, msg: write_json(progress_path, {"stage": "fouls", "progress": round(p, 3), "message": msg})
    progress(0.0, "finding contact candidates")
    analysis = json.loads(Path(args.analysis).read_text())
    cands, total = find_candidates(analysis)
    close = [s for s in analysis.get("shots") or [] if _is_closeup(analysis, s)]
    result = {"version": 1, "clip_id": analysis.get("clip_id"), "window": analysis.get("window"),
              "analysis_version": analysis.get("version"), "candidates_found": total, "incidents": [],
              "closeup_shots": [s["id"] for s in close],
              "assumptions": ASSUMPTIONS, "pipeline": {"pose_model": f"ultralytics {POSE_WEIGHTS}", "foot_model": f"rtmlib RTMPose {FOOT_WEIGHTS}",
                                                        "ball_model": f"roboflow/sports {BALL_WEIGHTS}"}}
    if cands or close:
        progress(0.05, "loading pose model")
        from ultralytics import YOLO
        import torch
        torch.set_num_threads(CPU_THREADS)
        dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        models = Models(dev)
        needs_pitch = any((f.get("calibration") or {}).get("ok") and (f.get("calibration") or {}).get("homography") is None
                          for f in analysis["frames"])
        pitch_path = WEIGHTS / "football-pitch-detection.pt"
        pitch_model = YOLO(str(pitch_path)) if needs_pitch and pitch_path.exists() else None
        cap = open_video(args.video)
        if not cap.isOpened():
            raise RuntimeError("cannot open video")
        fps = cap.get(cv2.CAP_PROP_FPS)
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        work = [(analysis, cands, "analysis")]
        if close:
            progress(0.08, f"detecting players in {len(close)} close-up shot(s)")
            synth = closeup_analysis(analysis, close, cap, fps, models.pose, dev)
            c2, t2 = find_candidates(synth)
            result["candidates_found"] += t2
            work.append((synth, c2, "closeup_pose"))
        todo = [(src, c, tag) for src, cs, tag in work for c in cs]
        for k, (src, c, tag) in enumerate(todo):
            progress(0.1 + 0.85 * k / len(todo), f"pose around candidate {k + 1}/{len(todo)} (t={c['t0']:.1f}s)")
            homs = Homographies(src, pitch_model, dev)
            inc = measure(c, src, _tracks(src), cap, fps, size, models, homs, args.debug_dir)
            inc["source"] = tag
            if tag == "closeup_pose":
                inc["notes"].insert(0, "Close-up shot: players found by the pose model because the wide-view detector tracked none; "
                                       "track ids are separate from the analysis' ids and teams come from kit colour.")
            result["incidents"].append(inc)
        cap.release()
        result["pipeline"].update(device=dev, fps=round(fps, 3), foot_model_loaded=models.foot is not None,
                                  ball_model_loaded=models.ball is not None)
    result["incidents"].sort(key=lambda i: i["t"])
    for n, inc in enumerate(result["incidents"]):
        inc["id"] = n
    result["pipeline"]["elapsed_seconds"] = round(time.time() - t_start, 1)
    write_json(out, result)
    progress(1.0, f"{len(result['incidents'])} contact candidate(s) examined")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True, help="fouls.json path; progress/error files are written next to it")
    ap.add_argument("--debug-dir", help="write contact-frame overlays here")
    args = ap.parse_args(argv)
    err = Path(args.out).with_name("fouls.error.json")
    try:
        err.unlink(missing_ok=True)
        run(args)
    except Exception as e:  # the backend reads this instead of a half-written result
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        write_json(err, {"error": f"{type(e).__name__}: {e}"})
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

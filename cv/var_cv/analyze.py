"""Virtual VAR CV pipeline for one (clip, window). Output: analysis.json version 2.

python -m var_cv.analyze --clip-id ID --source-url URL --video var_data/ID/video.mp4 \
    --start 12.0 --end 17.0 --out var_data/ID/12.0-17.0 [--venue "Estadi Johan Cruyff"]

Writes progress.json while running, then analysis.json (atomic), or error.json + exit 1.
"""

import argparse
import json
import os

# Shared machine: cap CPU threads (set before numpy/cv2/torch load their thread pools). Models run on MPS.
CPU_THREADS = 4
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, str(CPU_THREADS))
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import pitch, shots, teams, temporal, track

cv2.setNumThreads(CPU_THREADS)

ALLOWED_HOST = "espnmedia-cdn.akamaized.net"
MAX_WINDOW_S = 10.0
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
WEIGHTS = Path(__file__).resolve().parent.parent / "weights"
MODELS = {"players": "football-player-detection.pt", "pitch": "football-pitch-detection.pt",
          "ball": "football-ball-detection.pt"}  # roboflow/sports YOLOv8 weights
ROLES = {1: "goalkeeper", 2: "player", 3: "referee"}  # player model classes; 0 = ball
PERSON_CONF, BALL_CONF = 0.4, 0.3
OFF_PITCH_MARGIN_M = 5.0  # detections projecting further outside the pitch are not players on it
# Looked-up venue dimensions (metres). Unknown venues fall back to the FIFA-recommended size, flagged unverified.
VENUES = {
    "estadi johan cruyff": (105.0, 68.0, "Estadi Johan Cruyff, field size 105 m x 68 m "
                                         "(https://en.wikipedia.org/wiki/Johan_Cruyff_Stadium)"),
}
DEFAULT_PITCH = (105.0, 68.0, "unverified for this venue: FIFA-recommended 105 m x 68 m assumed")
ASSUMPTIONS = [
    "Player positions are ground-plane estimates from one broadcast camera: foot point = bottom-centre of the box.",
    "ball.x/y from the CV pipeline is the ground projection of the ball's lowest point (ball3d refines it when present).",
    "Team labels A/B are colour clusters (A = lighter kit), not club identities.",
    "Goalkeepers: detector class or a kit unlike both teams near a goal; their team = nearest team block.",
    "position_uncertainty_m and reprojection_error_m are 1-sigma from the line-fit covariance plus line localisation.",
]


class UserError(Exception):
    pass


def write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def check_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname != ALLOWED_HOST or not u.path.endswith(".mp4"):
        raise UserError(f"refusing source URL: only https MP4s from {ALLOWED_HOST} are allowed")


def download(url, dest):
    check_url(url)
    tmp = f"{dest}.part"
    with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
        total = 0
        while chunk := r.read(1 << 20):
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise UserError("source video larger than 500 MB")
            f.write(chunk)
    os.replace(tmp, dest)


def device():
    import torch
    torch.set_num_threads(CPU_THREADS)
    return "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")


def contained(xyxy, conf, frac=0.7):
    """Boxes mostly inside a more confident box: fragments of occluded players that NMS keeps."""
    drop = np.zeros(len(xyxy), bool)
    for i, a in enumerate(xyxy):
        area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
        for j, b in enumerate(xyxy):
            if j != i and conf[j] > conf[i]:
                w = min(a[2], b[2]) - max(a[0], b[0])
                h = min(a[3], b[3]) - max(a[1], b[1])
                if w > 0 and h > 0 and w * h / area >= frac:
                    drop[i] = True
                    break
    return drop


TIMINGS = Counter()


class timed:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.t = time.perf_counter()

    def __exit__(self, *exc):
        TIMINGS[self.name] += time.perf_counter() - self.t


def detect(frame, models, dev):
    """Model outputs for one frame: detected calibration, line masks, people and the best ball."""
    import supervision as sv

    with timed("pitch_model"):
        r = models["pitch"].predict(frame, device=dev, verbose=False)[0]
    kps = r.keypoints.data[0].cpu().numpy() if r.keypoints is not None and len(r.keypoints.data) else None
    with timed("calibration"):
        masks = pitch.line_mask(frame)
        cal = pitch.calibrate_frame(frame, kps, masks)
    cal["source"] = "detected" if cal["ok"] else None

    with timed("player_model"):
        det = sv.Detections.from_ultralytics(models["players"].predict(frame, device=dev, imgsz=1280, verbose=False)[0])
    balls = det[(det.class_id == 0) & (det.confidence >= BALL_CONF)]
    # duplicate boxes on one person (often one per class) -> cross-class NMS + containment
    people = det[(det.class_id != 0) & (det.confidence >= PERSON_CONF)].with_nms(threshold=0.45, class_agnostic=True)
    people = people[~contained(people.xyxy, people.confidence, frac=0.6)]
    if len(balls) == 0:  # the dedicated ball model only when the player model missed it (saves ~0.7 s/frame)
        with timed("ball_model"):
            balls = sv.Detections.from_ultralytics(models["ball"].predict(frame, device=dev, imgsz=1280, verbose=False)[0])
        balls = balls[balls.confidence >= BALL_CONF]
    ball = None
    if len(balls):
        j = int(np.argmax(balls.confidence))
        ball = {"xyxy": balls.xyxy[j].tolist(), "confidence": float(balls.confidence[j])}
    feats = [teams.jersey_feature(frame, b) if c in (1, 2) else None for b, c in zip(people.xyxy, people.class_id)]
    return {"cal": cal, "masks": masks, "kps": kps, "people": people, "feats": feats, "ball": ball}


def to_pitch(H, uv):
    x, y = pitch.project(H, [uv])[0]
    return (None, None) if np.isnan(x) else (round(float(x), 2), round(float(y), 2))


def on_pitch(x, y):
    m = OFF_PITCH_MARGIN_M
    return -m <= x <= pitch.LENGTH + m and -m <= y <= pitch.WIDTH + m


def track_shot(recs):
    """Track ids for one shot (fresh state => ids never cross a cut), as [(det_index, track_id)] per record."""
    def warp(prev, cur):
        if cur["motion"] is not None:
            return lambda p: pitch.project(cur["motion"], p)
        if prev["cal"]["ok"] and cur["cal"]["ok"]:
            H0, G1 = prev["cal"]["H"], np.linalg.inv(cur["cal"]["H"])
            return lambda p: np.nan_to_num(pitch.project(G1, pitch.project(H0, p)), nan=-1e6)
        return lambda p: p

    warps = [lambda p: p] + [warp(a, b) for a, b in zip(recs, recs[1:])]
    ids = track.assign_ids([(r["people"].xyxy, w) for r, w in zip(recs, warps)])
    frames = []
    for r, frame_ids in zip(recs, ids):
        H = r["cal"]["H"] if r["cal"]["ok"] else None
        dets = []
        for i, tid in enumerate(frame_ids):
            x1, y1, x2, y2 = r["people"].xyxy[i]
            pos = to_pitch(H, ((x1 + x2) / 2, y2)) if H is not None else (None, None)
            f = r["feats"][i]
            dets.append({"id": int(tid), "box": (x1, y1, x2, y2), "pos": None if pos[0] is None else pos,
                         "conf": float(r["people"].confidence[i]),
                         "team": r["team_model"].predict(f) if f is not None and r["team_model"] else None})
        frames.append(dets)
    id_map, drop = track.merge_tracks(frames, [r["t"] for r in recs])
    renum = {}
    out = []
    for k, frame_ids in enumerate(ids):
        pairs, seen = [], set()
        for i, tid in enumerate(frame_ids):
            new = id_map[int(tid)]
            if (k, int(tid)) in drop or new in seen:
                continue
            seen.add(new)
            pairs.append((i, renum.setdefault(new, len(renum) + 1)))
        out.append(pairs)
    return out


def near_goal(x, y):
    return (x < 20 or x > pitch.LENGTH - 20) and abs(y - pitch.WIDTH / 2) < 22


def assign_tracks(recs, tracked, model):
    """Per-track role, team (majority vote over the shot) and team_score (vote share).

    Goalkeepers: detector class, or a kit unlike both teams on a track that stays near a goal.
    A kit unlike both teams elsewhere is a match official. Referees never get a team.
    """
    roles, feats, pos = {}, {}, {}
    for rec, pairs in zip(recs, tracked):
        H = rec["cal"]["H"] if rec["cal"]["ok"] else None
        for i, tid in pairs:
            roles.setdefault(tid, []).append(int(rec["people"].class_id[i]))
            if rec["feats"][i] is not None:
                feats.setdefault(tid, []).append(rec["feats"][i])
            if H is not None:
                x1, _, x2, y2 = rec["people"].xyxy[i]
                p = to_pitch(H, ((x1 + x2) / 2, y2))
                if p[0] is not None:
                    pos.setdefault(tid, []).append(p)
    role = {tid: ROLES[Counter(v).most_common(1)[0][0]] for tid, v in roles.items()}
    team, score = {tid: None for tid in role}, {tid: 0.0 for tid in role}
    if model is None:
        return role, team, score
    for tid, f in feats.items():
        odd = np.mean([model.odd(x) for x in f]) > 0.7 and len(f) >= 4
        if odd and role[tid] == "player":
            p = np.mean(pos[tid], axis=0) if tid in pos else None
            role[tid] = "goalkeeper" if p is not None and near_goal(*p) else "referee"
        if role[tid] == "player":
            votes = Counter(model.predict(x) for x in f)
            team[tid], n = votes.most_common(1)[0]
            score[tid] = n / len(f)
    gk_votes = {}
    for rec, pairs in zip(recs, tracked):  # keepers: nearest team block along the pitch (image x if uncalibrated)
        H = rec["cal"]["H"] if rec["cal"]["ok"] else None
        xs = {}
        for i, tid in pairs:
            x1, _, x2, y2 = rec["people"].xyxy[i]
            u = ((x1 + x2) / 2, y2)
            xs[tid] = to_pitch(H, u)[0] if H is not None else u[0]
        cent = {k: [xs[t] for t in xs if team[t] == k and xs[t] is not None] for k in "AB"}
        if min(len(v) for v in cent.values()) < 3:
            continue
        for tid in xs:
            if role[tid] == "goalkeeper" and xs[tid] is not None:
                gk_votes.setdefault(tid, []).append(min("AB", key=lambda k: abs(xs[tid] - np.mean(cent[k]))))
    for tid, v in gk_votes.items():
        team[tid], n = Counter(v).most_common(1)[0]
        score[tid] = n / len(v)
    return role, team, score


def calibration_json(cal, shape):
    out = {"ok": cal["ok"], "source": cal.get("source") if cal["ok"] else None, "homography": None,
           "reprojection_error_m": None, "line_fit_residual_m": None, "keypoints": cal["keypoints"],
           "line_support": round(cal["support"], 3),
           "keypoint_loo_m": None if cal["loo_m"] is None else round(cal["loo_m"], 3),
           "failure": None if cal["ok"] else cal.get("failure")}
    if cal["ok"]:
        G = np.linalg.inv(cal["H"])
        out["homography"] = [[float(v) for v in row] for row in G / G[2, 2]]
        err = pitch.region_error(cal["sigma"], cal["masks_region"])
        out["reprojection_error_m"] = None if err is None else round(err, 3)
        out["line_fit_residual_m"] = round(cal["error_m"], 3)
    return out


def frame_json(rec, shot_id, pairs, role, team, score):
    cal = rec["cal"]
    H = cal["H"] if cal["ok"] else None
    sig = (lambda pts: cal["sigma"](pts)) if H is not None else None
    out = {"t": round(rec["t"], 3), "shot": shot_id, "calibration": calibration_json(cal, rec["masks"][0].shape),
           "ball": None, "players": []}
    if rec["ball"]:
        x1, y1, x2, y2 = rec["ball"]["xyxy"]
        centre, bottom = ((x1 + x2) / 2, (y1 + y2) / 2), ((x1 + x2) / 2, y2)
        x, y = to_pitch(H, bottom) if H is not None else (None, None)
        out["ball"] = {"x": x, "y": y, "confidence": round(rec["ball"]["confidence"], 3),
                       "image": [round(centre[0], 1), round(centre[1], 1)],
                       "image_bottom": [round(bottom[0], 1), round(bottom[1], 1)],
                       "bbox": [round(v, 1) for v in (x1, y1, x2, y2)],
                       "position_uncertainty_m": round(float(sig(bottom)[0]), 3) if x is not None else None}
    for i, tid in pairs:
        x1, y1, x2, y2 = (float(v) for v in rec["people"].xyxy[i])
        u = ((x1 + x2) / 2, y2)
        x, y = to_pitch(H, u) if H is not None else (None, None)
        if H is not None and (x is None or not on_pitch(x, y)):
            continue
        conf = float(rec["people"].confidence[i])
        out["players"].append({
            "track_id": tid, "role": role[tid], "team": None if role[tid] == "referee" else team[tid],
            "x": x, "y": y, "confidence": round(conf, 3),
            "position_uncertainty_m": round(float(sig(u)[0]), 3) if x is not None else None,
            "bbox": [round(v, 1) for v in (x1, y1, x2, y2)], "foot": [round(u[0], 1), round(u[1], 1)],
            "team_score": score[tid] * conf})
    return out


def run_hooks(result, video):
    """Optional post-processors owned by other modules; missing or failing ones never block the analysis."""
    status = {}
    for name, call in (("ball3d", lambda m: m.apply(result)), ("reid", lambda m: m.apply(result, str(video)))):
        try:
            mod = __import__(f"{__package__}.{name}", fromlist=["apply"])
        except ImportError:
            status[name] = "not installed"
            continue
        try:
            with timed(f"hook_{name}"):
                call(mod)
            status[name] = "applied"
        except Exception as e:  # report, keep the base analysis
            status[name] = f"error: {type(e).__name__}: {e}"
            traceback.print_exc()
    return status


def run(args):
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "error.json").unlink(missing_ok=True)  # stale failure from a previous attempt

    def progress(stage, p, msg=""):
        write_json(out / "progress.json", {"stage": stage, "progress": round(p, 3), "message": msg})

    length, width, pitch_source = args.pitch
    pitch.set_dimensions(length, width)

    video = Path(args.video) if args.video else out.parent / "video.mp4"
    if not video.exists():
        progress("download", 0.0, "downloading source video")
        video.parent.mkdir(parents=True, exist_ok=True)
        download(args.source_url, video)

    progress("load_models", 0.05, "loading models")
    from ultralytics import YOLO
    dev = device()
    models = {k: YOLO(str(WEIGHTS / v)) for k, v in MODELS.items()}

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise UserError("cannot open video")
    fps = cap.get(cv2.CAP_PROP_FPS)
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width_px, height_px = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = nframes / fps
    if args.start >= duration:
        raise UserError(f"window start {args.start}s is beyond the clip ({duration:.1f}s)")
    f0, f1 = round(args.start * fps), min(round(args.end * fps), nframes - 1)
    step = max(1, round(fps / args.sample_fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)

    t_models = time.time() - t0
    sigs, recs, prev = [], [], None
    for i in range(f0, f1 + 1):
        ok, frame = cap.read()
        if not ok:
            break
        sigs.append(shots.signature(frame))
        if (i - f0) % step == 0:
            rec = detect(frame, models, dev)
            with timed("camera_motion"):
                gray = track.motion_gray(frame)
                motion = track.camera_motion(prev["gray"], gray, prev["people"].xyxy) if prev else None
            rec.update(frame=i, t=i / fps, gray=gray, motion=motion)
            if prev:
                prev.pop("gray")
            prev = rec
            recs.append(rec)
            progress("analyse", 0.1 + 0.75 * (i - f0) / max(1, f1 - f0), f"frame {i - f0 + 1}/{f1 - f0 + 1}")
    cap.release()

    progress("tracking", 0.88, "shots, calibration propagation, tracking, teams")
    model = teams.fit([f for r in recs for f, c in zip(r["feats"], r["people"].class_id) if f is not None and c == 2])
    shot_list, frames = [], []
    for sid, (a, b) in enumerate(shots.find_shots(sigs, fps)):
        srecs = [r for r in recs if f0 + a <= r["frame"] <= f0 + b]
        n_detected = sum(r["cal"]["ok"] for r in srecs)
        with timed("propagation"):
            temporal.propagate(srecs)
            if temporal.pool_keypoints(srecs):  # new seeds: spread them too
                temporal.propagate(srecs)
        for r in srecs:
            r["cal"]["masks_region"] = r["masks"][1]
            if not r["cal"]["ok"] and not n_detected and r["cal"].get("failure"):
                r["cal"]["failure"] += "; no calibrated frame in this shot to propagate from"
        n_ok = sum(r["cal"]["ok"] for r in srecs)
        ratio = n_ok / len(srecs) if srecs else 0.0
        shot_list.append({"id": sid, "start": round((f0 + a) / fps, 3), "end": round((f0 + b) / fps, 3),
                          "calibrated_ratio": round(ratio, 3), "detected_ratio": round(n_detected / max(1, len(srecs)), 3),
                          "usable": bool(ratio >= 0.5 and n_ok >= 2)})
        if not srecs:
            continue
        for r in srecs:
            r["team_model"] = model
        tracked = track_shot(srecs)
        role, team, score = assign_tracks(srecs, tracked, model)
        sframes = [frame_json(r, sid, pairs, role, team, score) for r, pairs in zip(srecs, tracked)]
        temporal.smooth_tracks(sframes)
        for f in sframes:
            f["players"] = teams.cap_per_frame(f["players"])
            for p in f["players"]:
                p.pop("team_score", None)
        frames += sframes

    result = {
        "version": 2, "clip_id": args.clip_id,
        "window": {"start": args.start, "end": args.end},
        "pitch": {"length_m": pitch.LENGTH, "width_m": pitch.WIDTH, "source": pitch_source},
        "video": {"fps": round(fps, 3), "duration_seconds": round(duration, 3), "width": width_px,
                  "height": height_px, "sampled_fps": round(fps / step, 3)},
        "pipeline": {"device": dev, "models": {k: f"roboflow/sports {v}" for k, v in MODELS.items()},
                     "calibration_thresholds": {"min_line_support": pitch.MIN_SUPPORT,
                                                "min_single_line_support": pitch.MIN_LINE_SUPPORT,
                                                "max_line_residual_m": pitch.MAX_ERROR_M}},
        "assumptions": ASSUMPTIONS,
        "teams": {k: {"color": (model.colours() if model else {}).get(k)} for k in "AB"},
        "shots": shot_list,
        "frames": frames,
        "events": [],
    }
    progress("postprocess", 0.95, "ball 3D, identities, events")
    result["pipeline"]["hooks"] = run_hooks(result, video)
    with timed("events"):
        result["events"] = temporal.detect_passes(result["frames"])
    result["pipeline"]["elapsed_seconds"] = round(time.time() - t0, 1)
    result["pipeline"]["timings_s"] = {"setup": round(t_models, 1), **{k: round(v, 1) for k, v in TIMINGS.items()},
                                       "cpu_load_avg_1m": round(os.getloadavg()[0], 1)}
    write_json(out / "analysis.json", result)
    progress("done", 1.0, f"{len(frames)} frames, {sum(f['calibration']['ok'] for f in frames)} calibrated, "
                          f"{len(result['events'])} pass events")


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip-id", required=True)
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--video", help="shared per-clip video path (default: <out>/../video.mp4)")
    ap.add_argument("--start", type=float, required=True, help="window start, seconds of source time")
    ap.add_argument("--end", type=float, required=True, help="window end, seconds of source time")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample-fps", type=float, default=10.0)
    ap.add_argument("--venue", help="stadium name, looked up for real pitch dimensions")
    ap.add_argument("--pitch-length", type=float, help="override pitch length (m)")
    ap.add_argument("--pitch-width", type=float, help="override pitch width (m)")
    args = ap.parse_args(argv)
    args.start, args.end = round(args.start, 1), round(args.end, 1)
    args.pitch = VENUES.get((args.venue or "").strip().lower(), DEFAULT_PITCH)
    if args.pitch_length or args.pitch_width:
        args.pitch = (args.pitch_length or args.pitch[0], args.pitch_width or args.pitch[1], "caller-provided")
    return args


def main(argv=None):
    args = parse(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.clip_id):
            raise UserError("invalid clip id")
        if not (0 <= args.start < args.end and args.end - args.start <= MAX_WINDOW_S):
            raise UserError(f"window must satisfy 0 <= start < end and end - start <= {MAX_WINDOW_S:g}s")
        if not (90 <= args.pitch[0] <= 120 and 45 <= args.pitch[1] <= 90):
            raise UserError("pitch dimensions outside IFAB limits (90-120 m x 45-90 m)")
        check_url(args.source_url)
        run(args)
    except Exception as e:  # report every failure to the backend, never a half-written analysis
        Path(args.out).mkdir(parents=True, exist_ok=True)
        msg = str(e) if isinstance(e, UserError) else f"{type(e).__name__}: {e}"
        write_json(Path(args.out) / "error.json", {"error": msg})
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

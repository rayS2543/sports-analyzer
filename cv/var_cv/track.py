"""Camera motion between samples, and per-shot track ids for sampled frames (~10 fps) from a
panning broadcast camera.

IoU trackers (ByteTrack) lose most players here: between samples the camera pans tens of
pixels and small far-side boxes stop overlapping. Instead: warp last positions into the new
frame with the camera-motion homography, then match foot points with the Hungarian algorithm, gated by
distance relative to box height. Never called across a shot boundary.
"""

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

GATE = 0.9  # max foot-point distance / box height (~1.6 m) to continue a track between samples
MAX_MISSED = 8  # samples a track may go unseen (occlusion) before it ends


MOTION_SCALE = 2  # camera motion is estimated on half-resolution frames


def motion_gray(frame):
    h, w = frame.shape[:2]
    return cv2.cvtColor(cv2.resize(frame, (w // MOTION_SCALE, h // MOTION_SCALE), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2GRAY)


def camera_motion(prev_gray, gray, prev_boxes=()):
    """3x3 homography mapping full-res image points of the previous frame into this one, or None.

    A broadcast camera pans/tilts/zooms about a fixed centre, so consecutive frames are related
    by a single homography for the whole scene (pitch and stands alike). Estimated from sparse
    optical flow on corners outside player boxes, forward-backward checked, RANSAC-fitted.
    """
    mask = np.full(prev_gray.shape, 255, np.uint8)
    for x1, y1, x2, y2 in np.asarray(prev_boxes, float).reshape(-1, 4) / MOTION_SCALE:
        mask[max(0, int(y1) - 3):int(y2) + 3, max(0, int(x1) - 3):int(x2) + 3] = 0
    p0 = cv2.goodFeaturesToTrack(prev_gray, 800, 0.005, 7, mask=mask)
    if p0 is None or len(p0) < 30:
        return None
    lk = dict(winSize=(21, 21), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    p1, st1, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None, **lk)
    pb, st2, _ = cv2.calcOpticalFlowPyrLK(gray, prev_gray, p1, None, **lk)
    good = (st1.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((pb - p0).reshape(-1, 2), axis=1) < 1.0)
    if good.sum() < 30:
        return None
    M, inl = cv2.findHomography(p0[good], p1[good], cv2.RANSAC, 1.0)
    if M is None or inl.sum() < 25:
        return None
    S = np.diag([MOTION_SCALE, MOTION_SCALE, 1.0])
    return S @ M @ np.linalg.inv(S)


VEL_BLEND = 0.5  # weight of the newest displacement in a track's velocity estimate
COAST_DECAY = 0.8  # velocity kept per sample while a track is unseen or hidden in a merged box
TEAM_MIN_VOTES = 1  # confident kit readings before a track's team gates its continuation
TEAM_SHARE = 0.7
MAX_SCALE = 1.8  # box height ratio a track may change by between samples (a ball box is not a player)


def _track_team(votes):
    n = sum(votes.values())
    if n < TEAM_MIN_VOTES:
        return None
    team, k = max(votes.items(), key=lambda kv: kv[1])
    return team if k / n >= TEAM_SHARE else None


def assign_ids(frames, tangles=True):
    """frames: list of (boxes Nx4 xyxy, warp[, teams]) where warp maps Mx2 image points of the previous
    frame into this frame (camera motion) and teams optionally holds a confident kit label ("A"/"B") or
    None per box.
    Returns a list of int arrays: track id (1..n) per box, stable within the sequence.

    Identity through tangles, where players overlap and the detector merges or drops boxes:
    - a track is predicted at its camera-compensated foot plus its recent velocity (a runner who
      crosses a teammate keeps going, instead of being matched to whoever stands where he last was);
    - a box that two tracks could both explain (merged players) feeds neither track's position or
      velocity: both coast through it, so the pair is separated by their motion when the boxes split;
    - a track whose kit is known never continues onto a box of the other kit, nor onto one of a very
      different size.
    tangles=False is the plain association (last camera-compensated position only): in close-ups the
    boxes are huge and move fast, and velocity extrapolation of a missed track lands on its neighbour.
    """
    tracks = {}  # id -> {"foot": (2,), "vel": (2,), "h", "missed", "votes": {team: n}}
    next_id, out = 1, []
    for frame in frames:
        boxes, warp = frame[0], frame[1]
        boxes = np.asarray(boxes, float).reshape(-1, 4)
        teams = list(frame[2]) if len(frame) > 2 and frame[2] is not None else [None] * len(boxes)
        feet = np.c_[(boxes[:, 0] + boxes[:, 2]) / 2, boxes[:, 3]]
        heights = np.maximum(boxes[:, 3] - boxes[:, 1], 1.0)
        ids = np.zeros(len(boxes), int)
        tids = list(tracks)
        moved = pred = None
        if tids:
            moved = warp(np.array([tracks[t]["foot"] for t in tids]))
            pred = moved + np.array([tracks[t]["vel"] for t in tids])  # vel stays 0 unless tangles
        if tids and len(boxes):
            th = np.array([tracks[t]["h"] for t in tids])
            cost = np.linalg.norm(pred[:, None] - feet[None], axis=2) / np.maximum(th[:, None], heights[None])
            for r, t in enumerate(tids if tangles else ()):
                kit = _track_team(tracks[t]["votes"])
                for c, team in enumerate(teams):
                    if (kit and team and kit != team) or max(th[r], heights[c]) > MAX_SCALE * min(th[r], heights[c]):
                        cost[r, c] = np.inf
            rows, cols = linear_sum_assignment(np.where(cost > GATE, 1e6, cost))
            for r, c in zip(rows, cols):
                if cost[r, c] <= GATE:
                    ids[c] = tids[r]
            # a box holding an established, just-seen track that found no box of its own is a merge of
            # players: it and the track that took the box both coast through it
            matched = set(ids[ids > 0])
            hidden = set()
            for c in range(len(boxes) if tangles else 0):
                if not ids[c]:
                    continue
                x1, y1, x2, y2 = boxes[c]
                w, h = x2 - x1, y2 - y1
                for r, t in enumerate(tids):
                    st = tracks[t]
                    px, py = pred[r]
                    if t not in matched and st["n"] >= 2 and st["missed"] == 0 and cost[r, c] <= GATE \
                            and x1 - 0.2 * w <= px <= x2 + 0.2 * w and y1 + 0.3 * h <= py <= y2 + 0.25 * h:
                        hidden |= {t, int(ids[c])}
        else:
            hidden = set()
        seen = set(ids[ids > 0])
        for k, t in enumerate(tids):
            st = tracks[t]
            if t in hidden or t not in seen:  # coast
                st["foot"], st["vel"] = pred[k], st["vel"] * COAST_DECAY
                if t not in seen:
                    st["missed"] += 1
                    if st["missed"] > MAX_MISSED:
                        del tracks[t]
        for c in range(len(boxes)):
            t = int(ids[c])
            if t and t in hidden:
                continue
            if t:
                st = tracks[t]
                k = tids.index(t)
                blend = 1.0 if st["n"] == 1 else VEL_BLEND  # the first displacement is all we know
                if tangles:
                    st["vel"] = (1 - blend) * st["vel"] + blend * (feet[c] - moved[k])
                st["foot"], st["h"], st["missed"] = feet[c], heights[c], 0
                st["n"] += 1
            else:
                ids[c], next_id = next_id, next_id + 1
                t = int(ids[c])
                tracks[t] = {"foot": feet[c], "vel": np.zeros(2), "h": heights[c], "missed": 0, "n": 1, "votes": {}}
            if teams[c]:
                tracks[t]["votes"][teams[c]] = tracks[t]["votes"].get(teams[c], 0) + 1
        out.append(ids)
    return out


def _iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def merge_tracks(frames, times, dup_frac=0.6, max_gap=4, max_speed=8.0, max_jump_m=3.0):
    """Remove duplicate and fragmented tracks within one shot.

    frames: per sampled frame a list of dicts {"id", "box" (xyxy), "pos" (pitch xy or None),
    "conf", "team"}; times: sample times (s). Returns (id_map, drop) where id_map maps old id ->
    surviving id and drop is a set of (frame index, old id) detections to discard.

    1. Duplicates: two tracks that co-occur and, in >= dup_frac of those frames, overlap
       (IoU >= 0.3) or stand < 0.6 m apart, with compatible teams, are one person: the shorter
       track is folded into the longer; in shared frames the less confident box is dropped.
    2. Fragments: a track that starts within max_gap samples after another ended, never
       co-occurring with it, close enough on the pitch to be the same runner (< max_speed m/s,
       < max_jump_m), same team, continues that track.
    """
    occ = {}
    for k, dets in enumerate(frames):
        for d in dets:
            occ.setdefault(d["id"], {})[k] = d
    parent = {t: t for t in occ}

    def root(t):
        while parent[t] != t:
            t = parent[t]
        return t

    def compatible(a, b):
        ta = [d["team"] for d in occ[a].values() if d["team"]]
        tb = [d["team"] for d in occ[b].values() if d["team"]]
        if not ta or not tb:
            return True
        return max(set(ta), key=ta.count) == max(set(tb), key=tb.count)

    drop = set()
    ids = sorted(occ, key=lambda t: -len(occ[t]))
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = set(occ[a]) & set(occ[b])
            if not shared or root(a) == root(b) or not compatible(a, b):
                continue
            close = 0
            for k in shared:
                da, db = occ[a][k], occ[b][k]
                near = da["pos"] is not None and db["pos"] is not None and \
                    np.hypot(da["pos"][0] - db["pos"][0], da["pos"][1] - db["pos"][1]) < 0.6
                close += _iou(da["box"], db["box"]) >= 0.3 or near
            if close / len(shared) >= dup_frac:
                parent[root(b)] = root(a)
                for k in shared:
                    lo = b if occ[b][k]["conf"] <= occ[a][k]["conf"] else a
                    drop.add((k, lo))
    # fragments: link a track's start to the end of an earlier group it never overlaps
    def frames_of(g):
        return {k for t in occ if root(t) == g for k in occ[t] if (k, t) not in drop}

    for b in sorted(occ, key=lambda t: min(occ[t])):
        gb = root(b)
        fb = frames_of(gb)
        sb = min(fb)
        best = None
        for ga in {root(t) for t in occ} - {gb}:
            fa = frames_of(ga)
            ea = max(fa)
            if ea >= sb or sb - ea > max_gap or fa & fb or not compatible(ga, b):
                continue
            pa = next(occ[t][ea]["pos"] for t in occ if root(t) == ga and ea in occ[t] and (ea, t) not in drop)
            pb = occ[b][sb]["pos"] if sb in occ[b] else None
            if pa is None or pb is None:
                continue
            dist = np.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if dist < max_jump_m and dist / max(times[sb] - times[ea], 1e-3) < max_speed \
                    and (best is None or dist < best[0]):
                best = (dist, ga)
        if best:
            parent[gb] = best[1]
    return {t: root(t) for t in occ}, drop

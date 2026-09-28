"""Player identity within a window: repair intra-shot swaps, then give every person a global_id.

apply(analysis, video_path) adds players[].global_id (stable across shots when the same person is matched,
otherwise fresh) and analysis["identity"] (what was fixed/linked and how). track_id keeps its meaning
(per shot) but is corrected where a swap was repaired.

Appearance. Each detection gets colour histograms of four body bands of its box (head/hair+skin, shirt,
shorts, socks): HSV, 6 hue x 2 sat x 2 value bins, grass pixels removed. Distance between two
appearances = weighted Hellinger distance, d = sum_r w_r sqrt(1 - sum_b sqrt(p_rb q_rb)).
It is normalised by sigma_app = median distance of a detection to its own track's mean (measured on the
window itself). No neural ReID: at broadcast wide-shot scale a player is ~25x60 px and teammates wear
identical kits, so pedestrian-ReID/CLIP features do not separate teammates either; colour bands do
separate teams, keepers, referees and some teammates (hair, skin, socks, sleeves) with no weights or fees.

Swaps. Two tracks of one shot whose boxes overlap (occlusion) and both continue afterwards are tested:
    keep = d(a_before, a_after) + d(b_before, b_after),   swap = d(a_before, b_after) + d(b_before, a_after)
(means of up to 6 clean detections on each side). If keep - swap > max(SWAP_SIGMAS * sigma_app, 0.25 keep)
the labels are exchanged from the frame (within the occlusion, or up to 3 samples before it) where the
relabelled foot tracks are smoothest -- appearance says THAT they swapped, motion says WHEN; smoothing/velocity of the two tracks is
recomputed (temporal.smooth_tracks) because it had been averaged across two people.

Global ids (shots in time order).
1. Fragments of one person inside a shot (a track that ends, and one that starts <= 2 s later) are chained
   by Hungarian assignment on  cost = (d_pos / s_pos)^2 + (d_app / s_app)^2,  d_pos = |p_start - (p_end + v gap)|,
   s_pos = 1 m + 2 m/s * gap; same team and role class required; gate chi^2 <= 9 per term.
2. Live cut: an earlier shot's last calibrated frame is <= LIVE_GAP_S before this shot's first one
   (both at the shot edges; an uncalibrated insert such as a close-up may sit between) ->
   the same Hungarian cost against the previous shot's people (pitch position + velocity continuity +
   appearance), s_pos = 1 m + 2 m/s * gap. Velocity = straight-line fit over the last 0.6 s (capped at
   9 m/s). A pair is kept only if it beats every alternative in its row and column by chi^2 >= 4;
   crowded, ambiguous players get fresh ids instead of a coin-flip.
3. Everything still unmatched (and replays / uncalibrated shots): appearance + team + role only, against
   anybody seen earlier in the window and absent from this shot, accepted only if clearly better than the
   runner-up (chi^2 margin >= 4, i.e. 2 sigma) -- same-kit teammates usually stay ambiguous and get a
   fresh id, deliberately.
jersey_number is not produced: numbers are a few pixels tall in wide shots and no OCR model is installed.
"""

import warnings

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

BANDS = ((0.0, 0.16, 0.3, 0.7, 0.15),   # (y0, y1, x0, x1, weight) as fractions of the box: head
         (0.16, 0.5, 0.2, 0.8, 0.45),   # shirt
         (0.5, 0.7, 0.2, 0.8, 0.25),    # shorts
         (0.75, 0.95, 0.15, 0.85, 0.15))  # socks
BINS = (6, 2, 2)  # coarse: a crop has a few hundred pixels; measured best on the test clip
MIN_PIXELS = 8
SWAP_SIGMAS = 2.0
CHAIN_GAP_S = 2.0
LIVE_GAP_S = 2.0   # s between the last calibrated frame before a cut and the first after it
GATE = 9.0          # chi^2 per term
MARGIN = 4.0        # appearance-only match must beat the runner-up by this much chi^2 (2 sigma)
VEL_SPAN_S = 0.6    # velocity at a track end: straight-line fit over this much of it
MAX_RUN_MS = 9.0    # m/s, sprint speed cap for extrapolation
OVERLAP = 0.3
SWAP_LEAD = 3       # samples before an occlusion where the tracker may already have swapped       # intersection / smaller box area that counts as an occlusion


def embed(frame, bbox):
    """(4, 24) band histograms (rows of NaN where a band has too few non-grass pixels), or None."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w < 4 or h < 8:
        return None
    out = np.full((len(BANDS), int(np.prod(BINS))), np.nan)
    for i, (a, b, c, d, _) in enumerate(BANDS):
        crop = frame[max(int(y1 + a * h), 0):max(int(y1 + b * h), 0), max(int(x1 + c * w), 0):max(int(x1 + d * w), 0)]
        if crop.size == 0:
            continue
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(int)
        hsv = hsv[~((hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] > 50))]  # drop grass
        if len(hsv) < MIN_PIXELS:
            continue
        idx = (hsv[:, 0] * BINS[0] // 180) * BINS[1] * BINS[2] + (hsv[:, 1] * BINS[1] // 256) * BINS[2] \
            + hsv[:, 2] * BINS[2] // 256
        out[i] = np.bincount(idx, minlength=out.shape[1]) / len(hsv)
    return None if np.isnan(out[1]).all() else out


def mean_app(embs):
    embs = [e for e in embs if e is not None]
    if not embs:
        return None
    return _nanmean(embs)


def _nanmean(arrs):
    with warnings.catch_warnings():  # all-NaN bands (e.g. socks never visible) stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.array(arrs), axis=0)


def dist(a, b):
    """Weighted Hellinger distance over the bands both appearances have; NaN if none."""
    if a is None or b is None:
        return np.nan
    w = np.array([band[4] for band in BANDS])
    ok = ~(np.isnan(a).any(1) | np.isnan(b).any(1))
    if not ok[1]:  # the shirt band is required
        return np.nan
    d = np.sqrt(np.maximum(0.0, 1 - np.sqrt(a[ok] * b[ok]).sum(1)))
    return float((w[ok] * d).sum() / w[ok].sum())


def _read_frames(video_path, frames, fps):
    """Decoded images for the analysis frames (sequential read: the window is short)."""
    want = {int(round(f["t"] * fps)): k for k, f in enumerate(frames)}
    if not want:
        return {}
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {video_path}")
    first, last = min(want), max(want)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    out = {}
    for i in range(first, last + 1):
        if not cap.grab():
            break
        if i in want:
            ok, img = cap.retrieve()
            if ok:
                out[want[i]] = img
    cap.release()
    return out


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / max(small, 1e-6)


def _occluded(players):
    """Indices of players whose box overlaps another one (their crops mix two people)."""
    bad = set()
    for i, p in enumerate(players):
        for j in range(i + 1, len(players)):
            if _overlap(p["bbox"], players[j]["bbox"]) > OVERLAP:
                bad |= {i, j}
    return bad


# ------------------------------------------------------------------ swaps

def _tracks(frames):
    """tid -> [(frame index, player index)] for one shot."""
    tr = {}
    for k, f in enumerate(frames):
        for i, p in enumerate(f["players"]):
            tr.setdefault(p["track_id"], []).append((k, i))
    return tr


def _events(frames):
    """Occlusion events between two tracks: (a, b, first frame, last frame, frame of max overlap)."""
    runs = {}
    for k, f in enumerate(frames):
        ps = f["players"]
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                ov = _overlap(ps[i]["bbox"], ps[j]["bbox"])
                if ov > OVERLAP:
                    key = tuple(sorted((ps[i]["track_id"], ps[j]["track_id"])))
                    runs.setdefault(key, []).append((k, ov))
    events = []
    for (a, b), items in runs.items():
        start = 0
        for n in range(1, len(items) + 1):
            if n == len(items) or items[n][0] - items[n - 1][0] > 2:
                seg = items[start:n]
                events.append((a, b, seg[0][0], seg[-1][0], max(seg, key=lambda x: x[1])[0]))
                start = n
    return sorted(events, key=lambda e: e[2])


def _side(frames, emb, clean, tid, ks):
    return mean_app([emb[(k, i)] for k in ks for i, p in enumerate(frames[k]["players"])
                     if p["track_id"] == tid and (k, i) in clean])


def fix_swaps(frames, emb, clean, sigma):
    """Repair identity swaps in one shot (frames in time order). Returns [(t, a, b)] of applied swaps."""
    fixed, seen, events = [], set(), _events(frames)
    while True:  # events are re-derived after every repair: later labels may have changed
        todo = [e for e in events if e[:3] not in seen]
        if not todo:
            return fixed
        a, b, k0, k1, _ = todo[0]
        seen.add((a, b, k0))
        present = lambda tid, ks: [k for k in ks if any(p["track_id"] == tid for p in frames[k]["players"])]
        k0 = max(0, k0 - SWAP_LEAD)  # trackers often swap just before the boxes overlap
        before = range(max(0, k0 - 12), k0)
        after = range(k1 + 1, min(len(frames), k1 + 13))
        pa, pb = present(a, before)[-6:], present(b, before)[-6:]
        qa, qb = present(a, after)[:6], present(b, after)[:6]
        if min(len(pa), len(pb), len(qa), len(qb)) < 2:
            continue  # one of them is not seen on both sides: nothing to compare
        A0, B0 = _side(frames, emb, clean, a, pa), _side(frames, emb, clean, b, pb)
        A1, B1 = _side(frames, emb, clean, a, qa), _side(frames, emb, clean, b, qb)
        keep = dist(A0, A1) + dist(B0, B1)
        swap = dist(A0, B1) + dist(B0, A1)
        if np.isfinite(keep) and np.isfinite(swap) and keep - swap > max(SWAP_SIGMAS * sigma, 0.25 * keep):
            k_sw = _swap_frame(frames, a, b, k0, k1)
            for f in frames[k_sw:]:
                for p in f["players"]:
                    if p["track_id"] in (a, b):
                        p["track_id"] = b if p["track_id"] == a else a
            fixed.append((frames[k_sw]["t"], a, b))
            events = _events(frames)


def _swap_frame(frames, a, b, k0, k1):
    """First frame carrying swapped labels. Appearance decided THAT the two swapped; motion decides WHEN:
    the split s in [k0, k1 + 1] whose relabelled foot tracks are smoothest (sum of squared image
    accelerations / box height, over the occlusion +- 2 samples). Crops inside the occlusion mix two
    people, so they are not trusted for this."""
    lo, hi = max(0, k0 - 2), min(len(frames), k1 + 3)

    def foot(k, tid):
        p = next((p for p in frames[k]["players"] if p["track_id"] == tid), None)
        return None if p is None else (np.array(p["foot"], float), p["bbox"][3] - p["bbox"][1])

    raw = {tid: [foot(k, tid) for k in range(lo, hi)] for tid in (a, b)}

    def rough(s):
        total = 0.0
        for tid, other in ((a, b), (b, a)):
            seq = [raw[tid][k - lo] if k < s else raw[other][k - lo] for k in range(lo, hi)]
            for x, y, z in zip(seq, seq[1:], seq[2:]):
                if x is not None and y is not None and z is not None:
                    total += (np.linalg.norm(x[0] - 2 * y[0] + z[0]) / max(y[1], 1.0)) ** 2
            for x, y in zip(seq, seq[1:]):  # also plain jumps: sparse tracks may lack 3 in a row
                if x is not None and y is not None:
                    total += 0.25 * (np.linalg.norm(x[0] - y[0]) / max(y[1], 1.0)) ** 2
        return total

    return min(range(k0, k1 + 2), key=rough)


def _resmooth(frames, tids):
    """Majority team/role and smoothing of repaired tracks (they had been computed over two people)."""
    for tid in tids:
        ps = [p for f in frames for p in f["players"] if p["track_id"] == tid]
        for key in ("team", "role"):
            vals = [p.get(key) for p in ps if p.get(key) is not None]
            if vals:
                best = max(set(vals), key=vals.count)
                for p in ps:
                    p[key] = best
        for p in ps:
            if p.get("role") == "referee":
                p["team"] = None
    try:
        from . import temporal
    except ImportError:
        temporal = None
    if temporal is not None and hasattr(temporal, "smooth_tracks"):
        for f in frames:
            for p in f["players"]:
                if "raw_x" in p:
                    p["x"], p["y"] = p["raw_x"], p["raw_y"]
        temporal.smooth_tracks(frames)


# ------------------------------------------------------------------ global ids

def _tracklets(frames, emb, clean, shot):
    out = []
    for tid, items in _tracks(frames).items():
        ps = [(frames[k]["t"], frames[k]["players"][i]) for k, i in items]
        roles = [p.get("role") for _, p in ps]
        teams = [p.get("team") for _, p in ps if p.get("team") is not None]
        cal = [(t, p) for t, p in ps if p.get("x") is not None]
        out.append({"shot": shot, "tid": tid, "t0": ps[0][0], "t1": ps[-1][0], "players": [p for _, p in ps],
                    "role": max(set(roles), key=roles.count),
                    "team": max(set(teams), key=teams.count) if teams else None,
                    "app": mean_app([emb.get((k, i)) for k, i in items if (k, i) in clean]
                                    or [emb.get((k, i)) for k, i in items]),
                    "start": _state(cal, first=True) if cal and cal[0][0] == ps[0][0] else None,
                    "end": _state(cal, first=False) if cal and cal[-1][0] == ps[-1][0] else None})
    return out


def _state(cal, first):
    """(t, x, y, vx, vy) at one end of a tracklet: straight-line fit to its calibrated positions within
    VEL_SPAN_S of that end (the frame-level vx/vy is used when the pipeline provides it); speed capped
    at MAX_RUN_MS. One sample -> zero velocity."""
    t_end = cal[0][0] if first else cal[-1][0]
    near = [(t, p) for t, p in cal if abs(t - t_end) <= VEL_SPAN_S]
    p = cal[0][1] if first else cal[-1][1]
    tt = np.array([t for t, _ in near])
    xy = np.array([[q["x"], q["y"]] for _, q in near])
    x, y = (np.polyval(np.polyfit(tt - t_end, xy[:, k], 1), 0) for k in (0, 1)) if len(near) >= 3 \
        else (p["x"], p["y"])
    if p.get("vx") is not None:
        v = np.array([p["vx"], p["vy"]])
    elif len(near) >= 3 and np.ptp(tt) >= 0.2:
        v = np.array([np.polyfit(tt, xy[:, k], 1)[0] for k in (0, 1)])
    else:
        v = np.zeros(2)
    v *= min(1.0, MAX_RUN_MS / max(np.hypot(*v), 1e-9))
    return (t_end, float(x), float(y), float(v[0]), float(v[1]))


def _compatible(a, b):
    if (a["role"] == "referee") != (b["role"] == "referee"):
        return False
    return a["team"] is None or b["team"] is None or a["team"] == b["team"]


def _cost(end, start, app_a, app_b, sigma):
    """chi^2 of position/velocity continuity + appearance, or inf when gated out."""
    gap = start[0] - end[0]
    if gap <= 0:
        return np.inf
    s_pos = 1.0 + 2.0 * gap  # 1 m calibration/foot error + ~2 m/s unmodelled velocity change
    pred = np.array(end[1:3]) + gap * np.array(end[3:5])
    c_pos = (np.hypot(*(np.array(start[1:3]) - pred)) / s_pos) ** 2
    d = dist(app_a, app_b)
    c_app = (d / sigma) ** 2 if np.isfinite(d) else 1.0
    return c_pos + c_app if c_pos <= GATE and c_app <= GATE else np.inf


UNMATCHED = 2 * GATE  # cost of leaving a row without a partner (a fresh id)


def _hungarian(C, total=False):
    """Min-cost assignment where any row may stay unmatched at cost UNMATCHED (dummy columns)."""
    n, m = C.shape
    if n == 0 or m == 0 or not np.isfinite(C).any():
        return n * UNMATCHED if total else []
    big = np.full((n, n), 1e9)
    np.fill_diagonal(big, UNMATCHED)
    A = np.c_[np.where(np.isfinite(C), C, 1e9), big]
    rows, cols = linear_sum_assignment(A)
    pairs = [(r, c) for r, c in zip(rows, cols) if c < m and np.isfinite(C[r, c])]
    return float(A[rows, cols].sum()) if total else pairs


def _chain(tls, sigma):
    """Merge fragments of one person within a shot. Returns list of chains (lists of tracklets)."""
    ends = [a for a in tls if a["end"]]
    starts = [b for b in tls if b["start"]]
    C = np.full((len(ends), len(starts)), np.inf)
    for i, a in enumerate(ends):
        for j, b in enumerate(starts):
            if b is not a and 0 < b["t0"] - a["t1"] <= CHAIN_GAP_S and _compatible(a, b):
                C[i, j] = _cost(a["end"], b["start"], a["app"], b["app"], sigma)
    nxt = {id(ends[i]): starts[j] for i, j in _hungarian(C)}
    has_prev = {id(b) for b in nxt.values()}
    chains = []
    for a in sorted(tls, key=lambda x: x["t0"]):
        if id(a) in has_prev:
            continue
        ch = [a]
        while id(ch[-1]) in nxt:
            ch.append(nxt[id(ch[-1])])
        chains.append(ch)
    return chains


def _unit(chain):
    ps = [p for tl in chain for p in tl["players"]]
    apps = [tl["app"] for tl in chain if tl["app"] is not None]
    app = _nanmean(apps) if apps else None
    return {"chain": chain, "players": ps, "role": chain[0]["role"], "team": chain[0]["team"], "app": app,
            "t0": chain[0]["t0"], "t1": chain[-1]["t1"], "start": chain[0]["start"], "end": chain[-1]["end"]}


def _appearance_match(units, pool, sigma):
    """One-to-one appearance+team+role match with a ratio test. Returns [(unit index, identity)]."""
    if not units or not pool:
        return []
    C = np.full((len(units), len(pool)), np.inf)
    for i, u in enumerate(units):
        for j, g in enumerate(pool):
            d = dist(u["app"], g["app"])
            if _compatible(u, g) and u["role"] == g["role"] and np.isfinite(d) and (d / sigma) ** 2 <= GATE:
                C[i, j] = (d / sigma) ** 2
    return [(i, pool[j]) for i, j in _unambiguous(C, _hungarian(C))]


def _unambiguous(C, pairs):
    """Keep assigned pairs the data really prefers: forbidding the pair must raise the optimal total
    assignment cost (re-solved, others free to rearrange) by at least MARGIN."""
    base = _hungarian(C, total=True)
    out = []
    for i, j in pairs:
        C2 = C.copy()
        C2[i, j] = np.inf
        if _hungarian(C2, total=True) - base >= MARGIN:
            out.append((i, j))
    return out


def apply(analysis, video_path):
    frames_all = analysis["frames"]
    fps = analysis["video"]["fps"]
    images = _read_frames(video_path, frames_all, fps)
    emb, clean = {}, set()
    by_shot = {}
    for k, f in enumerate(frames_all):
        by_shot.setdefault(f.get("shot"), []).append(k)
    # appearance per detection, keyed by (global frame index, player index)
    for k, f in enumerate(frames_all):
        img = images.get(k)
        occ = _occluded(f["players"])
        for i, p in enumerate(f["players"]):
            emb[(k, i)] = embed(img, p["bbox"]) if img is not None else None
            if i not in occ and emb[(k, i)] is not None:
                clean.add((k, i))
    sigma = _sigma(frames_all, emb, clean)

    report = {"swaps_fixed": [], "cuts": [], "sigma_app": round(sigma, 4)}
    shots = sorted(by_shot, key=lambda s: frames_all[by_shot[s][0]]["t"])
    identities, next_gid, prev = [], 1, None
    for s in shots:
        ks = by_shot[s]
        frames = [frames_all[k] for k in ks]
        loc = {(j, i): emb[(k, i)] for j, k in enumerate(ks) for i in range(len(frames_all[k]["players"]))}
        loc_clean = {(j, i) for j, k in enumerate(ks) for i in range(len(frames_all[k]["players"])) if (k, i) in clean}
        fixed = fix_swaps(frames, loc, loc_clean, sigma)
        if fixed:
            _resmooth(frames, {x for _, a, b in fixed for x in (a, b)})
            report["swaps_fixed"] += [{"shot": s, "t": t, "track_ids": [a, b]} for t, a, b in fixed]
        units = [_unit(ch) for ch in _chain(_tracklets(frames, loc, loc_clean, s), sigma)]
        assigned = {}
        cut = {"shot": s, "kind": "first" if prev is None else "appearance"}
        src = _live_source(frames, [[frames_all[k] for k in by_shot[p]] for p in shots[:shots.index(s)]],
                           shots[:shots.index(s)])
        if src is not None:
            cand = [g for g in identities if g.get("end_shot") == src]
            us = [i for i, u in enumerate(units) if u["start"] is not None and u["t0"] - frames[0]["t"] < 0.5]
            C = np.full((len(us), len(cand)), np.inf)
            for a, i in enumerate(us):
                for b, g in enumerate(cand):
                    if _compatible(units[i], g):
                        C[a, b] = _cost(g["end"], units[i]["start"], g["app"], units[i]["app"], sigma)
            pairs = _unambiguous(C, _hungarian(C))
            if pairs:
                for a, b in pairs:
                    assigned[us[a]] = cand[b]
                cut.update(kind="live", from_shot=src)
        rest = [i for i in range(len(units)) if i not in assigned]
        taken = {id(g) for g in assigned.values()}
        pool = [g for g in identities if id(g) not in taken]
        live_n = len(assigned)
        for i, g in _appearance_match([units[i] for i in rest], pool, sigma):
            assigned[rest[i]] = g
        cut.update(matched_position=live_n, matched_appearance=len(assigned) - live_n)
        report["cuts"].append(cut)
        for i, u in enumerate(units):
            g = assigned.get(i)
            if g is None:
                g = {"gid": next_gid}
                next_gid += 1
                identities.append(g)
            g.update(shot=s, role=u["role"], team=u["team"] if u["team"] is not None else g.get("team"),
                     app=u["app"] if u["app"] is not None else g.get("app"))
            if u["end"] is not None:
                g.update(end=u["end"], end_shot=s)
            for p in u["players"]:
                p["global_id"] = g["gid"]
        prev = s
    analysis["identity"] = report


def _calibrated(frame):
    return bool((frame.get("calibration") or {}).get("ok"))


def _live_source(frames, earlier, ids, edge_s=0.5):
    """The latest earlier shot this one continues live: its last calibrated frame is within edge_s of its
    end, ours starts calibrated within edge_s, and the time between them is <= LIVE_GAP_S (a short
    uncalibrated insert such as a close-up may sit in between). None if there is no such shot."""
    first = next((f["t"] for f in frames if _calibrated(f)), None)
    if first is None or first - frames[0]["t"] > edge_s:
        return None
    for sid, fr in zip(ids[::-1], earlier[::-1]):
        last = next((f["t"] for f in reversed(fr) if _calibrated(f)), None)
        if first - fr[-1]["t"] > LIVE_GAP_S:
            return None
        if last is not None and fr[-1]["t"] - last <= edge_s and first - last <= LIVE_GAP_S:
            return sid
    return None


def _sigma(frames, emb, clean):
    """Typical distance of a clean detection to its own track's mean (appearance noise)."""
    groups = {}
    for (k, i) in clean:
        f = frames[k]
        groups.setdefault((f.get("shot"), f["players"][i]["track_id"]), []).append(emb[(k, i)])
    d = []
    for es in groups.values():
        if len(es) >= 3:
            m = mean_app(es)
            d += [dist(e, m) for e in es]
    d = [x for x in d if np.isfinite(x)]
    return max(float(np.median(d)) if d else 0.05, 0.02)

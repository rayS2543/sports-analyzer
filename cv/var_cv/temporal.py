"""Per-shot temporal logic: calibration propagation, track smoothing, pass events.

Everything here works inside ONE shot: nothing is carried or interpolated across a cut.
"""

import numpy as np

from . import pitch

MAX_PROPAGATION_GAP = 6  # samples an unverified chained homography may be carried before it is dropped


def _verify(H, masks, shape):
    """Refine a chained homography on this frame's painted lines, anchored softly to the chain."""
    h, w = shape[:2]
    grid = np.array([[u, v] for u in np.linspace(0.1, 0.9, 5) * w for v in np.linspace(0.4, 0.9, 3) * h])
    prior = pitch.project(H, grid)
    ok = ~np.isnan(prior).any(1)
    return pitch.refine(H, masks, grid[ok], prior[ok], kp_weight=0.1)


def propagate(recs):
    """Fill uncalibrated frames of one shot from calibrated neighbours.

    recs: the shot's sampled records in time order, each with "cal" (dict, see
    pitch.calibrate_frame), "masks" and "motion" (3x3 image homography from the previous
    record into this one, or None). A chained homography must pass the same line checks
    as a detected one before a frame counts as calibrated (source "propagated"); chains
    may bridge up to MAX_PROPAGATION_GAP unverifiable frames. Mutates rec["cal"].
    """
    n = len(recs)
    for step in (1, -1):
        carry, gap = None, 0
        for i in (range(n) if step == 1 else range(n - 1, -1, -1)):
            cal = recs[i]["cal"]
            if cal["ok"]:
                carry, gap = cal["H"], 0
                continue
            j = i - step  # neighbour we chain from
            if carry is None or not 0 <= j < n:
                carry = None
                continue
            M = recs[i]["motion"] if step == 1 else recs[j]["motion"]
            if M is None:
                carry = None
                continue
            # forward: image_i -> image_j is inv(motion_i); backward: motion_j maps image_i -> image_j
            Hc = carry @ (np.linalg.inv(M) if step == 1 else M)
            gap += 1
            if gap > MAX_PROPAGATION_GAP:
                carry = None
                continue
            r = _verify(Hc, recs[i]["masks"], recs[i]["masks"][0].shape)
            if pitch.passes(r):
                cal.update(H=r["H"], ok=True, source="propagated", support=r["support"], worst_line=r["worst"],
                           error_m=r["error_m"], sigma=r["sigma"], failure=None)
                carry, gap = r["H"], 0
            else:
                carry = Hc
                cal["failure"] = (f"{cal.get('failure') or 'not detected'}; propagated homography failed the "
                                  f"line check (support {r['support']:.2f})")


def _chain(recs):
    """C[k]: image k -> image of the first record of its motion-connected segment; seg[k]: segment id."""
    C, seg = [np.eye(3)], [0]
    for k in range(1, len(recs)):
        M = recs[k]["motion"]
        if M is None:
            C.append(np.eye(3))
            seg.append(seg[-1] + 1)
        else:
            C.append(C[-1] @ np.linalg.inv(M))
            seg.append(seg[-1])
    return C, seg


def pool_keypoints(recs, radius=6):
    """Calibrate frames that no single-frame fit could, from pitch keypoints pooled over nearby frames.

    Keypoints the model found in neighbouring frames of the same shot (within `radius` samples,
    connected by camera motion) are mapped into this frame; the per-landmark median is fitted and
    then refined and verified on this frame's painted lines exactly like a detected fit.
    Marks successes source "propagated". Mutates rec["cal"]; returns how many frames it fixed.
    """
    C, seg = _chain(recs)
    fixed = 0
    for i, rec in enumerate(recs):
        if rec["cal"]["ok"]:
            continue
        pts = {}
        for j in range(max(0, i - radius), min(len(recs), i + radius + 1)):
            kps = recs[j].get("kps")
            if kps is None or seg[j] != seg[i]:
                continue
            h, w = rec["masks"][0].shape
            x, y, c = kps[:, 0], kps[:, 1], kps[:, 2]
            good = (c > pitch.KP_CONF) & (x > pitch.BORDER_PX) & (x < w - pitch.BORDER_PX) & \
                   (y > pitch.BORDER_PX) & (y < h - pitch.BORDER_PX)
            if not good.any():
                continue
            mapped = pitch.project(np.linalg.inv(C[i]) @ C[j], kps[good, :2])
            for v, u in zip(np.where(good)[0], mapped):
                pts.setdefault(int(v), []).append(u)
        if len(pts) < 4:
            continue
        ids = sorted(pts)
        img = np.array([np.median(pts[v], axis=0) for v in ids])
        H, inl, loo = pitch.calibrate(img, pitch.VERTICES[ids])
        if H is None or inl.sum() < 4 or (np.isfinite(loo) and loo > pitch.MAX_LOO_M):
            continue
        r = pitch.refine(H, rec["masks"], img[inl], pitch.VERTICES[ids][inl])
        if pitch.passes(r):
            rec["cal"].update(H=r["H"], ok=True, source="propagated", support=r["support"], worst_line=r["worst"],
                              error_m=r["error_m"], sigma=r["sigma"], failure=None,
                              loo_m=loo if np.isfinite(loo) else None)
            fixed += 1
    return fixed


def smooth_tracks(frames, window_s=0.35, max_speed=12.0):
    """Smooth x/y per track within one shot (local weighted quadratic), keep raw_x/raw_y, add vx/vy.

    frames: frame dicts of one shot (time order) whose players carry raw x/y (None when
    uncalibrated). Velocity needs >= 3 observations spanning >= 0.2 s; implausible speeds
    (> max_speed m/s, i.e. tracking glitches) are reported as null. Mutates the dicts.
    """
    obs = {}
    for f in frames:
        for p in f["players"]:
            p["raw_x"], p["raw_y"], p["vx"], p["vy"] = p["x"], p["y"], None, None
            if p["x"] is not None:
                obs.setdefault(p["track_id"], []).append((f["t"], p))
    for items in obs.values():
        t = np.array([a for a, _ in items])
        xy = np.array([[p["raw_x"], p["raw_y"]] for _, p in items])
        for k, (t0, p) in enumerate(items):
            sel = np.abs(t - t0) <= window_s
            tt, pp = t[sel] - t0, xy[sel]
            if len(tt) < 2:
                continue
            wts = (1 - (np.abs(tt) / (window_s * 1.001)) ** 3) ** 3  # tricube
            deg = 2 if len(tt) >= 5 else 1
            cx = np.polyfit(tt, pp[:, 0], deg, w=np.sqrt(wts))
            cy = np.polyfit(tt, pp[:, 1], deg, w=np.sqrt(wts))
            p["x"], p["y"] = round(float(np.polyval(cx, 0)), 2), round(float(np.polyval(cy, 0)), 2)
            if len(tt) >= 3 and np.ptp(tt) >= 0.2:
                vx, vy = float(cx[-2]), float(cy[-2])  # derivative at t0 = linear coefficient
                if np.hypot(vx, vy) <= max_speed:
                    p["vx"], p["vy"] = round(vx, 2), round(vy, 2)


POSSESSION_M = 1.5  # ball within this distance of a player's feet = that player controls it
MIN_PASS_M, MIN_PASS_SPEED, MAX_BALL_SPEED = 5.0, 4.0, 40.0


def _ball_track(frames):
    """[(frame, (x, y))] of plausible ball ground positions; drops isolated jumps (> MAX_BALL_SPEED)."""
    pts = [(f, np.array([f["ball"]["x"], f["ball"]["y"]])) for f in frames
           if f["calibration"]["ok"] and f.get("ball") and f["ball"].get("x") is not None
           and not f["ball"].get("airborne")]
    keep = []
    for i, (f, p) in enumerate(pts):
        nbrs = [pts[j] for j in (i - 1, i + 1) if 0 <= j < len(pts)]
        speeds = [np.linalg.norm(p - q) / max(abs(f["t"] - g["t"]), 1e-3) for g, q in nbrs]
        if speeds and min(speeds) > MAX_BALL_SPEED:
            continue
        keep.append((f, p))
    return keep


def _owner(frame, ball):
    """(player dict, distance, runner-up distance) of the nearest team player to the ball, or None."""
    cands = [(np.hypot(p["x"] - ball[0], p["y"] - ball[1]), p) for p in frame["players"]
             if p["x"] is not None and p.get("team") in ("A", "B") and p["role"] != "referee"]
    if not cands:
        return None
    cands.sort(key=lambda c: c[0])
    d1, p = cands[0]
    d2 = cands[1][0] if len(cands) > 1 else 10.0
    return (p, d1, d2) if d1 <= POSSESSION_M else None


def detect_passes(frames, max_flight_s=4.0):
    """Candidate pass moments: player P controls the ball, the ball then travels >= MIN_PASS_M at
    >= MIN_PASS_SPEED to another player Q (or clearly away from P). t = last sampled frame P had
    the ball. Conservative: needs calibrated frames and a tracked ground ball; confidence reflects
    possession clarity, ball detection, calibration source and whether a receiver was found."""
    events = []
    by_shot = {}
    for f in frames:
        by_shot.setdefault(f["shot"], []).append(f)
    for shot_frames in by_shot.values():
        track = _ball_track(sorted(shot_frames, key=lambda f: f["t"]))
        owned = []  # (frame, ball xy, owner player, d1, d2)
        for f, b in track:
            o = _owner(f, b)
            owned.append((f, b) + (o if o else (None, None, None)))
        runs = []  # [owner track id, first idx, last idx]
        for i, (f, b, p, d1, d2) in enumerate(owned):
            if p is None:
                continue
            if runs and runs[-1][0] == p["track_id"] and i - runs[-1][2] <= 3:
                runs[-1][2] = i
            else:
                runs.append([p["track_id"], i, i])
        for k, (tid, a, z) in enumerate(runs):
            f_rel, b_rel, passer, d1, d2 = owned[z]
            nxt = runs[k + 1] if k + 1 < len(runs) else None
            receiver, recv_idx = None, None
            if nxt and nxt[0] == tid:
                continue  # same player again: a dribble, not a pass
            if nxt and owned[nxt[1]][0]["t"] - f_rel["t"] <= max_flight_s:
                recv_idx = nxt[1]
                receiver = owned[recv_idx][2]
            end_idx = recv_idx if recv_idx is not None else min(len(owned) - 1, z + 10)
            if end_idx <= z:
                continue
            f_end, b_end = owned[end_idx][0], owned[end_idx][1]
            dist = float(np.linalg.norm(b_end - b_rel))
            dt = f_end["t"] - f_rel["t"]
            speed = dist / max(dt, 1e-3)
            if dist < MIN_PASS_M or not MIN_PASS_SPEED <= speed <= MAX_BALL_SPEED:
                continue
            if receiver is None:  # no receiver seen: require the ball to keep moving away from the passer
                away = [np.linalg.norm(owned[i][1] - b_rel) for i in range(z + 1, end_idx + 1)]
                if len(away) < 3 or any(b <= a for a, b in zip(away, away[1:])):
                    continue
            clarity = float(np.clip((d2 - d1) / 2.0, 0.2, 1.0))
            ball_conf = float(np.mean([owned[i][0]["ball"]["confidence"] for i in range(z, end_idx + 1)]))
            cal = 1.0 if f_rel["calibration"].get("source") == "detected" else 0.9
            if receiver is None:
                recv_factor, tail = 0.5, "no receiver seen"
            elif receiver.get("team") == passer["team"]:
                recv_factor, tail = 1.0, f"reached #{receiver['track_id']} ({receiver['team']}) after {dt:.1f} s"
            else:
                recv_factor, tail = 0.7, f"intercepted by #{receiver['track_id']} ({receiver['team']}) after {dt:.1f} s"
            run_factor = 1.0 if z > a else 0.8
            conf = float(np.clip(0.9 * clarity * ball_conf * cal * recv_factor * run_factor, 0.05, 0.9))
            ev = {"type": "pass", "t": f_rel["t"], "passer_track_id": passer["track_id"], "team": passer["team"],
                  "confidence": round(conf, 2),
                  "reason": f"ball left #{passer['track_id']} at {speed:.0f} m/s over {dist:.0f} m, {tail}",
                  "receiver_track_id": receiver["track_id"] if receiver else None,
                  "receiver_team": receiver.get("team") if receiver else None,
                  "ball_speed_mps": round(speed, 1), "shot": f_rel["shot"]}
            if passer.get("global_id") is not None:
                ev["passer_global_id"] = passer["global_id"]
            events.append(ev)
    return sorted(events, key=lambda e: e["t"])

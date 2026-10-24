"""Offside-position assessment (IFAB Law 11) from one analysed frame's ground-plane positions.

A player is in an offside position if any part of the head, body or feet is in the opponents'
half (excluding the halfway line) AND nearer the opponents' goal line than both the ball and the
second-last opponent. Level is onside. We compare each condition as a signed margin along the
attack direction; margin > 0 means the attacker is beyond that line.

Second-last opponent: the second-deepest located defender when the defending goalkeeper is
located. When the keeper is not located we assume the unseen keeper is the last opponent and use the
deepest located outfield defender as the second-last (stated in reasons). Either way we assume no
opponent outside the camera view is deeper than that player.

Uncertainty (metres) of a margin between two ground positions:

    U = sqrt(r**2 + (2 * BODY_MARGIN_M)**2 + T**2),   T = (0.5 / sampled_fps) * |vx_att - vx_def|

- r = the frame's calibration reprojection error in metres. A homography error displaces nearby
  pitch points in a similar direction, so it largely cancels in a difference; counting it once
  (not twice) is the local-error estimate, not a worst case.
- BODY_MARGIN_M = 0.3: we only have each player's foot anchor (bbox bottom-centre). The furthest
  forward scoring part (head, torso, feet; arms excluded) of a running or leaning player commonly
  sits up to ~0.3 m horizontally from that anchor. Attacker and defender can err in opposite
  directions, so the two margins add linearly (2 * 0.3) rather than in quadrature.
- T = timing: how far the judged state may be from the moment the ball was played (timing_s; by
  default half a sample interval, 0.5 / sampled_fps s). Over that time the margin changes by the
  along-pitch closing speed |vx_att - vx_def| (smoothed track velocities, m/s; the sign of the
  attack direction cancels inside the absolute value). When a velocity is missing the closing speed
  is assumed to be FALLBACK_CLOSING_MPS (a sprint against a standing defender), never zero.
- The sources are independent, so they combine by root-sum-square.
- Opponents outside the picture are unknown. An offside call needs the image to reach MIN_VIEW_ROOM_M
  beyond the second-last opponent along the attack direction (or the goal line); a deeper, unseen
  defender would move the line and undo the call. Onside calls are unaffected.
- When the ball sets the line, its own ground-point error joins the sum. A ball whose height is not
  known (not fitted, so its ground point may be misplaced) cannot set a line: the call is
  inconclusive unless another line already clears the attacker.

review_event() picks the moment from the ball itself (kick_moment) instead of the last sample on
which the passer still "had" the ball, and judges interpolated positions at that moment.
"""
import math

BODY_MARGIN_M = 0.3
FALLBACK_CLOSING_MPS = 8.0  # attacker sprinting past a standing defender; used when a velocity is missing
MIN_VIEW_ROOM_M = 5.0  # an offside call needs the picture to reach at least this far beyond the second-last opponent
AIR_SHIFT_PER_M = 2.5  # ground-point shift per metre of ball height when the shift cannot be read from the data
LIMITS = ("Active involvement (interfering with play or an opponent, gaining an advantage) and "
          "exemptions (goal kick, throw-in, corner kick) cannot be judged from positions; being in "
          "an offside position is not an offence by itself.")


def _result(verdict, reasons, direction=None, **extra):
    base = {"verdict": verdict, "margin_m": None, "uncertainty_m": None, "offside_line_x": None,
            "second_last_defender_track_id": None, "attacker_track_id": None, "attack_direction": direction}
    base.update(extra)
    base["reasons"] = reasons + [LIMITS]
    return base


def _infer_direction(defenders, keeper, length):
    """Attack goes toward the goal the defending team protects."""
    if keeper:
        return ("right" if keeper["x"] > length / 2 else "left"), "Attack direction inferred from the defending goalkeeper's position."
    outfield = [p["x"] for p in defenders]
    if len(outfield) >= 2:
        mean = sum(outfield) / len(outfield)
        # ponytail: mean-of-defenders heuristic; use tracking over the shot if it misleads.
        if abs(mean - length / 2) > 5:
            return ("right" if mean > length / 2 else "left"), "Attack direction inferred from the defending players' mean position (heuristic; goalkeeper not visible)."
    return None, "Attack direction could not be inferred (goalkeeper not visible and defenders near halfway)."


def assess(frame, attacker_track_id, attacking_team, attack_direction=None, length=105.0, sampled_fps=None, timing_s=None, view=None):
    reasons = ["Positions are ground-plane foot anchors from one broadcast camera; body parts are not "
               f"measured, so {BODY_MARGIN_M} m per player is assumed (see uncertainty)."]
    calibration = frame.get("calibration") or {}
    error = calibration.get("reprojection_error_m")
    if not calibration.get("ok") or not isinstance(error, (int, float)):
        return _result("inconclusive", ["Camera calibration is missing or failed for this frame, so pitch positions are unknown."] + reasons, attack_direction, attacker_track_id=attacker_track_id)

    placed = [p for p in frame.get("players") or [] if p.get("role") != "referee" and p.get("x") is not None]
    attacker = next((p for p in placed if p.get("track_id") == attacker_track_id and p.get("team") == attacking_team), None)
    if not attacker:
        return _result("inconclusive", [f"Attacker track {attacker_track_id} (team {attacking_team}) is not located in this frame."] + reasons, attack_direction, attacker_track_id=attacker_track_id)

    defending = "B" if attacking_team == "A" else "A"
    defenders = [p for p in placed if p.get("team") == defending]
    keeper = next((p for p in defenders if p.get("role") == "goalkeeper"), None)
    direction = attack_direction
    if direction is None:
        direction, why = _infer_direction(defenders, keeper, length)
        reasons.append(why)
        if direction is None:
            return _result("inconclusive", reasons, None, attacker_track_id=attacker_track_id)
    sign = 1 if direction == "right" else -1

    defenders.sort(key=lambda p: sign * p["x"], reverse=True)
    if keeper:
        second = defenders[1] if len(defenders) >= 2 else None
    else:
        second = defenders[0] if defenders else None
        if second:
            reasons.append(f"The defending goalkeeper is not visible; assuming the keeper is the last opponent, so the deepest visible "
                           f"outfield defender (track {second.get('track_id')}) is taken as the second-last opponent.")
    timing = 0.0
    speeds = (attacker.get("vx"), second and second.get("vx"))
    window = timing_s if timing_s is not None else (0.5 / sampled_fps if sampled_fps else None)
    if window is not None and second:
        if all(isinstance(v, (int, float)) for v in speeds):
            closing, how = abs(speeds[0] - speeds[1]), ""
        else:
            closing, how = FALLBACK_CLOSING_MPS, " (velocity unavailable: assumed sprint)"
        timing = window * closing
        reasons.append(f"Timing: up to {window:.2f} s between the judged state and the true moment, at a closing speed of "
                       f"{closing:.1f} m/s{how}, adds {timing:.2f} m to the uncertainty.")
    else:
        reasons.append("Movement between sampled frames is not included in the uncertainty (no sampling rate or no defender to compare).")
    base = math.sqrt(error ** 2 + (2 * BODY_MARGIN_M) ** 2 + timing ** 2)

    ball = frame.get("ball") or {}
    ball_error = _ball_error(ball) if ball.get("x") is not None else None
    lines = [("halfway line", length / 2, 0.0)]
    if ball_error is not None:
        lines.append(("ball", ball["x"], ball_error))
    if second:
        lines.append(("second-last opponent", second["x"], 0.0))
    name, line_x, line_err = max(lines, key=lambda item: sign * item[1])
    margin = sign * (attacker["x"] - line_x)
    uncertainty = math.hypot(base, line_err)
    extra = {"margin_m": round(margin, 2), "uncertainty_m": round(uncertainty, 2), "offside_line_x": round(line_x, 2),
             "second_last_defender_track_id": second and second.get("track_id"), "attacker_track_id": attacker_track_id}

    # Failing any one condition is enough for onside, even with the other evidence missing.
    for label, x, err in lines:
        u = math.hypot(base, err)
        if sign * (attacker["x"] - x) < -u:
            reasons.append(f"Attacker is clearly not beyond the {label} ({abs(sign * (attacker['x'] - x)):.2f} m behind, uncertainty {u:.2f} m).")
            return _result("onside", reasons, direction, **extra)

    missing = []
    if ball.get("x") is None:
        missing.append("the ball is not located, so the attacker may be level with or behind it")
    elif ball_error is None:
        missing.append("the ball's height is unknown, so its ground point (and whether the attacker is ahead of it) cannot be trusted")
    if not second:
        missing.append("no opponent to set the offside line is located")
    if missing:
        reasons.append("Cannot establish an offside position: " + "; ".join(missing) + ".")
        return _result("inconclusive", reasons, direction, **extra)

    room = _view_room(frame, second["x"], second.get("y", 0.0), sign, view, length)
    extra["view_room_m"] = room
    if room is not None and room < MIN_VIEW_ROOM_M:
        reasons.append(f"The picture reaches only {room:.1f} m beyond the second-last opponent (needs {MIN_VIEW_ROOM_M:.0f} m): "
                       "a deeper opponent outside the view would move the line, so an offside call cannot be made.")
        if margin > uncertainty:
            return _result("inconclusive", reasons, direction, **extra)
    reasons.append("Assumes no opponent outside the camera view is deeper than the second-last opponent used here.")
    if abs(margin) <= uncertainty:
        reasons.append(f"Margin to the {name} ({margin:+.2f} m) is within the uncertainty ({uncertainty:.2f} m).")
        return _result("inconclusive", reasons, direction, **extra)
    reasons.append(f"Attacker is {margin:.2f} m beyond the {name} (uncertainty {uncertainty:.2f} m) and in the opponents' half.")
    return _result("offside", reasons, direction, **extra)


def _view_room(frame, x, y, sign, view, length):
    """Metres from the pitch point (x, y) along the attack direction to where it leaves the image (or the goal
    line if it never does); None without a homography or image size."""
    h = (frame.get("calibration") or {}).get("homography")
    if not h or not view:
        return None
    def inside(px):
        w = h[2][0] * px + h[2][1] * y + h[2][2]
        u, v = (h[0][0] * px + h[0][1] * y + h[0][2]) / (w or 1e-9), (h[1][0] * px + h[1][1] * y + h[1][2]) / (w or 1e-9)
        return w > 0 and 0 <= u <= view[0] and 0 <= v <= view[1]
    limit = (length - x) if sign > 0 else x
    room = 0.0
    while room < limit and inside(x + sign * (room + 0.5)):
        room += 0.5
    return min(room, max(limit, 0.0))


def _ball_error(ball):
    """Metres the ball's ground point may be off, or None when its height is unknown. A ball on the grass
    (rolling / at a player's feet) is only as uncertain as its detection; an airborne one also carries the
    height error through the camera geometry (ground shift per metre of height, read from the data)."""
    pos = ball.get("position_uncertainty_m") or 0.0
    if ball.get("airborne") is False:
        return pos
    z, height_error = ball.get("z"), ball.get("height_uncertainty_m")
    if ball.get("airborne") is not True or z is None or height_error is None:
        return None
    shift = math.hypot(ball["x"] - ball.get("ground_x", ball["x"]), ball.get("y", 0) - ball.get("ground_y", ball.get("y", 0)))
    return math.hypot(pos, height_error * (shift / z if z > 0.3 else AIR_SHIFT_PER_M))


def review(frame, passer_track_id, team, length=105.0, sampled_fps=None, timing_s=None, attack_direction=None, view=None):
    """Assess every outfield teammate of the passer; key = the most advanced (largest margin)."""
    if team not in ("A", "B"):
        return _result("inconclusive", ["The passer's team is unknown, so the attacking side cannot be set."]), []
    results = [assess(frame, p.get("track_id"), team, attack_direction, length, sampled_fps, timing_s, view) for p in frame.get("players") or []
               if p.get("team") == team and p.get("role") == "player" and p.get("track_id") != passer_track_id]
    if not results:
        return _result("inconclusive", ["No teammate of the passer is detected in this frame."]), []
    results.sort(key=lambda r: -math.inf if r["margin_m"] is None else r["margin_m"], reverse=True)
    return results[0], [{"track_id": r["attacker_track_id"], "verdict": r["verdict"], "margin_m": r["margin_m"]} for r in results]


# --- the moment the ball is played ---------------------------------------------------------------------

MIN_KICK_SPEED_MPS = 5.0     # slower balls cannot be separated from the passer's own motion
KICK_FIT_SAMPLES = 4         # post-kick ball detections used for the straight-line fit
AT_FEET_Z_M = 1.0            # first post-kick detection this low = the ball was struck near the grass
KICK_POSITION_M = 0.5        # foot anchor vs the ball's contact point and ball detection error, together


def _interp(t, ts, vs):
    """Linear interpolation of vs at t, held constant outside ts (ts ascending)."""
    if t <= ts[0]:
        return vs[0]
    for i in range(1, len(ts)):
        if t <= ts[i]:
            return vs[i - 1] + (vs[i] - vs[i - 1]) * (t - ts[i - 1]) / (ts[i] - ts[i - 1])
    return vs[-1]


def _line(ts, vs):
    """Least-squares (slope, intercept) of vs against ts."""
    n, mt, mv = len(ts), sum(ts) / len(ts), sum(vs) / len(vs)
    var = sum((t - mt) ** 2 for t in ts)
    slope = sum((t - mt) * (v - mv) for t, v in zip(ts, vs)) / var if var else 0.0
    return slope, mv - slope * mt


def _track(frames, track_id):
    return [(f["t"], p["x"], p["y"]) for f in frames for p in f.get("players") or []
            if p.get("track_id") == track_id and p.get("x") is not None]


def kick_moment(frames, passer_track_id, t_hint, sampled_fps):
    """When the passer actually played the ball: {"t", "sigma_s", "method"}.

    The detector's pass time is the last sample on which the ball was within 1.5 m of the passer, which
    can be a whole sample before or after the kick (the ball covers 1-2 m per sample after a hard kick).
    Here the first few ball detections after the ball has left are fitted with a straight line, and the
    kick is the moment that line passes closest to the passer's (interpolated) position. sigma is the
    position error divided by the ball's speed relative to the passer. Without a usable fit the time stays
    the detector's and sigma is the whole gap to the next ball detection (the kick is somewhere in it).
    frames: one shot's calibrated frames, any order."""
    frames = sorted(frames, key=lambda f: f["t"])
    step = 1.0 / sampled_fps if sampled_fps else 0.1
    passer = _track(frames, passer_track_id)
    obs = [(f["t"], f["ball"]["x"], f["ball"]["y"], f["ball"].get("z")) for f in frames if f["t"] > t_hint + 1e-6 and (f.get("ball") or {}).get("x") is not None
           and f["ball"].get("height_model") != "outlier"]
    fallback = {"t": t_hint, "sigma_s": max(step, obs[0][0] - t_hint if obs else step), "method": "last sample with the passer in possession"}
    if len(passer) < 2:
        return fallback
    pt, px, py = (list(c) for c in zip(*passer))
    gone = [o for o in obs if math.hypot(o[1] - _interp(o[0], pt, px), o[2] - _interp(o[0], pt, py)) > 1.5]
    if len(gone) < 2 or gone[1][0] - gone[0][0] > 2.5 * step:
        return fallback
    fit = gone[:KICK_FIT_SAMPLES]
    t0 = fit[0][0]
    vx, x0 = _line([r[0] - t0 for r in fit], [r[1] for r in fit])
    vy, y0 = _line([r[0] - t0 for r in fit], [r[2] for r in fit])
    pvx, pvy = (_interp(t0 + 0.05, pt, px) - _interp(t0 - 0.05, pt, px)) / 0.1, (_interp(t0 + 0.05, pt, py) - _interp(t0 - 0.05, pt, py)) / 0.1
    relative = math.hypot(vx - pvx, vy - pvy)
    if math.hypot(vx, vy) < MIN_KICK_SPEED_MPS or relative < MIN_KICK_SPEED_MPS * 0.6:
        return fallback
    best = None
    for k in range(-30, 1):  # search back from the first detection after the ball left, up to 0.3 s
        t = t0 + k * 0.01
        d = math.hypot(x0 + vx * (t - t0) - _interp(t, pt, px), y0 + vy * (t - t0) - _interp(t, pt, py))
        if best is None or d < best[0]:
            best = (d, t)
    d, t = best
    if t < t_hint - 1.5 * step or d > 1.5:
        return fallback
    residual = float(math.sqrt(sum((x0 + vx * (r[0] - t0) - r[1]) ** 2 + (y0 + vy * (r[0] - t0) - r[2]) ** 2 for r in fit) / len(fit)))
    if residual > 1.0:
        return fallback
    sigma = max(0.02, math.hypot(KICK_POSITION_M, d, residual) / relative)
    ball = {"x": round(x0 + vx * (t - t0), 2), "y": round(y0 + vy * (t - t0), 2)}
    z = fit[0][3]
    if isinstance(z, (int, float)) and z <= AT_FEET_Z_M:  # struck near the grass: its ground point is where it was played
        ball.update(airborne=False, z=0.0, height_model="at_kick", position_uncertainty_m=KICK_POSITION_M)
    return {"t": round(t, 3), "sigma_s": round(min(sigma, step), 3),
            "method": f"ball line fitted to {len(fit)} detections (ball {math.hypot(vx, vy):.0f} m/s, {d:.1f} m from the passer at the kick)",
            "ball": ball}


def frame_at(frames, t, kick_ball=None):
    """The scene at time t: players interpolated between the two calibrated samples around t (a player seen in
    only one of them keeps that sample's position), calibration error = the worse of the two, ball from the
    kick-line fit when given. Falls back to the nearest sample when t has no calibrated sample on both sides."""
    near = min(frames, key=lambda f: abs(f["t"] - t))
    f0 = max((f for f in frames if f["t"] <= t), key=lambda f: f["t"], default=None)
    f1 = min((f for f in frames if f["t"] >= t), key=lambda f: f["t"], default=None)
    scene = dict(near)
    if f0 and f1 and f0 is not f1 and all((f.get("calibration") or {}).get("ok") for f in (f0, f1)):
        w = (t - f0["t"]) / (f1["t"] - f0["t"])
        other = {p.get("track_id"): p for p in (f1 if near is f0 else f0).get("players") or []}
        players = []
        for p in near.get("players") or []:
            q = other.get(p.get("track_id"))
            mix = dict(p)
            if q and p.get("x") is not None and q.get("x") is not None:
                a, b = (p, q) if near is f0 else (q, p)
                for key in ("x", "y", "vx", "vy"):
                    if isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float)):
                        mix[key] = a[key] + (b[key] - a[key]) * w
            players.append(mix)
        errors = [f["calibration"].get("reprojection_error_m") for f in (f0, f1)]
        scene.update(t=round(t, 3), players=players, calibration=dict(near["calibration"], reprojection_error_m=max(errors) if all(isinstance(e, (int, float)) for e in errors) else None))
    ball = dict(near.get("ball") or {})
    if kick_ball:
        if not ball:  # not detected on the nearest sample: borrow the height facts from the first detection after it
            ball = dict(next((f["ball"] for f in frames if f["t"] > near["t"] and (f.get("ball") or {}).get("x") is not None), {}))
        ball.update(kick_ball)
    return dict(scene, ball=ball or None)


DIRECTION_MIN_PLAYERS = 3  # outfielders a team needs in a frame to say where it stands relative to its opponents
DIRECTION_MIN_FRAMES = 10  # frames that must vote
DIRECTION_AGREE = 0.7      # share of voting frames that must agree
DIRECTION_GAP_M = 3.0      # mean position of the opponents versus the team's own, to count as a vote


def _keeper_end(frames, team, length):
    xs = sorted(p["x"] for f in frames if (f.get("calibration") or {}).get("ok") for p in f.get("players") or []
                if p.get("role") == "goalkeeper" and p.get("team") == team and p.get("x") is not None)
    return None if len(xs) < 3 else ("right" if xs[len(xs) // 2] > length / 2 else "left")


def _positions_direction(frames, team):
    """The end `team` seems to attack, from where its opponents stand relative to it, or None: opponents between a team and
    the goal it attacks is the usual picture, but in transitions it flips, so it is only ever a cross-check."""
    votes = []
    for f in frames:
        if not (f.get("calibration") or {}).get("ok"):
            continue
        own = [p["x"] for p in f.get("players") or [] if p.get("role") == "player" and p.get("team") == team and p.get("x") is not None]
        opp = [p["x"] for p in f.get("players") or [] if p.get("role") == "player" and p.get("team") not in (None, team) and p.get("x") is not None]
        if len(own) >= DIRECTION_MIN_PLAYERS and len(opp) >= DIRECTION_MIN_PLAYERS:
            gap = sum(opp) / len(opp) - sum(own) / len(own)
            if abs(gap) > DIRECTION_GAP_M:
                votes.append("right" if gap > 0 else "left")
    if len(votes) < DIRECTION_MIN_FRAMES:
        return None
    top = max(("left", "right"), key=votes.count)
    return top if votes.count(top) >= DIRECTION_AGREE * len(votes) else None


def window_direction(frames, team, length):
    """(direction, why) for the end `team` attacks, or (None, why not). A goalkeeper seen in the shot says which end each team
    defends, and the teams' positions must agree with it: either alone has been wrong on real clips, and a guess here flips
    every margin in the review."""
    opponent = "B" if team == "A" else "A"
    claims = set()
    if (end := _keeper_end(frames, opponent, length)):
        claims.add(end)  # the team attacks the end its opponent's keeper defends
    if (end := _keeper_end(frames, team, length)):
        claims.add("left" if end == "right" else "right")
    if not claims:
        return None, "no goalkeeper is seen in this shot"
    if len(claims) > 1:
        return None, "the goalkeepers seen contradict each other"
    direction = claims.pop()
    positions = _positions_direction(frames, team)
    if positions is None:
        return None, "the teams' positions in the shot do not confirm which end the goalkeeper defends"
    if positions != direction:
        return None, "the goalkeeper and the teams' positions point to different ends"
    return direction, "goalkeeper seen in this shot, confirmed by the teams' positions"


def feasibility(frame, result, team, shot_frames=None, moment=None, direction_source=None):
    """What the offside review had to work with, so the app can say when it is available and why not.
    blockers stop a decisive call; warnings only widen or qualify it."""
    calibration = frame.get("calibration") or {}
    placed = [p for p in frame.get("players") or [] if p.get("role") != "referee" and p.get("x") is not None]
    attacker = next((p for p in placed if p.get("track_id") == result.get("attacker_track_id") and p.get("team") == team), None)
    defenders = [p for p in placed if team and p.get("team") not in (None, team)]
    keeper = "located" if any(p.get("role") == "goalkeeper" for p in defenders) else "assumed"
    ball = frame.get("ball") or {}
    calibrated = bool(calibration.get("ok"))
    blockers, warnings = [], []
    if not calibrated:
        blockers.append("no calibrated wide view of this moment")
    if attacker is None:
        blockers.append("attacker not tracked at this moment")
    if not defenders:
        blockers.append("no opponent tracked")
    if result.get("verdict") != "onside":  # a clear onside call needs no ball and no direction beyond what it already used
        if ball.get("x") is None:
            blockers.append("ball not located")
        elif _ball_error(ball) is None:
            blockers.append("ball height unknown")
    if result.get("restart"):
        blockers.append(f"the pass restarts play with a {result['restart']}: offside does not apply")
    if result.get("attack_direction") is None:
        blockers.append("attack direction unknown")
    if keeper == "assumed" and defenders:
        warnings.append("defending goalkeeper not seen: assumed to be the last opponent")
    room = result.get("view_room_m")
    if room is not None and room < MIN_VIEW_ROOM_M:
        warnings.append(f"the picture reaches only {room:.1f} m beyond the second-last opponent: an offside call is not possible")
    if moment and moment.get("method", "").startswith("last sample"):
        warnings.append("ball-contact moment is only bracketed to the detector's sample")
    shot = [f for f in shot_frames or [] if f is not None]
    return {"available": not blockers, "blockers": blockers, "warnings": warnings,
            "calibrated": calibrated, "calibration_source": calibration.get("source"),
            "calibrated_frames": [sum(1 for f in shot if (f.get("calibration") or {}).get("ok")), len(shot)] if shot else None,
            "tracked_players": len(placed), "tracked_opponents": len(defenders),
            "ball_contact_moment": None if moment is None else {"found": not moment["method"].startswith("last sample"), "t": moment["t"],
                                                                 "sigma_s": moment["sigma_s"], "method": moment["method"]},
            "goalkeeper": keeper, "attack_direction_source": direction_source}


RESTART_WINDOW_S = 0.8  # the ball must have sat still this long before the kick ...
RESTART_STILL_M = 1.0   # ... within this distance
CORNER_M = 2.5          # near a corner flag: a corner kick
GOAL_AREA_M = (5.5, 18.32)  # depth and width of the goal area: a goal kick is taken from inside it


def restart_kind(frames, t, length=105.0, width=68.0):
    """'corner kick' or 'goal kick' when the ball sat still on the grass where one is taken just before t, else None.
    Offside does not apply to either. A keeper picking the ball up and kicking it from the same spot looks the
    same (the ball is still), so the goal-kick reading is worded as a possibility."""
    seen = [(f["ball"]["x"], f["ball"]["y"]) for f in frames if t - RESTART_WINDOW_S <= f["t"] <= t + 1e-6
            and (f.get("calibration") or {}).get("ok") and (f.get("ball") or {}).get("x") is not None and f["ball"].get("airborne") is not True]
    if len(seen) < 3:
        return None
    x, y = sorted(p[0] for p in seen)[len(seen) // 2], sorted(p[1] for p in seen)[len(seen) // 2]
    if max(math.hypot(px - x, py - y) for px, py in seen) > RESTART_STILL_M:
        return None
    if any(math.hypot(x - cx, y - cy) <= CORNER_M for cx in (0.0, length) for cy in (0.0, width)):
        return "corner kick"
    depth, wide = GOAL_AREA_M
    return "goal kick" if (x <= depth or x >= length - depth) and abs(y - width / 2) <= wide / 2 else None


def review_event(frames, event, length=105.0, sampled_fps=None, view=None):
    """Offside review of one detected pass: (key result, candidates). The moment is the estimated kick, the scene
    is interpolated to it, and the result carries a feasibility record."""
    shot = sorted((f for f in frames if f.get("shot") == event.get("shot")) or frames, key=lambda f: f["t"])
    calibrated = [f for f in shot if (f.get("calibration") or {}).get("ok")]
    passer, team = event.get("passer_track_id"), event.get("team")
    moment = kick_moment(calibrated, passer, event["t"], sampled_fps)
    frame = frame_at(shot, moment["t"], moment.get("ball"))
    direction, source = window_direction(calibrated, team, length) if team in ("A", "B") else (None, "the passer's team is unknown")
    if direction is None:  # never guess: a wrong end flips every margin
        key = _result("inconclusive", [f"The attack direction is not established ({source}), so offside cannot be read from this pass."])
        key.update(frame_t=frame["t"], moment=moment)
        key["feasibility"] = feasibility(frame, key, team, shot, moment, source)
        return key, []
    key, candidates = review(frame, passer, team, length, sampled_fps, moment["sigma_s"], direction, view)
    key["reasons"].insert(0, f"Moment the ball was played: {moment['t']:.2f} s ({moment['method']}; +/- {moment['sigma_s']:.2f} s); "
                             f"the detector's sample was {event['t']:.2f} s.")
    key["frame_t"], key["moment"] = frame["t"], moment
    step = 1.0 / sampled_fps if sampled_fps else 0.1

    def checked(result):
        """Judge the same attacker one sample either side of the moment; a decisive call that the neighbours
        reverse (a defender appearing or vanishing, a track swap) is not trustworthy: inconclusive."""
        attacker = result.get("attacker_track_id")
        if attacker is None or result["margin_m"] is None:
            return result
        near = []
        for dt in (-step, step):
            r = assess(frame_at(shot, moment["t"] + dt, moment.get("ball")), attacker, team, direction, length, sampled_fps, moment["sigma_s"], view)
            near.append({"dt_s": round(dt, 3), "verdict": r["verdict"], "margin_m": r["margin_m"]})
        result["timing_check"] = near
        opposite = {"onside": "offside", "offside": "onside"}.get(result["verdict"])
        if any(n["verdict"] == opposite for n in near):
            result["reasons"].append("One sample either side of the moment the call reverses (" + ", ".join(
                f"{n['dt_s']:+.2f} s: {n['verdict']} {n['margin_m']:+.2f} m" for n in near) + "), so it depends on the exact instant or on a player "
                "who is tracked in only some samples; not decisive.")
            result["verdict"] = "inconclusive"
        return result

    checked(key)
    receiver = event.get("receiver_track_id")
    if receiver is not None and event.get("receiver_team") == team:  # the player the pass was played to
        r = checked(assess(frame, receiver, team, direction, length, sampled_fps, moment["sigma_s"], view))
        key["receiver"] = {k: r.get(k) for k in ("verdict", "margin_m", "uncertainty_m", "attacker_track_id", "timing_check")}
    restart = restart_kind(calibrated, moment["t"], length)
    if restart:  # offside does not apply: say so instead of judging the players
        key["restart"] = restart
        key["verdict"] = "inconclusive"
        key["reasons"].insert(0, f"The ball sat still before this pass where a {restart} is taken, and offside does not apply to a {restart}"
                                 + (" (a goalkeeper restarting play from his hands looks the same here)." if restart == "goal kick" else "."))
        for c in candidates:
            c["verdict"] = "inconclusive"
        if key.get("receiver"):
            key["receiver"]["verdict"] = "inconclusive"
    key["feasibility"] = feasibility(frame, key, team, shot, moment, source)
    return key, candidates

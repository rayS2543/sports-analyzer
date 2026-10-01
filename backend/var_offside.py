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
- T = timing: the judged frame is the sampled frame nearest the moment the ball was played, so the
  true moment is up to half a sample interval (0.5 / sampled_fps s) away. Over that time the margin
  changes by the along-pitch closing speed |vx_att - vx_def| (smoothed track velocities, m/s; the
  sign of the attack direction cancels inside the absolute value). Only added when both velocities
  and sampled_fps exist; otherwise reasons say timing is not included.
- The sources are independent, so they combine by root-sum-square.

Not included: the ball's own movement between samples, and a ball in the air projecting to the
wrong ground point (flagged in reasons when the ball sets the line).
"""
import math

BODY_MARGIN_M = 0.3
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


def assess(frame, attacker_track_id, attacking_team, attack_direction=None, length=105.0, sampled_fps=None):
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
    if sampled_fps and all(isinstance(v, (int, float)) for v in speeds):
        timing = 0.5 / sampled_fps * abs(speeds[0] - speeds[1])
        reasons.append(f"Timing: up to {0.5 / sampled_fps:.2f} s between the sampled frame and the true moment, at a closing speed of "
                       f"{abs(speeds[0] - speeds[1]):.1f} m/s, adds {timing:.2f} m to the uncertainty.")
    else:
        reasons.append("Movement between sampled frames is not included in the uncertainty (velocities unavailable).")
    uncertainty = math.sqrt(error ** 2 + (2 * BODY_MARGIN_M) ** 2 + timing ** 2)

    ball = frame.get("ball") or {}
    lines = [("halfway line", length / 2)]
    if ball.get("x") is not None:
        lines.append(("ball", ball["x"]))
    if second:
        lines.append(("second-last opponent", second["x"]))
    name, line_x = max(lines, key=lambda item: sign * item[1])
    margin = sign * (attacker["x"] - line_x)
    extra = {"margin_m": round(margin, 2), "uncertainty_m": round(uncertainty, 2), "offside_line_x": round(line_x, 2),
             "second_last_defender_track_id": second and second.get("track_id"), "attacker_track_id": attacker_track_id}

    # Failing any one condition is enough for onside, even with the other evidence missing.
    for label, x in lines:
        if sign * (attacker["x"] - x) < -uncertainty:
            reasons.append(f"Attacker is clearly not beyond the {label} ({abs(sign * (attacker['x'] - x)):.2f} m behind, uncertainty {uncertainty:.2f} m).")
            return _result("onside", reasons, direction, **extra)

    missing = []
    if ball.get("x") is None:
        missing.append("the ball is not located, so the attacker may be level with or behind it")
    if not second:
        missing.append("no opponent to set the offside line is located")
    if missing:
        reasons.append("Cannot establish an offside position: " + "; ".join(missing) + ".")
        return _result("inconclusive", reasons, direction, **extra)

    reasons.append("Assumes no opponent outside the camera view is deeper than the second-last opponent used here.")
    if abs(margin) <= uncertainty:
        reasons.append(f"Margin to the {name} ({margin:+.2f} m) is within the uncertainty ({uncertainty:.2f} m).")
        return _result("inconclusive", reasons, direction, **extra)
    reasons.append(f"Attacker is {margin:.2f} m beyond the {name} (uncertainty {uncertainty:.2f} m) and in the opponents' half.")
    if name == "ball":
        reasons.append("The ball sets the line; an airborne ball's ground projection may be misplaced.")
    return _result("offside", reasons, direction, **extra)


def review(frame, passer_track_id, team, length=105.0, sampled_fps=None):
    """Assess every outfield teammate of the passer; key = the most advanced (largest margin)."""
    if team not in ("A", "B"):
        return _result("inconclusive", ["The passer's team is unknown, so the attacking side cannot be set."]), []
    results = [assess(frame, p.get("track_id"), team, None, length, sampled_fps) for p in frame.get("players") or []
               if p.get("team") == team and p.get("role") == "player" and p.get("track_id") != passer_track_id]
    if not results:
        return _result("inconclusive", ["No teammate of the passer is detected in this frame."]), []
    results.sort(key=lambda r: -math.inf if r["margin_m"] is None else r["margin_m"], reverse=True)
    return results[0], [{"track_id": r["attacker_track_id"], "verdict": r["verdict"], "margin_m": r["margin_m"]} for r in results]

"""Sending-off assessment (IFAB Law 12, 2026/27) from the CV foul measurements (cv/var_cv/fouls.py).

The CV step measures; this module decides, per ground, red | not_red | inconclusive, and never
looks at the official decision.

Law text used (theifab.com/laws/latest/fouls-and-misconduct):
- Serious foul play: "A tackle or challenge that endangers the safety of an opponent or uses excessive
  force or brutality"; a player who lunges at an opponent "using one or both legs, with excessive force
  or endangers the safety of an opponent".
- Violent conduct: excessive force or brutality "when not challenging for the ball"; a player who, when
  not challenging for the ball, "deliberately strikes an opponent ... on the head or face with the hand
  or arm" unless the force used was negligible.
- DOGSO considerations: distance between the offence and the goal; general direction of the play;
  likelihood of keeping or gaining control of the ball; location and number of defenders and attackers.
  In the offender's own penalty area, when a penalty is awarded, an offence that was an attempt to play
  the ball or a challenge for it is a caution; holding, pulling, pushing, no possibility to play the ball
  etc. remain a sending-off.

The Laws give no numbers. The thresholds below are this system's policy for turning measurements into
a call; they are stated in every result, and anything between "clearly yes" and "clearly no" is
inconclusive. An indicator is relied on only when observable with confidence >= RELY.
"""

RELY = 0.6
FAST_MPS = 5.0          # challenger speed treated as "force" alongside studs showing
ARM_FORCE_MPS = 3.0     # arm speed above which a strike's force is not negligible
DOGSO_NEAR_M = 30.0     # distance at which an opportunity can be obvious
DOGSO_FAR_M = 40.0      # beyond this, not an obvious opportunity
CONTROL_M = 2.5         # ball within this of the attacker = control likely
NO_CONTROL_M = 5.0      # ball further than this = control unlikely
GROUND_LABEL = {"serious_foul_play": "Serious foul play", "violent_conduct": "Violent conduct",
                "dogso": "Denying an obvious goal-scoring opportunity"}
POLICY = (f"Thresholds are this system's policy, not IFAB numbers: indicators count at >= {RELY:.0%} confidence; "
          f"speed >= {FAST_MPS:g} m/s, arm speed >= {ARM_FORCE_MPS:g} m/s, DOGSO within {DOGSO_NEAR_M:g} m "
          f"(not beyond {DOGSO_FAR_M:g} m), control = ball within {CONTROL_M:g} m.")


def _i(indicators, key):
    return indicators.get(key) or {"label": key, "value": None, "confidence": 0.0, "observable": False, "detail": "Not measured."}


def _yes(i):
    return bool(i.get("observable")) and i.get("value") is True and (i.get("confidence") or 0) >= RELY


def _no(i):
    return bool(i.get("observable")) and i.get("value") is False and (i.get("confidence") or 0) >= RELY


def _reliable(i):
    return bool(i.get("observable")) and i.get("value") is not None and (i.get("confidence") or 0) >= RELY


def _why_unknown(i):
    if not i.get("observable"):
        return f"{i.get('label')}: not observable ({i.get('detail') or 'no evidence'})"
    return f"{i.get('label')}: confidence {i.get('confidence', 0):.0%} is below {RELY:.0%}"


def _ground(name, verdict, used, reasons, **extra):
    out = {"ground": name, "label": GROUND_LABEL[name], "verdict": verdict,
           "indicators": [dict(v, key=k) for k, v in used.items()], "reasons": reasons}
    out.update(extra)
    return out


def serious_foul_play(ind):
    keys = ("contact", "contact_above_ankle", "studs_showing", "both_feet_off_ground", "straight_leg_high_foot",
            "challenger_speed", "challenging_for_ball")
    used = {k: _i(ind, k) for k in keys}
    contact, ball = used["contact"], used["challenging_for_ball"]
    danger = {k: used[k] for k in ("studs_showing", "both_feet_off_ground", "straight_leg_high_foot")}
    if not contact.get("observable"):
        return _ground("serious_foul_play", "inconclusive", used, [_why_unknown(contact)])
    if _no(ball):
        return _ground("serious_foul_play", "not_red", used, [
            "The ball was not playable, so this was not a challenge for the ball; see violent conduct."])
    if _no(contact):
        if any(_yes(v) for v in danger.values()):
            return _ground("serious_foul_play", "inconclusive", used, [
                "No contact was measured, but a dangerous action was: a lunge can endanger an opponent without touching them."])
        return _ground("serious_foul_play", "not_red", used, ["No contact between the players was measured."])
    if not _yes(contact):
        return _ground("serious_foul_play", "inconclusive", used, [_why_unknown(contact) if not _reliable(contact) else
                                                                   "Contact could not be resolved from the pose."])
    speed = used["challenger_speed"]
    fast = _reliable(speed) and speed["value"] >= FAST_MPS
    above = _yes(used["contact_above_ankle"])
    signs = []
    if _yes(danger["studs_showing"]) and (above or fast):
        signs.append("studs/sole led into the opponent " + ("above the ankle" if above else f"at {speed['value']:g} m/s"))
    if _yes(danger["both_feet_off_ground"]):
        signs.append("the challenger lunged with both feet off the ground")
    if _yes(danger["straight_leg_high_foot"]) and above:
        signs.append("a straight leg with a high foot made contact above the ankle")
    if signs:
        return _ground("serious_foul_play", "red", used, [
            "Contact in a challenge that endangers the opponent's safety: " + "; ".join(signs) + ".",
            "Force and intent are not measured; the call rests on the challenge's geometry."])
    if all(_no(v) for v in danger.values()):
        return _ground("serious_foul_play", "not_red", used, [
            "Contact was made, but no measured sign of endangering the opponent (studs, lunge, straight leg high).",
            "Careless or reckless play (free kick / caution) is not assessed here."])
    return _ground("serious_foul_play", "inconclusive", used, [
        "Contact was made, but the danger signs could not all be measured: "
        + "; ".join(_why_unknown(v) for v in danger.values() if not (_yes(v) or _no(v))) + "."])


def violent_conduct(ind):
    used = {k: _i(ind, k) for k in ("off_ball_strike", "challenging_for_ball", "contact")}
    strike, ball = used["off_ball_strike"], used["challenging_for_ball"]
    scope = "Only hand/arm strikes to the head are measured; kicks, headbutts or off-ball force are not assessed."
    if _no(strike):
        return _ground("violent_conduct", "not_red", used, ["No hand or arm of the challenger reached the opponent's head.", scope])
    if not _yes(strike):
        return _ground("violent_conduct", "inconclusive", used, [_why_unknown(strike), scope])
    if _yes(ball):
        return _ground("violent_conduct", "inconclusive", used, [
            "A hand or arm reached the head while the ball was playable: a deliberate strike cannot be separated from a challenge from pixels."])
    if not _no(ball):
        return _ground("violent_conduct", "inconclusive", used, [
            "A hand or arm reached the head, but whether the ball was playable is unknown: " + _why_unknown(ball) + "."])
    speed = strike.get("arm_speed_mps")
    if speed is None or speed < ARM_FORCE_MPS:
        return _ground("violent_conduct", "inconclusive", used, [
            "Hand or arm to the head when not challenging for the ball, but the force may have been negligible "
            + ("(arm speed unknown)." if speed is None else f"(arm moving {speed:g} m/s).")])
    return _ground("violent_conduct", "red", used, [
        f"Hand or arm to the opponent's head when not challenging for the ball, arm moving {speed:g} m/s (force not negligible).",
        "Deliberateness is inferred from the movement, not measured."])


def dogso(ind, factors):
    keys = ("distance_to_goal", "direction_of_play", "control", "defenders_between", "attackers", "in_penalty_area",
            "attempt_to_play_ball")
    used = {"contact": _i(ind, "contact")}
    used.update({k: _i(factors, k) for k in keys})
    note = "Whether the contact was a foul is not decided here; DOGSO is assessed as if it were."
    if _no(used["contact"]):
        return _ground("dogso", "not_red", used, ["No contact was measured, so there is no offence to deny an opportunity."])
    if not _yes(used["contact"]):
        return _ground("dogso", "inconclusive", used, ["No offence could be established: " + _why_unknown(used["contact"]) + "."])
    dist, dirn, ctrl, dfn = (used[k] for k in ("distance_to_goal", "direction_of_play", "control", "defenders_between"))
    against = []
    if _reliable(dist) and dist["value"] > DOGSO_FAR_M:
        against.append(f"{dist['value']:g} m from goal")
    if _reliable(dirn) and dirn["value"] == "away_from_goal":
        against.append("play moving away from goal")
    if _reliable(ctrl) and ctrl["value"] > NO_CONTROL_M:
        against.append(f"ball {ctrl['value']:g} m from the attacker")
    if _reliable(dfn) and dfn["value"] >= 2:
        against.append(f"{dfn['value']} defenders between the attacker and goal")
    if against:
        return _ground("dogso", "not_red", used, ["Not an obvious goal-scoring opportunity: " + "; ".join(against) + ".", note])
    unknown = [v for v in (dist, dirn, ctrl, dfn) if not _reliable(v)]
    if unknown:
        return _ground("dogso", "inconclusive", used, ["; ".join(_why_unknown(v) for v in unknown) + ".", note])
    blocked = dfn["value"] - (dfn.get("goalkeepers") or 0) > 0 or ((dfn.get("goalkeepers") or 0) and dist["value"] > 16.5)
    full_view = (dfn.get("corridor_in_view") or 0) >= 0.9
    if (dist["value"] <= DOGSO_NEAR_M and dirn["value"] == "towards_goal" and ctrl["value"] <= CONTROL_M
            and not blocked and full_view):
        return _downgrade(used, [
            f"{dist['value']:g} m from goal, moving towards it, ball {ctrl['value']:g} m away and no defender able to intervene "
            f"({dfn['value']} in the corridor to goal).", note])
    return _ground("dogso", "inconclusive", used, [
        "Factors fall between clearly obvious and clearly not"
        + ("" if full_view else " (part of the area to goal is off-camera, so unseen defenders are possible)") + ".", note])


def _downgrade(used, reasons):
    box, attempt = used["in_penalty_area"], used["attempt_to_play_ball"]
    if _no(box):
        return _ground("dogso", "red", used, reasons + ["Outside the offender's penalty area: sending-off."])
    if not _yes(box):
        return _ground("dogso", "inconclusive", used, reasons + [
            "The offence is too close to the penalty-area line to know whether the penalty-area downgrade applies."])
    if _yes(attempt):
        return _ground("dogso", "not_red", used, reasons + [
            "Inside the offender's own penalty area with an attempt to play the ball: Law 12 downgrades this to a caution (penalty kick)."],
            downgraded_to="yellow")
    if _no(attempt):
        return _ground("dogso", "red", used, reasons + [
            "Inside the penalty area but not an attempt to play the ball (e.g. holding, pulling, pushing): still a sending-off."])
    return _ground("dogso", "inconclusive", used, reasons + [
        "Inside the penalty area: red if there was no attempt to play the ball, yellow if there was; " + _why_unknown(attempt) + "."])


def sanction(grounds):
    verdicts = [g["verdict"] for g in grounds]
    if "red" in verdicts:
        return "red"
    if "inconclusive" in verdicts:
        return "inconclusive"
    if any(g.get("downgraded_to") == "yellow" for g in grounds):
        return "yellow"
    return "none"


def assess_incident(inc):
    ind, factors = inc.get("indicators") or {}, inc.get("dogso") or {}
    grounds = [serious_foul_play(ind), violent_conduct(ind), dogso(ind, factors)]
    result = sanction(grounds)
    notes = {"red": "At least one sending-off ground is met by the measurements.",
             "inconclusive": "No ground is clearly met, but at least one could not be ruled out from this footage.",
             "yellow": "Penalty-area DOGSO with an attempt to play the ball: caution, not a sending-off.",
             "none": "No sending-off ground is met. Cautions for reckless play or stopping a promising attack are not assessed."}
    return {"id": inc.get("id"), "t": inc.get("t"), "t_range": inc.get("t_range"), "shot": inc.get("shot"),
            "players": inc.get("players"), "calibrated": inc.get("calibrated", False), "grounds": grounds,
            "sanction": result, "sanction_note": notes[result], "notes": (inc.get("notes") or []) + [POLICY],
            "attack_direction": factors.get("attack_direction")}


def review(fouls):
    incidents = [assess_incident(i) for i in fouls.get("incidents") or []]
    if not incidents:
        message = "No opposing players came close enough in this window to examine a challenge."
    else:
        message = None
    return {"incidents": incidents, "message": message, "candidates_found": fouls.get("candidates_found"),
            "assumptions": fouls.get("assumptions") or [], "policy": POLICY}

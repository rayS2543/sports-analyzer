import math

import pytest

from var_offside import BODY_MARGIN_M, FALLBACK_CLOSING_MPS, assess, feasibility, frame_at, kick_moment, review, review_event


def player(track, team, x, role="player", y=30.0):
    return {"track_id": track, "team": team, "role": role, "x": x, "y": y}


def frame(attacker_x, second_x=80.0, keeper=True, ball_x=60.0, error=0.4, ok=True):
    players = [player(7, "A", attacker_x), player(3, "B", second_x), player(4, "B", 70.0), player(9, "A", 50.0),
               {"track_id": 20, "team": None, "role": "referee", "x": 99.0, "y": 10.0}]
    if keeper:
        players.append(player(1, "B", 100.0, role="goalkeeper"))
    return {"t": 1.0, "calibration": {"ok": ok, "reprojection_error_m": error},
            "ball": None if ball_x is None else {"x": ball_x, "y": 30.0, "airborne": False}, "players": players}


U = math.sqrt(0.4 ** 2 + (2 * BODY_MARGIN_M) ** 2)


@pytest.mark.parametrize("attacker_x, direction, verdict", [
    (83.0, "right", "offside"),       # 3 m beyond second-last
    (77.0, "right", "onside"),        # 3 m behind
    (80.5, "right", "inconclusive"),  # inside uncertainty
    (80.0, "right", "inconclusive"),  # level: within uncertainty, not "onside by rule"
    (83.0, None, "offside"),          # direction from keeper at x=100
])
def test_table(attacker_x, direction, verdict):
    result = assess(frame(attacker_x), 7, "A", direction)
    assert result["verdict"] == verdict
    assert result["attack_direction"] == "right"
    assert result["uncertainty_m"] == round(U, 2)
    assert any("cannot be judged from positions" in r for r in result["reasons"])


def test_offside_reports_line_and_defender():
    result = assess(frame(83.0), 7, "A", "right")
    assert result["margin_m"] == 3.0
    assert result["offside_line_x"] == 80.0
    assert result["second_last_defender_track_id"] == 3
    assert result["attacker_track_id"] == 7


@pytest.mark.parametrize("f, why", [
    (frame(83.0, ok=False), "calibration"),
    (frame(83.0, error=None), "calibration"),
    (frame(83.0, ball_x=None), "ball is not located"),
])
def test_missing_evidence_is_inconclusive(f, why):
    result = assess(f, 7, "A", "right")
    assert result["verdict"] == "inconclusive"
    assert any(why in r for r in result["reasons"])


def test_untracked_attacker_or_wrong_team():
    assert assess(frame(83.0), 99, "A", "right")["verdict"] == "inconclusive"
    assert assess(frame(83.0), 7, "B", "right")["verdict"] == "inconclusive"


@pytest.mark.parametrize("attacker_x, verdict", [(83.0, "offside"), (77.0, "onside"), (80.4, "inconclusive")])
def test_unseen_keeper_uses_deepest_outfield_defender(attacker_x, verdict):
    # Keeper off-screen: the deepest visible outfielder (x=80) becomes second-last, not the one at 70.
    result = assess(frame(attacker_x, keeper=False), 7, "A", "right")
    assert result["verdict"] == verdict
    assert result["second_last_defender_track_id"] == 3 and result["offside_line_x"] == 80.0
    assert any("assuming the keeper is the last opponent" in r for r in result["reasons"])


def test_visible_keeper_makes_no_assumption():
    result = assess(frame(83.0), 7, "A", "right")
    assert not any("assuming the keeper" in r for r in result["reasons"])


def test_single_outfield_defender_without_keeper():
    f = frame(83.0, keeper=False)
    f["players"] = [p for p in f["players"] if p["track_id"] != 4]
    assert assess(f, 7, "A", "right")["verdict"] == "offside"


def test_no_defender_located_is_inconclusive():
    f = frame(83.0, keeper=False)
    f["players"] = [p for p in f["players"] if p["team"] != "B"]
    result = assess(f, 7, "A", "right")
    assert result["verdict"] == "inconclusive" and result["second_last_defender_track_id"] is None


def with_speeds(f, attacker_vx, defender_vx):
    for p in f["players"]:
        p["vx"] = {7: attacker_vx, 3: defender_vx}.get(p["track_id"], 0.0)
    return f


def test_timing_term_uses_closing_speed_and_fps():
    result = assess(with_speeds(frame(83.0), 6.0, -2.0), 7, "A", "right", sampled_fps=10)
    timing = 0.5 / 10 * 8.0
    assert result["uncertainty_m"] == round(math.sqrt(0.4 ** 2 + (2 * BODY_MARGIN_M) ** 2 + timing ** 2), 2)
    assert any("Timing" in r for r in result["reasons"])


def test_timing_can_turn_a_call_inconclusive():
    f = with_speeds(frame(81.2), 8.0, -6.0)
    assert assess(f, 7, "A", "right")["verdict"] == "offside"  # no fps: timing not included
    assert assess(f, 7, "A", "right", sampled_fps=5)["verdict"] == "inconclusive"


@pytest.mark.parametrize("attacker_vx, defender_vx", [(None, 1.0), (1.0, None)])
def test_missing_velocity_assumes_a_sprint_not_zero(attacker_vx, defender_vx):
    result = assess(with_speeds(frame(83.0), attacker_vx, defender_vx), 7, "A", "right", sampled_fps=10)
    timing = 0.5 / 10 * FALLBACK_CLOSING_MPS
    assert result["uncertainty_m"] == round(math.sqrt(0.4 ** 2 + (2 * BODY_MARGIN_M) ** 2 + timing ** 2), 2)
    assert any("assumed sprint" in r for r in result["reasons"])


def test_explicit_timing_window_replaces_half_sample():
    result = assess(with_speeds(frame(83.0), 6.0, -2.0), 7, "A", "right", sampled_fps=10, timing_s=0.03)
    assert result["uncertainty_m"] == round(math.sqrt(0.4 ** 2 + (2 * BODY_MARGIN_M) ** 2 + (0.03 * 8.0) ** 2), 2)


def test_review_picks_most_advanced_teammate_and_skips_passer():
    f = frame(83.0)
    f["players"] += [player(8, "A", 76.0), player(5, "A", 95.0), player(30, "A", 99.0, role="goalkeeper")]
    key, candidates = review(f, 5, "A")
    assert key["attacker_track_id"] == 7 and key["verdict"] == "offside"
    assert [c["track_id"] for c in candidates] == [7, 8, 9]
    assert candidates[1] == {"track_id": 8, "verdict": "onside", "margin_m": -4.0}


def test_review_without_team_or_teammates():
    assert review(frame(83.0), 7, None)[0]["verdict"] == "inconclusive"
    f = frame(83.0)
    f["players"] = [p for p in f["players"] if p["team"] != "A"]
    key, candidates = review(f, 7, "A")
    assert key["verdict"] == "inconclusive" and candidates == []


def test_review_bad_calibration_keeps_track_ids():
    key, candidates = review(frame(83.0, ok=False), 5, "A")
    assert key["verdict"] == "inconclusive"
    assert {c["track_id"] for c in candidates} == {7, 9}


def test_own_half_is_onside_even_beyond_defenders():
    f = frame(40.0, second_x=30.0, ball_x=20.0)
    result = assess(f, 7, "A", "right")
    assert result["verdict"] == "onside"
    assert any("halfway line" in r for r in result["reasons"])


def test_behind_ball_is_onside():
    result = assess(frame(83.0, ball_x=90.0), 7, "A", "right")
    assert result["verdict"] == "onside"
    assert any("ball" in r for r in result["reasons"])


def test_bad_calibration_widens_uncertainty():
    result = assess(frame(83.0, error=3.0), 7, "A", "right")
    assert result["verdict"] == "inconclusive"
    assert result["uncertainty_m"] > 3.0


def test_direction_left_mirrors_right():
    mirrored = frame(105 - 83.0, second_x=105 - 80.0, ball_x=105 - 60.0)
    for p in mirrored["players"]:
        if p["track_id"] in (4, 9, 1):
            p["x"] = 105 - p["x"]
    result = assess(mirrored, 7, "A")
    assert result["attack_direction"] == "left"
    assert result["verdict"] == "offside" and result["margin_m"] == 3.0
    assert any("goalkeeper" in r for r in result["reasons"])


def test_direction_inferred_from_defenders_without_keeper():
    result = assess(frame(65.0, keeper=False), 7, "A")
    assert result["attack_direction"] == "right" and result["verdict"] == "onside"
    assert any("heuristic" in r for r in result["reasons"])


def test_direction_not_inferable_is_inconclusive():
    f = frame(55.0, second_x=52.0, keeper=False)
    f["players"] = [p for p in f["players"] if p["track_id"] != 4] + [player(4, "B", 51.0)]
    result = assess(f, 7, "A")
    assert result["verdict"] == "inconclusive" and result["attack_direction"] is None


# --- the ball's height -----------------------------------------------------------------------------

def with_ball(f, **ball):
    f["ball"] = {"x": 81.0, "y": 30.0, **ball}  # between the second-last opponent (80) and the attacker (83): the ball sets the line
    return f


def test_ball_of_unknown_height_cannot_set_the_line():
    for ball in ({"airborne": None, "z": None}, {}):  # not fitted / predates height fitting
        result = assess(with_ball(frame(83.0), **ball), 7, "A", "right")
        assert result["verdict"] == "inconclusive"
        assert any("height is unknown" in r for r in result["reasons"])


def test_unknown_height_ball_does_not_hide_a_clearly_onside_attacker():
    result = assess(with_ball(frame(77.0), airborne=None, z=None), 7, "A", "right")
    assert result["verdict"] == "onside"


def test_airborne_ball_ground_point_error_widens_the_margin():
    f = with_ball(frame(83.0), airborne=True, z=2.0, height_uncertainty_m=1.5, ground_x=78.0, ground_y=30.0, position_uncertainty_m=0.2)
    result = assess(f, 7, "A", "right")
    assert result["verdict"] == "inconclusive"  # 2.0 m margin vs 2.25 m ball error (1.5 m of height x 1.5 m shift per metre)
    assert result["uncertainty_m"] > 2.2
    f["ball"]["height_uncertainty_m"] = 0.1
    assert assess(f, 7, "A", "right")["verdict"] == "offside"


def test_ball_on_the_grass_adds_only_its_detection_error():
    f = with_ball(frame(83.0), airborne=False, z=0.0, position_uncertainty_m=0.3)
    result = assess(f, 7, "A", "right")
    assert result["verdict"] == "offside"
    assert result["uncertainty_m"] == round(math.sqrt(0.4 ** 2 + (2 * BODY_MARGIN_M) ** 2 + 0.3 ** 2), 2)


# --- the moment the ball is played ----------------------------------------------------------------------

FPS = 10
KICK = 1.09  # between the samples at 1.0 and 1.1


def pass_frames(missing_ball_at=(1.1,)):
    """Passer 1 (A) stands at x=50 and kicks at KICK; the ball leaves at 20 m/s. Attacker 7 (A) runs at 8 m/s and is
    1.3 m beyond the second-last opponent (80) at the kick. The detector missed the ball on the sample after the kick."""
    frames = []
    for i in range(0, 20):
        t = round(i / FPS, 3)
        ball_x = 50.3 + max(0.0, t - KICK) * 20.0
        players = [{"track_id": 1, "team": "A", "role": "player", "x": 50.0, "y": 30.0, "vx": 0.0},
                   {"track_id": 7, "team": "A", "role": "player", "x": 81.3 + 8.0 * (t - KICK), "y": 20.0, "vx": 8.0},
                   {"track_id": 3, "team": "B", "role": "player", "x": 80.0, "y": 25.0, "vx": 0.0},
                   {"track_id": 4, "team": "B", "role": "player", "x": 70.0, "y": 25.0, "vx": 0.0}]
        ball = None if t in missing_ball_at else {"x": ball_x, "y": 30.0, "z": 0.0, "airborne": False, "height_model": "rolling", "position_uncertainty_m": 0.2}
        frames.append({"t": t, "shot": 0, "calibration": {"ok": True, "reprojection_error_m": 0.4, "source": "detected"}, "ball": ball, "players": players})
    return frames


EVENT = {"type": "pass", "t": 1.0, "shot": 0, "passer_track_id": 1, "team": "A", "receiver_track_id": 7, "receiver_team": "A"}


def test_kick_moment_is_found_from_the_ball_line_not_the_last_possession_sample():
    moment = kick_moment(pass_frames(), 1, 1.0, FPS)
    assert abs(moment["t"] - KICK) < 0.03 and moment["sigma_s"] <= 0.05
    assert moment["method"].startswith("ball line")


def test_kick_moment_falls_back_to_the_gap_when_the_ball_is_not_usable():
    frames = pass_frames()
    for f in frames:
        f["ball"] = None
    moment = kick_moment(frames, 1, 1.0, FPS)
    assert moment["t"] == 1.0 and moment["sigma_s"] == pytest.approx(0.1) and moment["method"].startswith("last sample")


def test_review_event_judges_the_kick_not_the_detector_sample():
    frames = pass_frames()
    sample = min(frames, key=lambda f: abs(f["t"] - EVENT["t"]))
    old_style, _ = review(sample, 1, "A", 105.0, FPS)  # what the detector's sample alone would give
    assert old_style["verdict"] == "inconclusive" and old_style["margin_m"] == pytest.approx(0.58, abs=0.01)
    key, _ = review_event(frames, EVENT, 105.0, FPS)
    assert key["verdict"] == "offside" and key["margin_m"] == pytest.approx(1.3, abs=0.2)
    assert key["receiver"]["verdict"] == "offside" and key["receiver"]["attacker_track_id"] == 7
    assert key["frame_t"] == pytest.approx(KICK, abs=0.03)


def test_frame_at_interpolates_players_and_keeps_the_worse_calibration():
    frames = pass_frames()
    frames[11]["calibration"]["reprojection_error_m"] = 0.9
    scene = frame_at(frames, 1.05)
    attacker = next(p for p in scene["players"] if p["track_id"] == 7)
    assert attacker["x"] == pytest.approx(81.3 + 8.0 * (1.05 - KICK))
    assert scene["calibration"]["reprojection_error_m"] == 0.9
    frames[11]["calibration"]["ok"] = False
    fallback = frame_at(frames, 1.05)  # an uncalibrated neighbour: the nearest sample as it is, no interpolation
    assert fallback["t"] in (1.0, 1.1) and next(p for p in fallback["players"] if p["track_id"] == 7)["x"] in (frames[10]["players"][1]["x"], frames[11]["players"][1]["x"])


# --- feasibility -------------------------------------------------------------------------------------

def test_feasibility_reports_what_the_review_had():
    key, _ = review_event(pass_frames(), EVENT, 105.0, FPS)
    f = key["feasibility"]
    assert f["available"] and f["blockers"] == [] and f["calibrated"]
    assert f["goalkeeper"] == "assumed" and any("goalkeeper" in w for w in f["warnings"])
    assert f["tracked_players"] == 4 and f["tracked_opponents"] == 2 and f["calibrated_frames"] == [20, 20]
    assert f["ball_contact_moment"]["found"] is True


def test_feasibility_names_each_blocker():
    frames = pass_frames()
    for f in frames:
        f["calibration"] = {"ok": False, "reprojection_error_m": None, "source": None}
        f["ball"] = None
    key, _ = review_event(frames, EVENT, 105.0, FPS)
    f = key["feasibility"]
    assert not f["available"] and key["verdict"] == "inconclusive"
    assert "no calibrated wide view of this moment" in f["blockers"] and "ball not located" in f["blockers"]
    assert f["calibrated_frames"] == [0, 20] and f["ball_contact_moment"]["found"] is False


def test_feasibility_keeper_located():
    frames = pass_frames()
    for f in frames:
        f["players"].append({"track_id": 1, "team": "B", "role": "goalkeeper", "x": 100.0, "y": 30.0})
        f["players"][-1]["track_id"] = 99
    key, _ = review_event(frames, EVENT, 105.0, FPS)
    assert key["feasibility"]["goalkeeper"] == "located" and key["feasibility"]["attack_direction_source"] == "defending goalkeeper seen in this shot"


# --- opponents outside the picture ------------------------------------------------------------------------

def looking_right(f, edge_x):
    """Camera whose image border cuts the pitch (at any y) at pitch x = edge_x: u = 10 * (x - edge_x + 128) maps edge_x to 1280."""
    f["calibration"]["homography"] = [[10.0, 0, 10.0 * (128 - edge_x)], [0, 10.0, 0], [0, 0, 1.0]]
    return f


def test_offside_needs_the_picture_to_reach_past_the_second_last_opponent():
    wide, cut = looking_right(frame(83.0, keeper=False), 95.0), looking_right(frame(83.0, keeper=False), 82.0)
    ok = assess(wide, 7, "A", "right", view=(1280, 720))
    assert ok["verdict"] == "offside" and ok["view_room_m"] == pytest.approx(15.0)
    cut_result = assess(cut, 7, "A", "right", view=(1280, 720))
    assert cut_result["verdict"] == "inconclusive" and cut_result["view_room_m"] == pytest.approx(2.0)
    assert any("outside the view" in r for r in cut_result["reasons"])


def test_cut_off_view_does_not_block_an_onside_call():
    assert assess(looking_right(frame(77.0, keeper=False), 82.0), 7, "A", "right", view=(1280, 720))["verdict"] == "onside"
    assert assess(frame(83.0, keeper=False), 7, "A", "right")["view_room_m"] is None  # no image size / homography: not checked


def test_call_reversed_by_the_next_sample_is_not_decisive():
    frames = pass_frames()
    for f in frames:
        if f["t"] >= 1.1:  # a deep opponent seen at the kick and lost on the next sample moves the line 15 m
            continue
        f["players"].append({"track_id": 5, "team": "B", "role": "player", "x": 96.0, "y": 25.0, "vx": 0.0})
    key, _ = review_event(frames, EVENT, 105.0, FPS)
    assert key["verdict"] == "inconclusive" and {n["verdict"] for n in key["timing_check"]} >= {"offside"}
    assert any("reverses" in r for r in key["reasons"])
    assert review_event(pass_frames(), EVENT, 105.0, FPS)[0]["verdict"] == "offside"  # stable scene stays decisive

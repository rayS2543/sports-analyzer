import math

import pytest

from var_offside import BODY_MARGIN_M, assess, review


def player(track, team, x, role="player", y=30.0):
    return {"track_id": track, "team": team, "role": role, "x": x, "y": y}


def frame(attacker_x, second_x=80.0, keeper=True, ball_x=60.0, error=0.4, ok=True):
    players = [player(7, "A", attacker_x), player(3, "B", second_x), player(4, "B", 70.0), player(9, "A", 50.0),
               {"track_id": 20, "team": None, "role": "referee", "x": 99.0, "y": 10.0}]
    if keeper:
        players.append(player(1, "B", 100.0, role="goalkeeper"))
    return {"t": 1.0, "calibration": {"ok": ok, "reprojection_error_m": error},
            "ball": None if ball_x is None else {"x": ball_x, "y": 30.0}, "players": players}


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
def test_timing_skipped_without_velocities(attacker_vx, defender_vx):
    result = assess(with_speeds(frame(83.0), attacker_vx, defender_vx), 7, "A", "right", sampled_fps=10)
    assert result["uncertainty_m"] == round(U, 2)
    assert any("not included" in r for r in result["reasons"])


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

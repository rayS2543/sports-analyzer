"""Cuts that decide whether two detections are one player and which kit they wear.

A crowded crop is down-weighted in the team vote. A vote under 70% leaves the
player unlabelled, so they cannot be an opponent in a foul. Two same-team
detections under half a metre apart are one person; the head-count cap then
drops the surplus.
"""

import math

from var_cv import teams


def person(tid, team, x, y=0.0, confidence=0.9, team_score=None, role="player"):
    return {"track_id": tid, "role": role, "team": team, "x": x, "y": y,
            "confidence": confidence, "team_score": confidence if team_score is None else team_score}


def test_overlap_of_exactly_thirty_percent_is_not_a_crowded_crop():
    # 10x10 boxes. A 3 px overlap is 30% of the smaller box; the cut is strict.
    clear = [[0, 0, 10, 10], [7, 0, 17, 10]]
    crowded = [[0, 0, 10, 10], [6.9, 0, 16.9, 10], [100, 0, 110, 10]]
    assert teams.crowded(clear) == [False, False]
    assert teams.crowded(crowded) == [True, True, False]


def test_a_team_needs_seventy_percent_of_the_vote():
    assert teams.decisive({"A": 70, "B": 30}) == ("A", 0.7)
    assert teams.decisive({"A": 699, "B": 301}) == (None, 0.699)
    assert teams.decisive({"A": 5, "B": 5}) == (None, 0.5)
    assert teams.decisive({"B": 0.7, "A": 0.3}) == ("B", 0.7)


def test_same_team_players_half_a_metre_apart_are_both_kept():
    # 3-4-5: exactly half a metre, which is not yet one person.
    kept = teams.cap_per_frame([
        person(1, "A", 0.0, 0.0, confidence=0.9),
        person(2, "A", 0.3, 0.4, confidence=0.4),
    ])
    assert {p["track_id"] for p in kept} == {1, 2}

    inside = math.nextafter(0.5, 0.0)
    kept = teams.cap_per_frame([
        person(1, "A", 0.0, confidence=0.9),
        person(2, "A", inside, confidence=0.4),
        person(3, "A", None, confidence=0.95),  # no pitch position: not a duplicate of anyone
    ])
    assert {p["track_id"] for p in kept} == {1, 3}
    assert kept[0]["team"] == "A" and kept[1]["team"] == "A"

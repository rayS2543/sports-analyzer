"""Which pairs are even sent to the pose model.

The foul review only examines MAX_CANDIDATES pairs. A looser distance admits crossing
players and crowds out the real challenge; a tighter one drops a challenge that is
exactly at the contact distance. Team labels are a per-shot majority, so one flickered
frame must not invent or erase an opponent.
"""

import math

from var_cv import fouls


def frame(t, players, shot=0):
    return {"t": t, "shot": shot, "calibration": {"ok": True}, "players": players}


def player(tid, team, x, role="player"):
    return {"track_id": tid, "team": team, "role": role, "x": x, "y": 0.0, "bbox": [0, 0, 10, 40]}


def pairs(frames):
    cands, total = fouls.find_candidates({"frames": frames})
    return cands, total, {(c["shot"], tuple(c["track_ids"])) for c in cands}


def test_contact_distance_includes_the_boundary_and_nothing_past_it():
    on = fouls.CONTACT_M
    past = math.nextafter(on, math.inf)
    _, total_on, got_on = pairs([frame(1.0, [player(1, "A", 0.0), player(2, "B", on)])])
    _, total_past, got_past = pairs([frame(1.0, [player(1, "A", 0.0), player(2, "B", past)])])
    assert total_on == 1 and got_on == {(0, (1, 2))}
    assert total_past == 0 and got_past == set()


def test_only_the_six_closest_pairs_are_examined():
    # Seven opponents, the furthest standing exactly on the contact distance.
    players = [player(1, "A", 0.0)]
    for i, x in enumerate((0.2, 0.4, 0.6, 0.8, 1.0, 1.1, fouls.CONTACT_M), start=2):
        players.append(player(i, "B", x))
    cands, total = fouls.find_candidates({"frames": [frame(1.0, players)]})
    kept = {tuple(c["track_ids"]) for c in cands}
    assert total == 7 and len(cands) == fouls.MAX_CANDIDATES
    assert kept == {(1, i) for i in range(2, 8)}  # id 8, at 1.2 m, loses the slot
    assert cands[0]["track_ids"] == [1, 2]  # closest interaction is examined first


def test_a_goalkeeper_is_a_candidate_and_a_team_flicker_does_not_change_the_pair():
    keeper = player(2, "B", 0.5, role="goalkeeper")
    _, total, got = pairs([frame(1.0, [player(1, "A", 0.0), keeper])])
    assert total == 1 and got == {(0, (1, 2))}

    # Three frames say these two are teammates; one frame labels the second as an opponent.
    same = [frame(i * 0.1, [player(1, "A", 0.0), player(2, team, 0.5)]) for i, team in enumerate(["A", "A", "A", "B"])]
    assert pairs(same)[1] == 0
    # The opposite flicker still leaves them opponents, on every frame of the run.
    opposed = [frame(i * 0.1, [player(1, "A", 0.0), player(2, team, 0.5)]) for i, team in enumerate(["B", "B", "B", "A"])]
    cands, total, got = pairs(opposed)
    assert total == 1 and got == {(0, (1, 2))} and cands[0]["hits"] == 4


def test_team_votes_do_not_cross_shots():
    # The same track ids in the next shot are different people. Shot 0 is a real pair;
    # shot 1 is two players of team B and must not inherit shot 0's vote.
    frames = [
        frame(1.0, [player(1, "A", 0.0), player(2, "B", 0.4)], shot=0),
        frame(5.0, [player(1, "B", 0.0), player(2, "B", 0.4)], shot=1),
    ]
    _, total, got = pairs(frames)
    assert total == 1 and got == {(0, (1, 2))}

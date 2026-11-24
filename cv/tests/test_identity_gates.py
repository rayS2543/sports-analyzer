"""Gates that decide which box is a player and which tracklets are the same person.

Offside and foul review trust these ids. A relaxed gate merges two players; a tight
one splits one player across the moment that is judged.
"""

import numpy as np
import pytest

from var_cv import analyze, pitch, reid, track


def appearance(bin_index):
    app = np.zeros((4, 24))
    app[:, bin_index] = 1.0
    return app


SAME = appearance(0)
OTHER = appearance(1)


def test_a_fragment_inside_a_more_confident_box_is_not_a_second_player():
    person = np.array([0, 0, 100, 100], float)
    # 70 of this box's 100 px sit inside the person; 68 do not meet the cut.
    on_frac = np.array([93, 0, 103, 10], float)
    under = np.array([93.2, 0, 103.2, 10], float)
    assert analyze.contained(np.vstack([person, on_frac]), np.array([0.9, 0.4])).tolist() == [False, True]
    assert analyze.contained(np.vstack([person, under]), np.array([0.9, 0.4])).tolist() == [False, False]
    # The cut is strict about confidence too: a tie keeps both, and so does a fragment that is the surer box.
    assert analyze.contained(np.vstack([person, on_frac]), np.array([0.4, 0.4])).tolist() == [False, False]
    assert analyze.contained(np.vstack([person, on_frac]), np.array([0.2, 0.9])).tolist() == [False, False]
    touching = np.array([[0, 0, 10, 10], [10, 0, 20, 10]], float)
    assert not analyze.contained(touching, np.array([0.9, 0.2])).any()


def test_pitch_and_goal_mouth_boundaries_are_inclusive_on_the_inside_only():
    margin = analyze.OFF_PITCH_MARGIN_M
    assert analyze.on_pitch(-margin, 0)
    assert analyze.on_pitch(pitch.LENGTH + margin, pitch.WIDTH)
    assert not analyze.on_pitch(-margin - 0.01, pitch.WIDTH / 2)
    assert not analyze.on_pitch(pitch.LENGTH / 2, pitch.WIDTH + margin + 0.01)

    mid = pitch.WIDTH / 2
    assert analyze.near_goal(19.99, mid)
    assert not analyze.near_goal(20, mid)
    assert not analyze.near_goal(pitch.LENGTH - 20, mid)
    assert analyze.near_goal(pitch.LENGTH - 19.99, mid)
    assert analyze.near_goal(10, mid + 21.99)
    assert not analyze.near_goal(10, mid + 22)


def piece(tid, t0, t1, team="A", role="player", x0=10.0, y0=20.0, x1=10.0, y1=20.0, app=SAME):
    return {
        "tid": tid, "t0": t0, "t1": t1, "team": team, "role": role, "app": app, "players": [],
        "start": (t0, x0, y0, 0.0, 0.0), "end": (t1, x1, y1, 0.0, 0.0),
    }


def ids_of(chains):
    return [[t["tid"] for t in chain] for chain in chains]


def test_fragments_chain_only_for_the_same_person_inside_the_gate():
    # gap of 2.0s on the same spot is one person; 2.01s is a new one.
    linked = reid._chain([piece(1, 0.0, 1.0), piece(2, 3.0, 3.4)], sigma=0.3)
    assert ids_of(linked) == [[1, 2]]
    separate = reid._chain([piece(1, 0.0, 1.0), piece(2, 3.01, 3.4)], sigma=0.3)
    assert ids_of(separate) == [[1], [2]]

    # chi^2 9 is 3 * (1m + 2m/s * gap). At a 1s gap that is 9m, which still links; past it does not.
    on_gate = reid._chain([piece(1, 0.0, 1.0, x1=0.0), piece(2, 2.0, 2.4, x0=9.0)], sigma=0.3)
    past_gate = reid._chain([piece(1, 0.0, 1.0, x1=0.0), piece(2, 2.0, 2.4, x0=9.1)], sigma=0.3)
    assert ids_of(on_gate) == [[1, 2]]
    assert ids_of(past_gate) == [[1], [2]]

    assert ids_of(reid._chain([piece(1, 0.0, 1.0), piece(2, 1.4, 2.0, team="B")], sigma=0.3)) == [[1], [2]]
    assert ids_of(reid._chain([piece(1, 0.0, 1.0), piece(2, 1.4, 2.0, role="referee")], sigma=0.3)) == [[1], [2]]
    assert ids_of(reid._chain([
        piece(1, 0.0, 1.0, app=SAME), piece(2, 1.4, 2.0, app=OTHER),
    ], sigma=0.3)) == [[1], [2]]
    # A missing team does not block a chain; two referees may.
    assert ids_of(reid._chain([piece(1, 0.0, 1.0, team=None), piece(2, 1.4, 2.0)], sigma=0.3)) == [[1, 2]]
    assert ids_of(reid._chain([
        piece(1, 0.0, 1.0, role="referee"), piece(2, 1.4, 2.0, role="referee"),
    ], sigma=0.3)) == [[1, 2]]


def test_track_end_speed_is_a_sprint_cap_not_the_raw_fit():
    cal = [(0.0, {"x": 0.0, "y": 1.0}), (0.3, {"x": 6.0, "y": 1.0}), (0.6, {"x": 12.0, "y": 1.0})]
    t, x, y, vx, vy = reid._state(cal, first=False)
    assert (t, y) == (0.6, pytest.approx(1.0))
    assert x == pytest.approx(12.0)
    assert vx == pytest.approx(reid.MAX_RUN_MS) and vy == pytest.approx(0.0)

    # Two samples are not a velocity, so the player is not thrown forward.
    t, x, y, vx, vy = reid._state([(0.0, {"x": 0.0, "y": 0.0}), (0.5, {"x": 8.0, "y": 0.0})], first=False)
    assert (x, y, vx, vy) == (8.0, 0.0, 0.0, 0.0)

    t, x, y, vx, vy = reid._state([(1.0, {"x": 4.0, "y": 5.0, "vx": -40.0, "vy": 0.0})], first=True)
    assert (t, x, y) == (1.0, 4.0, 5.0)
    assert vx == pytest.approx(-reid.MAX_RUN_MS) and vy == pytest.approx(0.0)


def det(track_id, box, pos, conf, team):
    return {"id": track_id, "box": box, "pos": pos, "conf": conf, "team": team}


def test_duplicate_tracks_merge_at_the_overlap_fraction_and_not_across_teams():
    here, away = (0, 0, 20, 40), (200, 0, 220, 40)
    frames = []
    for k in range(5):
        same_spot = k < 3  # 3/5 == 0.6, the fraction that still counts as one person
        frames.append([
            det(1, here, (10.0, 20.0), 0.9, "A"),
            det(2, here if same_spot else away, (10.0, 20.0) if same_spot else (40.0, 20.0), 0.4, "A"),
        ])
    id_map, drop = track.merge_tracks(frames, [0.1 * k for k in range(5)])
    assert id_map[2] == 1
    assert {(k, 2) for k in range(5)} <= drop

    frames = []
    for k in range(5):
        same_spot = k < 2  # 2/5 is a crossing, not a duplicate
        frames.append([
            det(1, here, (10.0, 20.0), 0.9, "A"),
            det(2, here if same_spot else away, (10.0, 20.0) if same_spot else (40.0, 20.0), 0.4, "A"),
        ])
    id_map, drop = track.merge_tracks(frames, [0.1 * k for k in range(5)])
    assert id_map[1] == 1 and id_map[2] == 2 and drop == set()

    frames = [ [det(1, here, (10.0, 20.0), 0.9, "A"), det(2, here, (10.1, 20.0), 0.8, "B")] for _ in range(4)]
    id_map, drop = track.merge_tracks(frames, [0.1 * k for k in range(4)])
    assert id_map[2] == 2 and drop == set()


def test_a_fragment_continues_a_runner_only_inside_the_jump_and_speed_limits():
    def pair(pos, dt):
        frames = [
            [det(1, (0, 0, 10, 40), (0.0, 0.0), 0.9, "A")],
            [det(2, (0, 0, 10, 40), pos, 0.8, "A")],
        ]
        id_map, _ = track.merge_tracks(frames, [0.0, dt])
        return id_map[2]

    assert pair((2.9, 0.0), 1.0) == 1  # under 3 m and under 8 m/s
    assert pair((3.0, 0.0), 1.0) == 2  # 3 m is a different player
    assert pair((2.5, 0.0), 0.2) == 2  # 12.5 m/s is not a continuation
    frames = [
        [det(1, (0, 0, 10, 40), (10.0, 20.0), 0.9, "A")],
        [det(2, (0, 0, 10, 40), None, 0.9, "A")],
    ]
    id_map, _ = track.merge_tracks(frames, [0.0, 0.2])
    assert id_map[2] == 2  # no pitch position, so time alone does not glue them

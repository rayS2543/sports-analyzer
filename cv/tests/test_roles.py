"""Who is allowed onto the pitch: officials, goalkeepers, nested boxes, and the 5 m margin.

An official labelled as an outfielder, or a player kept past the touchline, moves the offside line.
"""

from types import SimpleNamespace

import numpy as np

from var_cv import analyze, teams


class Kit:  # two kits as 2-d signatures; a feature is (signature, display colour)
    model = teams.TeamModel([[1, 0], [0, 1]], 0.3, [[255] * 3, [0] * 3])


def feat(a):
    return (np.array([float(a), 1.0 - float(a)]), np.zeros(3))


ODD = (np.array([-3.0, -3.0]), np.zeros(3))  # far from both kit centres


def frame(people):
    boxes, cls, feats, pairs = [], [], [], []
    for i, p in enumerate(people):
        x, y = p["x"], p["y"]
        boxes.append([x - 4, y - 30, x + 4, y])  # foot at the bottom centre, which is the pitch point
        cls.append(p.get("cls", 2))
        feats.append(p["feat"])
        pairs.append((i, p["tid"]))
    rec = {
        "cal": {"ok": True, "H": np.eye(3)},
        "people": SimpleNamespace(xyxy=np.array(boxes, float), class_id=np.array(cls, int)),
        "feats": feats,
    }
    return rec, pairs


def tracks(frames_people):
    recs, tracked = [], []
    for people in frames_people:
        rec, pairs = frame(people)
        recs.append(rec)
        tracked.append(pairs)
    return analyze.assign_tracks(recs, tracked, Kit.model)


def role_at(x, y, n=4):
    person = [{"tid": 1, "x": x, "y": y, "feat": ODD}]
    role, team, _ = tracks([person] * n)
    return role[1], team[1]


def test_an_odd_kit_near_a_goal_is_the_keeper_and_the_same_kit_elsewhere_is_an_official():
    assert role_at(10.0, 34.0) == ("goalkeeper", None)
    assert role_at(52.5, 34.0) == ("referee", None)
    # 20 m from a goal line, and 22 m off the goal's centre, are outside the goal mouth
    assert role_at(20.0, 34.0)[0] == "referee"
    assert role_at(19.9, 34.0)[0] == "goalkeeper"
    assert role_at(85.0, 34.0)[0] == "referee"  # length 105, so the far 20 m starts past 85
    assert role_at(85.1, 34.0)[0] == "goalkeeper"
    assert role_at(10.0, 56.0)[0] == "referee"
    assert role_at(10.0, 55.9)[0] == "goalkeeper"
    # three crops is too few to call anyone an official, even in the goal
    assert role_at(10.0, 34.0, n=3) == ("player", None)


def test_a_kit_must_read_odd_on_more_than_seven_in_ten_crops_to_leave_the_outfield():
    def crops(n_odd, n_kit):
        frames = [[{"tid": 1, "x": 10.0, "y": 34.0, "feat": ODD if i < n_odd else feat(1)}]
                  for i in range(n_odd + n_kit)]
        return tracks(frames)

    role, team, _ = crops(7, 3)  # exactly 70%: the kit-A crops still vote
    assert role[1] == "player" and team[1] == "A"
    role, team, _ = crops(8, 2)  # the one kit-A reading does not make a keeper an outfielder
    assert role[1] == "goalkeeper" and team[1] is None


def test_a_keeper_takes_the_nearer_team_block_and_does_not_guess_from_one_team():
    def side(x0, tid0, kit):
        return [{"tid": tid0 + i, "x": x0 + 2 * i, "y": 40.0, "feat": feat(kit)} for i in range(3)]

    def with_keeper(x, both_sides=True):
        people = side(30.0, 10, 1.0) + (side(70.0, 20, 0.0) if both_sides else side(70.0, 20, 0.0)[:2])
        people.append({"tid": 1, "x": x, "y": 34.0, "cls": 1, "feat": ODD})
        return tracks([people])

    role, team, _ = with_keeper(8.0)
    assert role[1] == "goalkeeper" and team[1] == "A" and team[10] == "A" and team[20] == "B"
    _, team, _ = with_keeper(96.0)
    assert team[1] == "B"
    role, team, _ = with_keeper(8.0, both_sides=False)
    assert role[1] == "goalkeeper" and team[1] is None


def test_a_majority_of_referee_detections_drops_the_kit_vote():
    frames = [[{"tid": 1, "x": 40.0, "y": 34.0, "cls": cls, "feat": feat(1)}] for cls in (3, 3, 3, 2)]
    role, team, _ = tracks(frames)
    assert role[1] == "referee" and team[1] is None


def _scene(feet, H, ok, confidence=None):
    boxes = [[x - 4, y - 30, x + 4, y] for x, y in feet]
    n = len(feet)
    return {
        "t": 1.2,
        "cal": {
            "ok": ok, "H": H, "source": "detected" if ok else None, "keypoints": 4, "support": 0.8,
            "loo_m": 0.2, "failure": None if ok else "no lines", "error_m": 0.3,
            "sigma": lambda pts: np.array([0.4]), "masks_region": np.zeros((4, 4), np.uint8),
        },
        "masks": (np.zeros((4, 4), np.uint8),),
        "ball": None,
        "people": SimpleNamespace(
            xyxy=np.array(boxes, float),
            confidence=np.array(confidence if confidence is not None else [0.8] * n),
        ),
    }


def written(feet, roles=None, teams_=None, H=None, ok=True):
    H = np.eye(3) if H is None else H
    n = len(feet)
    roles = {i + 1: "player" for i in range(n)} | (roles or {})
    teams_ = {i + 1: "A" for i in range(n)} | (teams_ or {})
    scores = {i + 1: 1.0 for i in range(n)}
    out = analyze.frame_json(_scene(feet, H, ok), 0, [(i, i + 1) for i in range(n)], roles, teams_, scores)
    return [(p["track_id"], p["team"], p["x"], p["y"]) for p in out["players"]]


def test_the_pitch_margin_keeps_a_player_on_the_line_and_drops_the_one_past_it():
    # 5 m outside the 105 x 68 pitch is still on it; the next centimetre is not
    assert written([(-5.0, 34.0), (-5.01, 34.0), (52.5, 73.0), (52.5, 73.01)]) == [
        (1, "A", -5.0, 34.0), (3, "A", 52.5, 73.0)]


def test_a_referee_is_stored_without_a_team_and_a_point_behind_the_camera_is_not_a_player():
    assert written([(40.0, 34.0)], {1: "referee"}, {1: "A"}) == [(1, None, 40.0, 34.0)]
    assert written([(40.0, 34.0)], H=np.diag([1.0, 1.0, -1.0])) == []
    # no calibration: the box is kept, still with no team on a referee, and no invented pitch point
    assert written([(200.0, 200.0), (40.0, 34.0)], {1: "referee"}, {1: "A", 2: "B"}, H=None, ok=False) == [
        (1, None, None, None), (2, "B", None, None)]


def test_a_weak_detection_inside_a_stronger_box_is_the_same_person():
    small = [0.0, 0.0, 10.0, 10.0]
    cover = [0.0, 0.0, 7.0, 10.0]    # 70% of the small box
    short = [0.0, 0.0, 6.9, 10.0]    # 69%
    assert analyze.contained(np.array([small, cover]), np.array([0.4, 0.9])).tolist() == [True, False]
    assert analyze.contained(np.array([small, short]), np.array([0.4, 0.9])).tolist() == [False, False]
    # a confident player inside a weaker box stays; a tie discards neither
    large = [0.0, 0.0, 100.0, 100.0]
    assert analyze.contained(np.array([small, large]), np.array([0.9, 0.4])).tolist() == [False, False]
    assert analyze.contained(np.array([small, large]), np.array([0.8, 0.8])).tolist() == [False, False]

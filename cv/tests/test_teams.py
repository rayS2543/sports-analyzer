"""Team labels from shirt crops: crowded boxes count less and indecisive tracks get no team."""

from types import SimpleNamespace

import numpy as np

from var_cv import analyze, teams


class Kit:  # two kits as 2-d signatures; a feature is (signature, display colour)
    model = teams.TeamModel([[1, 0], [0, 1]], 0.3, [[255] * 3, [0] * 3])


def feat(a):  # a = how much the crop looks like kit A
    return (np.array([a, 1 - a]), np.zeros(3))


def test_crowded_marks_boxes_that_overlap_another_person():
    far = [[0, 0, 10, 30], [100, 0, 110, 30]]
    assert teams.crowded(far) == [False, False]
    assert teams.crowded([[0, 0, 10, 30], [4, 0, 14, 30], [100, 0, 110, 30]]) == [True, True, False]


def test_decisive_needs_the_share_and_otherwise_gives_no_team():
    assert teams.decisive({"A": 8.0, "B": 2.0}) == ("A", 0.8)
    assert teams.decisive({"A": 5.0, "B": 4.0})[0] is None
    assert teams.decisive({}) == (None, 0.0)


def test_assign_tracks_gives_a_split_vote_no_team_and_discounts_crowded_crops():
    # track 1: clean A. track 2: clean B. track 3 stands behind track 4 for 6 frames (its crop reads 4's kit, B)
    # and is clear for 2 (reads A): 2.0 A against 1.5 B is not decisive. track 4: B throughout, crowded.
    far, a, b = [300, 0, 310, 30], [0, 0, 10, 30], [4, 0, 14, 30]
    recs, tracked = [], []
    for k in range(8):
        hidden = k < 6
        boxes = [far, [200, 0, 210, 30], a] + ([b] if hidden else [])
        feats = [feat(1.0), feat(0.0), feat(0.0 if hidden else 1.0)] + ([feat(0.0)] if hidden else [])
        recs.append({"cal": {"ok": False, "H": None}, "people": SimpleNamespace(xyxy=np.array(boxes, float), class_id=np.full(len(boxes), 2)),
                     "feats": feats})
        tracked.append([(i, i + 1) for i in range(len(boxes))])
    role, team, score = analyze.assign_tracks(recs, tracked, Kit.model)
    assert team[1] == "A" and team[2] == "B" and team[4] == "B"
    assert team[3] is None and 0.5 < score[3] < teams.KIT_SHARE


def test_a_track_whose_crops_are_all_odd_kit_has_no_team_even_when_short():
    # an official seen for 2 frames is too short to be called a referee, but its (blue-ish) shirt must not
    # make it a team-B player: shirts far from both kits do not vote
    recs = [{"cal": {"ok": False, "H": None}, "people": SimpleNamespace(xyxy=np.array([[0, 0, 10, 30], [200, 0, 210, 30]], float),
                                                                         class_id=np.full(2, 2)),
             "feats": [feat(1.0), (np.array([-3.0, -3.0]), np.zeros(3))]} for _ in range(2)]
    role, team, _ = analyze.assign_tracks(recs, [[(0, 1), (1, 2)]] * 2, Kit.model)
    assert team[1] == "A" and team[2] is None

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


def sig(*v):
    return np.array(v, float)


def test_kit_outliers_finds_a_keeper_whose_shirt_is_far_from_his_teams():
    mint = {t: [sig(0.9, 0.1, 0.0)] * 14 for t in range(1, 9)}  # eight outfielders in one kit
    black = {9: [sig(0.0, 0.2, 1.0)] * 14}
    team = {t: "A" for t in range(1, 10)}
    assert teams.kit_outliers({**mint, **black}, team) == {9}
    assert teams.kit_outliers(mint, team) == set()  # a team in one kit has no outlier
    assert teams.kit_outliers({**mint, **black}, {**team, 9: None}) == set()  # a track with no team is not compared


def test_kit_outliers_leaves_a_team_with_two_shades_alone():
    light = {t: [sig(0.9, 0.1, 0.0)] * 14 for t in range(1, 5)}
    shaded = {t: [sig(0.8, 0.2, 0.1)] * 14 for t in range(5, 9)}  # the same kit in shadow
    assert teams.kit_outliers({**light, **shaded}, {t: "A" for t in range(1, 9)}) == set()


def test_assign_tracks_makes_the_odd_shirt_by_the_goal_a_keeper_and_elsewhere_teamless(monkeypatch):
    def run(goal_x):
        boxes = [[i * 12, 0, i * 12 + 10, 30] for i in range(9)]
        feats = [feat(1.0)] * 8 + [(np.array([0.2, 0.2]), np.zeros(3))]  # eight in kit A, one in a shirt between the kits
        recs = [{"cal": {"ok": True, "H": np.eye(3)}, "people": SimpleNamespace(xyxy=np.array(boxes, float), class_id=np.full(9, 2)), "feats": feats}
                for _ in range(14)]
        tracked = [[(i, i + 1) for i in range(9)]] * 14
        monkeypatch.setattr(analyze, "to_pitch", lambda H, uv, _x=goal_x: (_x if uv[0] > 100 else 50.0, 34.0))
        return analyze.assign_tracks(recs, tracked, Kit.model)
    role, team, _ = run(3.0)
    assert role[9] == "goalkeeper" and all(role[t] == "player" for t in range(1, 9))
    role, team, _ = run(50.0)
    assert role[9] == "player" and team[9] is None and team[1] == "A"


def test_kit_outliers_ignores_short_fragments_and_several_odd_tracks():
    mint = {t: [sig(0.9, 0.1, 0.0)] * 14 for t in range(1, 9)}
    team = {t: "A" for t in range(1, 12)}
    fragment = {9: [sig(0.0, 0.2, 1.0)] * 5}  # a black shirt seen for five crops: a blurred player or a half-hidden one, not a keeper
    assert teams.kit_outliers({**mint, **fragment}, team) == set()
    two_odd = {9: [sig(0.0, 0.2, 1.0)] * 14, 10: [sig(0.0, 0.3, 0.9)] * 14}  # two odd shirts: no single exception
    assert teams.kit_outliers({**mint, **two_odd}, team) == set()

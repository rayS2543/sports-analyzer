"""Pure-geometry checks for var_cv.fouls on synthetic data (no weights, no video)."""

import math

import numpy as np
import pytest

from var_cv import fouls

W, H = 1280, 720


def look_at_camera(C, target, f=1400.0):
    """Pitch->image P (3x4) for a camera at C looking at target; pitch z points down (left-handed pitch frame)."""
    C, target = np.asarray(C, float), np.asarray(target, float)
    fwd = (target - C) / np.linalg.norm(target - C)
    down = np.array([0, 0, 1.0])  # +z is into the grass in this pitch frame
    right = np.cross(down, fwd)
    right /= np.linalg.norm(right)
    dn = np.cross(fwd, right)
    R = np.stack([right, dn, fwd])
    t = -R @ C
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
    return K @ np.c_[R, t]


@pytest.fixture
def broadcast():
    # camera 18 m up (z = -18) behind the near touchline (y = 68 + 30), looking at the centre spot
    P = look_at_camera([52.5, 98.0, -18.0], [52.5, 34.0, 0.0])
    return P, P[:, [0, 1, 3]]


def test_camera_from_homography_recovers_heights(broadcast):
    P, G = broadcast
    cam = fouls.camera_from_homography(G, W, H)
    assert cam is not None
    assert abs(cam["f"] - 1400) < 1
    assert abs(abs(cam["C"][2]) - 18) < 0.05
    for X, Y, h in [(52.5, 34, 0.5), (40, 20, 1.2), (70, 50, 0.08)]:
        p = P @ np.array([X, Y, -h, 1.0])
        uv = p[:2] / p[2]
        assert abs(fouls.height_above_ground(cam, uv, X, Y) - h) < 1e-3
    assert fouls.height_above_ground(cam, fouls.project(G, (30, 30)), 30, 30) == pytest.approx(0, abs=1e-6)
    # depression-angle factor: 18 m up, ~64 m away -> tan ~ 0.28
    assert fouls.ray_tan(cam, 52.5, 34) == pytest.approx(18 / 64, rel=1e-3)


def test_grass_stays_at_zero_height_for_a_noisy_homography(broadcast):
    # A real (fitted) homography is not exactly K[r1 r2 t]: points on the grass must still come out at 0 m.
    _, G = broadcast
    noisy = G @ np.array([[1.01, 0.004, 0.3], [-0.003, 0.99, -0.2], [0, 0, 1.0]])
    cam = fouls.camera_from_homography(noisy, W, H)
    for X, Y in [(30, 20), (70, 55), (52.5, 34)]:
        assert fouls.height_above_ground(cam, fouls.project(noisy, (X, Y)), X, Y) == pytest.approx(0, abs=1e-6)


def test_camera_from_degenerate_homography_is_none():
    assert fouls.camera_from_homography(np.eye(3), W, H) is None


def kps(points, conf=0.9):
    k = np.zeros((17, 3))
    for name, (x, y) in points.items():
        k[fouls.K[name]] = (x, y, conf)
    return k


# An upright body 180 px tall, feet at y=400, centred at x.
def standing(x):
    return kps({"nose": (x, 228), "leye": (x - 3, 225), "reye": (x + 3, 225), "lear": (x - 6, 228), "rear": (x + 6, 228),
                "lsho": (x - 20, 250), "rsho": (x + 20, 250), "lelb": (x - 25, 290), "relb": (x + 25, 290),
                "lwri": (x - 27, 320), "rwri": (x + 27, 320), "lhip": (x - 12, 320), "rhip": (x + 12, 320),
                "lkne": (x - 12, 360), "rkne": (x + 12, 360), "lank": (x - 12, 395), "rank": (x + 12, 395)})


def test_contact_on_shin_above_ankle():
    victim = standing(500)
    challenger = standing(560)
    challenger[fouls.K["rank"], :2] = (512 + 2, 370)  # right foot planted into the victim's right shin
    c = fouls.nearest_contact(challenger, victim, 180)
    assert c["striker"] == "rank" and c["part"] == "shin" and c["d"] < fouls.TOUCH
    assert fouls.above_ankle(c["part"], c["s"], c["seg"])
    assert 0.2 < fouls.skeleton_height(victim, *c["seg"], c["s"]) < 0.4


def test_contact_at_ankle_is_not_above_ankle():
    assert not fouls.above_ankle("shin", 0.95, ("rkne", "rank"))
    assert fouls.above_ankle("shin", 0.5, ("rkne", "rank"))
    assert not fouls.above_ankle("foot/ankle", 0.0, ("rank", "rank"))
    assert fouls.above_ankle("thigh", 0.9, ("rhip", "rkne"))


def test_contact_frame_is_the_onset_not_the_later_tangle():
    victim = standing(500)
    apart = standing(620)
    touch = standing(560)
    touch[fouls.K["rank"], :2] = (514, 370)  # foot into the shin
    tangle = standing(505)  # later: bodies overlapping completely (distance 0 everywhere)
    rec = lambda t, c: {"t": t, "kps": [c, victim], "boxes": [[0, 220, 1, 400], [0, 220, 1, 400]]}
    r, j, c = fouls._onset([rec(1.0, apart), rec(1.1, touch), rec(1.2, tangle)])
    assert r["t"] == 1.1 and j == 0 and c["striker"] == "rank"
    r, _, c = fouls._onset([rec(1.0, apart)])  # never touching: the closest approach, reported as such
    assert r["t"] == 1.0 and c["d"] > fouls.TOUCH


def test_lunge_needs_two_frames_and_rejects_impossible_heights():
    victim = standing(500)
    def jump(lift_px):
        k = standing(560)
        k[[fouls.K["lank"], fouls.K["rank"]], 1] -= lift_px
        return {"t": 1.0, "kps": [k, victim], "boxes": [[540, 220, 580, 400], [480, 220, 520, 400]], "G": None}
    track = [(1.0, {"x": None, "y": None}, None)]
    two = fouls._airborne([jump(0), jump(40), jump(45)], 0, 1, track, (1280, 720))  # 40 px of 175 px ~ 0.4 m
    assert two["value"] is True and 0.3 < two["lift_m"] < 0.5
    one = fouls._airborne([jump(0), jump(40)], 0, 1, track, (1280, 720))
    assert one["value"] is False
    silly = fouls._airborne([jump(150), jump(160)], 0, 1, track, (1280, 720))  # ankles 1.5 m up: pose error
    assert not silly["observable"] and "implausible" in silly["detail"]


def test_hidden_keypoints_are_not_used():
    victim = standing(500)
    victim[:, 2] = 0.1
    assert fouls.nearest_contact(standing(520), victim, 180) is None


def test_sole_facing_from_heel_and_toe():
    # shin horizontal (knee left, ankle at the origin), foot dorsiflexed: heel below, toe above -> sole faces right
    ankle, heel, toe = np.array([0.0, 0.0]), np.array([4.0, 8.0]), np.array([6.0, -18.0])
    assert fouls.sole_facing(ankle, heel, toe, (60, 0)) > 0.9       # studs straight at a target on the right
    assert fouls.sole_facing(ankle, heel, toe, (-60, 0)) < -0.9     # the target is behind the foot
    # standing foot: heel and toe on the grass below the ankle -> sole faces down, not at a player beside it
    assert abs(fouls.sole_facing(ankle, (-5, 10), (20, 10), (60, 0))) < 0.3
    assert fouls.sole_facing(ankle, (5, 5), (5, 5), (60, 0)) is None


def test_localisation_quality_uses_measured_error():
    q_small, err = fouls.loc_quality(60)  # far camera, error unknown: 3 px on a 60 px body = 9 cm
    assert err == pytest.approx(0.09) and q_small == pytest.approx(0.55)
    q_agree, _ = fouls.loc_quality(60, 0.5)  # two models agree to 0.5 px: floored at 1.5 px
    assert q_agree == pytest.approx(1 - 1.5 / 60 * 1.8 / 0.2)
    assert fouls.loc_quality(60, 10)[0] == 0.0  # 10 px disagreement on a small player: worthless geometry
    assert fouls.loc_quality(400, None)[0] > 0.9


def test_opencv_threads_are_capped():
    import cv2
    assert cv2.getNumThreads() == 1  # GCD backend: 0 is the only effective cap (see fouls.py)
    cap = fouls.open_video(__file__)  # not a video: must still build without raising
    assert not cap.isOpened()


def test_knee_angle_straight_and_bent():
    k = standing(500)
    assert fouls.knee_angle(k, "l") > 170
    k[fouls.K["lank"], :2] = (500 - 12 + 35, 360)  # shin swung forward horizontally
    assert fouls.knee_angle(k, "l") < 100


def frame(t, players, ok=True, shot=0, ball=None):
    return {"t": t, "shot": shot, "calibration": {"ok": ok}, "ball": ball, "players": players}


def player(tid, team, x, y, bbox, role="player"):
    return {"track_id": tid, "team": team, "role": role, "x": x, "y": y, "bbox": bbox}


def test_candidates_merge_runs_and_exclude_team_mates_and_referees():
    frames = []
    for i in range(10):
        t = 10 + 0.1 * i
        near = 0.8 if 3 <= i <= 6 else 5.0
        frames.append(frame(t, [player(1, "A", 50, 30, [0, 0, 10, 50]), player(2, "B", 50 + near, 30, [100, 0, 110, 50]),
                                player(3, "A", 50.5, 30, [0, 0, 10, 50]),  # team-mate of 1: never a candidate with 1
                                player(4, None, 50.2, 30.2, [0, 0, 10, 50], role="referee")]))
    cands, total = fouls.find_candidates({"frames": frames})
    pairs = sorted(tuple(c["track_ids"]) for c in cands)
    assert (1, 3) not in pairs and all(4 not in p for p in pairs)
    c12 = next(c for c in cands if c["track_ids"] == [1, 2])
    assert (c12["t0"], c12["t1"], c12["hits"]) == (pytest.approx(10.3), pytest.approx(10.6), 4)


def test_uncalibrated_candidates_need_overlap_at_similar_depth():
    a = player(1, "A", None, None, [100, 100, 140, 200])
    same_depth = player(2, "B", None, None, [120, 105, 160, 205])
    far_behind = player(3, "B", None, None, [120, 60, 150, 130])  # overlapping box, feet 70 px higher = further away
    cands, _ = fouls.find_candidates({"frames": [frame(1.0, [a, same_depth, far_behind], ok=False)]})
    assert [c["track_ids"] for c in cands] == [[1, 2]]


def test_dogso_factors_count_defenders_in_corridor(broadcast):
    _, G = broadcast
    challenger = player(5, "B", 80, 34, None)
    victim = player(9, "A", 82, 34, None)
    f = frame(1.0, [challenger, victim,
                    player(6, "B", 95, 36, None),  # between attacker and goal
                    player(7, "B", 95, 5, None),   # wide: outside the corridor
                    player(8, "B", 104, 34, None, role="goalkeeper"),
                    player(10, "A", 90, 20, None)],
              ball={"x": 83, "y": 34.5, "confidence": 0.8, "airborne": False})
    out, tri = fouls.dogso_factors(f, G, (W, H), challenger, victim, (105.0, "keeper", 0.9), (6.0, 0.0))
    assert out["distance_to_goal"]["value"] == pytest.approx(23.0)
    assert out["direction_of_play"]["value"] == "towards_goal"
    assert out["control"]["value"] == pytest.approx(1.1)
    d = out["defenders_between"]
    assert d["value"] == 2 and d["outfield"] == 1 and d["goalkeepers"] == 1
    assert out["in_penalty_area"]["value"] is False
    assert out["attackers"]["value"] == 1


def test_dogso_not_observable_without_calibration():
    out, _ = fouls.dogso_factors(None, None, (W, H), None, None, (None, "", 0), None)
    assert all(not v["observable"] and v["value"] is None and v["confidence"] == 0 for v in out.values())


def test_interp_between_samples_and_gap_limit():
    track = [(1.0, {"bbox": [0, 0, 10, 10]}, None), (1.2, {"bbox": [10, 0, 20, 10]}, None)]
    assert fouls._interp(track, 1.1, "bbox") == pytest.approx([5, 0, 15, 10])
    assert fouls._interp(track, 2.0, "bbox") is None
    gap = [(1.0, {"x": 0}, None), (3.0, {"x": 10}, None)]
    assert fouls._interp(gap, 2.0, "x") is None  # never bridge a long gap


def test_indicator_not_observable_has_no_value():
    i = fouls.ind("X", True, 0.9, observable=False, detail="occluded")
    assert i["value"] is None and i["confidence"] == 0 and not i["observable"]
    assert math.isclose(fouls.ind("X", 1, 3.0)["confidence"], 1.0)

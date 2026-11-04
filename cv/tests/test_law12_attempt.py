"""Law 12 measurements that change a red: an attempt to play the ball, and an arm that only looks close."""

import numpy as np
import pytest

from var_cv import fouls


def _kps(points, conf=0.9):
    k = np.zeros((17, 3))
    for name, (x, y) in points.items():
        k[fouls.K[name]] = (x, y, conf)
    return k


def _standing(x):
    return _kps({
        "nose": (x, 228), "leye": (x - 3, 225), "reye": (x + 3, 225),
        "lear": (x - 6, 228), "rear": (x + 6, 228),
        "lsho": (x - 20, 250), "rsho": (x + 20, 250), "lelb": (x - 25, 290), "relb": (x + 25, 290),
        "lwri": (x - 27, 320), "rwri": (x + 27, 320), "lhip": (x - 12, 320), "rhip": (x + 12, 320),
        "lkne": (x - 12, 360), "rkne": (x + 12, 360), "lank": (x - 12, 395), "rank": (x + 12, 395),
    })


def test_an_arm_is_not_an_attempt_to_play_the_ball_and_a_foot_follows_the_ball():
    playing = {"observable": True, "value": True, "confidence": 0.5}
    not_playing = {"observable": True, "value": False, "confidence": 0.5}
    unseen = {"observable": False, "value": None}
    # A hand or elbow on a player, even with the ball at their feet, is not an attempt (no DOGSO downgrade).
    for striker in ("lwri", "rwri", "lelb", "relb"):
        arm = fouls._attempt({"challenging_for_ball": playing}, {"striker": striker})
        assert arm["value"] is False and arm["observable"] is True
    missing = fouls._attempt({"challenging_for_ball": unseen}, {"striker": "rank"})
    assert missing["observable"] is False and missing["value"] is None
    foot = fouls._attempt({"challenging_for_ball": playing}, {"striker": "rank"})
    assert foot["value"] is True and foot["confidence"] == pytest.approx(0.4)
    away = fouls._attempt({"challenging_for_ball": not_playing}, {"striker": "rank"})
    assert away["value"] is False and away["observable"] is True


def _arm_on_head(elbow_at, t):
    victim = _standing(500)
    chal = _standing(560)
    chal[fouls.K["relb"], :2] = elbow_at
    return {"t": t, "kps": [chal, victim], "boxes": [[540, 220, 580, 400], [480, 220, 520, 400]]}


def test_players_exactly_2m_apart_can_still_be_an_arm_to_the_head():
    nose = _standing(500)[fouls.K["nose"], :2]
    posed = [_arm_on_head(nose, 1.0)]
    ball = {"observable": False, "value": None}
    touching = fouls._arm_strike(posed, 0, 1, ball, ground_m=fouls.APART_M)
    illusion = fouls._arm_strike(posed, 0, 1, ball, ground_m=fouls.APART_M + 0.01)
    assert touching["value"] is True
    assert illusion["value"] is False and "depth illusion" in illusion["detail"]


def test_slow_motion_arm_speed_is_real_time():
    nose = _standing(500)[fouls.K["nose"], :2]
    # Closest at the middle frame, so the speed is the move from the frame before it to the frame after.
    posed = [
        _arm_on_head(nose + np.array([80.0, 0.0]), 1.0),
        _arm_on_head(nose, 1.1),
        _arm_on_head(nose + np.array([0.0, 80.0]), 1.2),
    ]
    ball = {"observable": False, "value": None}
    full = fouls._arm_strike(posed, 0, 1, ball, ground_m=0.5, playback=1.0)
    half = fouls._arm_strike(posed, 0, 1, ball, ground_m=0.5, playback=0.5)
    assert full["value"] is True and full["arm_speed_mps"] > 1
    # 0.5x playback: the same image move is twice as fast in real time. Rounded to 0.1 m/s.
    assert half["arm_speed_mps"] == pytest.approx(full["arm_speed_mps"] * 2, abs=0.15)

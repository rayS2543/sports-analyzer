"""Gates on identity and possession: a wrong link or a wrong passer moves the offside review."""

import numpy as np
import pytest

from var_cv import crossview, reid, temporal
from var_cv.analyze import UserError, check_url
from var_cv.pitch import orientation_ok, passes


def appearance(hot):
    row = np.zeros(24)
    row[hot] = 1.0
    return np.stack([row] * 4)


SAME = appearance(0)
OTHER = appearance(1)


def test_a_runner_links_only_within_the_position_and_kit_gates():
    still = (0.0, 0.0, 0.0, 0.0, 0.0)
    # 1 s gap, 3 m of slack: 9 m is chi^2 9 and still the same runner; the next centimetre is not
    assert reid._cost(still, (1.0, 9.0, 0.0, 0.0, 0.0), SAME, SAME, 0.2) == pytest.approx(9.0)
    assert reid._cost(still, (1.0, 9.01, 0.0, 0.0, 0.0), SAME, SAME, 0.2) == np.inf
    moving = (0.0, 0.0, 0.0, 5.0, 0.0)
    assert reid._cost(moving, (1.0, 5.0, 0.0, 0.0, 0.0), SAME, SAME, 0.2) == pytest.approx(0.0)
    # time does not run backwards, and a different kit is not the same runner even on the predicted spot
    assert reid._cost(still, (0.0, 0.0, 0.0, 0.0, 0.0), SAME, SAME, 0.2) == np.inf
    assert reid._cost(still, (-0.1, 0.0, 0.0, 0.0, 0.0), SAME, SAME, 0.2) == np.inf
    assert reid.dist(SAME, OTHER) == pytest.approx(1.0)
    assert np.isfinite(reid._cost(still, (1.0, 0.0, 0.0, 0.0, 0.0), SAME, OTHER, 1 / 3))
    assert reid._cost(still, (1.0, 0.0, 0.0, 0.0, 0.0), SAME, OTHER, 0.3) == np.inf
    # a shirt that was never seen does not veto a position match
    hidden = SAME.copy()
    hidden[1] = np.nan
    assert np.isnan(reid.dist(SAME, hidden))
    assert reid._cost(still, (1.0, 0.0, 0.0, 0.0, 0.0), SAME, hidden, 0.2) == pytest.approx(1.0)


def test_role_class_and_team_decide_who_may_be_the_same_person():
    keeper = {"role": "goalkeeper", "team": "A"}
    outfield = {"role": "player", "team": "A"}
    other = {"role": "player", "team": "B"}
    official = {"role": "referee", "team": None}
    unknown = {"role": "player", "team": None}
    assert reid._compatible(keeper, outfield)
    assert not reid._compatible(official, keeper)
    assert not reid._compatible(outfield, other)
    assert reid._compatible(outfield, unknown)
    assert reid._compatible(official, {"role": "referee", "team": None})


def test_an_appearance_tie_does_not_pick_an_identity():
    tied = np.array([[1.0, 1.0]])
    assert reid._unambiguous(tied, reid._hungarian(tied)) == []
    # forbidding the assigned column raises the cost by exactly 4, which is still enough
    clear = np.array([[1.0, 5.0]])
    assert reid._unambiguous(clear, reid._hungarian(clear)) == [(0, 0)]
    close = np.array([[1.0, 4.9]])
    assert reid._unambiguous(close, reid._hungarian(close)) == []


def test_track_end_velocity_is_capped_and_a_short_glitch_has_none():
    def state(samples):
        return reid._state(samples, first=False)

    one = state([(1.0, {"x": 10.0, "y": 20.0})])
    assert one[:3] == (1.0, 10.0, 20.0) and one[3:] == (0.0, 0.0)
    sprint = state([(1.0, {"x": 10.0, "y": 0.0, "vx": 12.0, "vy": 0.0})])
    assert sprint[3:] == (9.0, 0.0)
    glitch = state([(0.0, {"x": 0.0, "y": 0.0}), (0.05, {"x": 5.0, "y": 0.0}), (0.1, {"x": 10.0, "y": 0.0})])
    assert glitch[1] == pytest.approx(10.0) and glitch[3:] == (0.0, 0.0)
    run = state([(0.0, {"x": 0.0, "y": 0.0}), (0.3, {"x": 3.0, "y": 0.0}), (0.6, {"x": 6.0, "y": 0.0})])
    assert run[1] == pytest.approx(6.0) and run[3] == pytest.approx(9.0) and run[4] == pytest.approx(0.0)


def test_a_live_track_is_not_filled_in_across_a_gap():
    tr = {
        "t": np.array([0.0, 0.2, 1.0]),
        "xy": np.array([[0.0, 0.0], [2.0, 0.0], [10.0, 4.0]]),
        "sig": np.array([0.4, 0.4, 0.5]),
    }
    xy, sig = crossview.live_at(tr, [-0.06, -0.05, 0.1, 0.21, 1.0, 1.05, 1.06])
    assert np.isnan(xy[0]).all() and xy[1, 0] == pytest.approx(0.0)
    assert xy[2, 0] == pytest.approx(1.0) and sig[2] == pytest.approx(0.4)
    assert np.isnan(xy[3]).all() and np.isnan(sig[3])  # 0.8 s with no sample
    assert xy[4, 0] == pytest.approx(10.0) and xy[5, 0] == pytest.approx(10.0)
    assert np.isnan(xy[6]).all()

    tight = {"t": np.array([0.0, 0.35]), "xy": np.array([[0.0, 0.0], [1.0, 0.0]]), "sig": np.array([0.5, 0.5])}
    assert crossview.live_at(tight, [0.175])[0][0, 0] == pytest.approx(0.5)
    wide = {"t": np.array([0.0, 0.36]), "xy": np.array([[0.0, 0.0], [1.0, 0.0]]), "sig": np.array([0.5, 0.5])}
    assert np.isnan(crossview.live_at(wide, [0.18])[0]).all()

    lone = {"t": np.array([5.0]), "xy": np.array([[3.0, 4.0]]), "sig": np.array([0.2])}
    xy, _ = crossview.live_at(lone, [4.94, 4.95, 5.05, 5.06])
    assert np.isnan(xy[0]).all() and xy[1, 0] == pytest.approx(3.0)
    assert xy[2, 0] == pytest.approx(3.0) and np.isnan(xy[3]).all()


def test_live_tracks_ignore_other_shots_and_a_referee_is_neither_team():
    frames = []
    for i, role in enumerate(("referee", "referee", "player")):
        frames.append({"shot": 1, "t": i * 0.1, "calibration": {"ok": True}, "players": [
            {"global_id": 4, "track_id": 1, "x": 10.0 + i, "y": 20.0, "team": "A", "role": role}]})
    frames.append({"shot": 1, "t": 0.4, "calibration": {"ok": False}, "players": [
        {"global_id": 4, "track_id": 1, "x": 50.0, "y": 20.0, "team": "B", "role": "player"}]})
    frames.append({"shot": 1, "t": 0.0, "calibration": {"ok": True}, "players": [
        {"track_id": 3, "x": 5.0, "y": 6.0, "team": "B", "role": "player"},
        {"global_id": 4, "track_id": 1, "x": None, "y": 0.0, "team": "A", "role": "player"}]})
    frames.append({"shot": 2, "t": 0.0, "calibration": {"ok": True}, "players": [
        {"track_id": 9, "x": 1.0, "y": 1.0, "team": "A", "role": "player"}]})
    out = crossview.live_tracks({"frames": frames}, 1)
    assert set(out) == {4, 3}
    assert out[4]["team"] == "ref" and list(out[4]["t"]) == [0.0, 0.1, 0.2]
    assert out[3]["team"] == "B" and out[3]["xy"].tolist() == [[5.0, 6.0]]


def test_possession_is_the_nearest_team_player_within_1_5_m():
    ball = np.array([10.0, 20.0])
    referee = {"track_id": 1, "x": 10.0, "y": 20.0, "team": "A", "role": "referee"}
    nameless = {"track_id": 2, "x": 10.0, "y": 20.0, "team": None, "role": "player"}
    edge = {"track_id": 3, "x": 11.5, "y": 20.0, "team": "B", "role": "player"}
    owner, dist, runner_up = temporal._owner({"players": [referee, nameless, edge]}, ball)
    assert owner["track_id"] == 3 and dist == 1.5 and runner_up == 10.0
    past = {"track_id": 4, "x": 11.51, "y": 20.0, "team": "B", "role": "player"}
    assert temporal._owner({"players": [referee, nameless, past]}, ball) is None
    keeper = {"track_id": 5, "x": 10.0, "y": 20.0, "team": "A", "role": "goalkeeper"}
    owner, dist, runner_up = temporal._owner({"players": [referee, keeper, edge]}, ball)
    assert owner["track_id"] == 5 and dist == 0.0 and runner_up == 1.5


def test_line_checks_and_a_mirrored_camera_are_rejected():
    def report(**over):
        base = {"H": np.eye(3), "sigma": object(), "support": 0.5, "worst": 0.3,
                "error_m": 1.0, "uncertainty_m": 1.0}
        base.update(over)
        return base

    assert passes(report())
    assert not passes(report(support=0.499))
    assert not passes(report(worst=0.299))
    assert not passes(report(error_m=1.001))
    assert not passes(report(uncertainty_m=1.001))
    assert not passes(report(H=None))
    assert not passes(report(sigma=None))

    shape = (720, 1280)
    assert orientation_ok(np.eye(3), shape)
    assert not orientation_ok(np.diag([-1.0, 1.0, 1.0]), shape)
    assert not orientation_ok(np.zeros((3, 3)), shape)


def test_a_clip_download_accepts_only_an_https_mp4_on_the_cdn():
    check_url("https://espnmedia-cdn.akamaized.net/clips/abc.mp4")
    for url in (
        "http://espnmedia-cdn.akamaized.net/clips/abc.mp4",
        "https://espnmedia-cdn.akamaized.net.example/clips/abc.mp4",
        "https://example.com/espnmedia-cdn.akamaized.net/abc.mp4",
        "https://espnmedia-cdn.akamaized.net/clips/abc.m3u8",
        "https://espnmedia-cdn.akamaized.net/clips/abc.mp4/extra",
        "file:///tmp/abc.mp4",
    ):
        with pytest.raises(UserError):
            check_url(url)

"""Shot boundaries: a cut, a dissolve, and a fragment too short to track."""

import math

import pytest

from var_cv import shots


def _find(monkeypatch, dist, n, fps):
    monkeypatch.setattr(shots, "_dist", dist)
    return shots.find_shots(list(range(n)), fps)


def test_empty_and_sub_minimum_clips_have_no_shot(monkeypatch):
    assert shots.find_shots([], 25) == []
    fps = 10
    same = lambda a, b: 0.0
    # 2 frames are 0.2 s; 3 frames are exactly MIN_SHOT_S (0.3 s) and are a shot.
    assert _find(monkeypatch, same, 2, fps) == []
    assert _find(monkeypatch, same, 3, fps) == [(0, 2)]


def test_hard_cut_splits_only_above_the_threshold(monkeypatch):
    fps = 10

    def between(gap):
        def dist(a, b):
            return gap if {a, b} == {9, 10} else 0.0
        return dist

    assert _find(monkeypatch, between(shots.HARD_CUT), 20, fps) == [(0, 19)]
    assert _find(monkeypatch, between(shots.HARD_CUT + 1e-9), 20, fps) == [(0, 9), (10, 19)]


def test_a_flash_under_0_3s_is_not_a_shot_and_0_3s_is(monkeypatch):
    fps = 10

    def cut(flash):
        def group(i):
            if i < 10:
                return 0
            if i < 10 + flash:
                return 1
            return 2

        def dist(a, b):
            return 0.0 if group(a) == group(b) else 1.0
        return dist

    # 2 frames at 10 fps is 0.2 s: the flash is dropped and does not join the scenes it sits between.
    assert _find(monkeypatch, cut(2), 22, fps) == [(0, 9), (12, 21)]
    # 3 frames is 0.3 s, so the flash is its own shot.
    assert _find(monkeypatch, cut(3), 23, fps) == [(0, 9), (10, 12), (13, 22)]


def test_gradual_span_is_excluded_only_past_the_threshold(monkeypatch):
    fps = 10
    k = max(1, round(shots.GRADUAL_SPAN_S * fps))
    gap = {"v": shots.GRADUAL}

    def dist(a, b):
        return gap["v"] if abs(a - b) == k and min(a, b) == 10 else 0.0

    monkeypatch.setattr(shots, "_dist", dist)
    assert shots.find_shots(list(range(30)), fps) == [(0, 29)]
    gap["v"] = shots.GRADUAL + 1e-6
    # The span that moved (frames 10 .. 10+k) belongs to neither shot.
    assert shots.find_shots(list(range(30)), fps) == [(0, 9), (10 + k + 1, 29)]


def test_a_dissolve_does_not_leave_a_trackable_stub(monkeypatch):
    fps = 10
    k = max(1, round(shots.GRADUAL_SPAN_S * fps))

    def dist(a, b):
        # Excludes frames 2 .. 2+k, leaving a 0.2 s stub in front of the mix.
        return shots.GRADUAL + 1e-6 if abs(a - b) == k and min(a, b) == 2 else 0.0

    got = _find(monkeypatch, dist, 20, fps)
    assert got == [(2 + k + 1, 19)]
    assert got[0][0] > 1


@pytest.mark.parametrize("fps", [10, 25, 60])
def test_minimum_shot_uses_seconds_not_a_fixed_frame_count(monkeypatch, fps):
    # Largest frame count still under 0.3 s, so 10 fps drops 2 frames and 60 fps drops 17.
    dropped = math.floor(shots.MIN_SHOT_S * fps - 1e-9)
    same = lambda a, b: 0.0
    assert _find(monkeypatch, same, dropped, fps) == []
    assert _find(monkeypatch, same, dropped + 1, fps) == [(0, dropped)]

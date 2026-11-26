"""How far a calibration may be carried, and which speeds are real.

Offside reads the smoothed velocity as closing speed, and a missing velocity as an
8 m/s sprint. A chain of homographies that cannot be checked against painted lines
must stop, or the next frame is given a pitch it never saw.
"""

import numpy as np

from test_geometry import camera, render
from var_cv import pitch, temporal


def _frames(xs, ys, dt):
    return [{"t": round(i * dt, 3), "shot": 0, "players": [{"track_id": 1, "x": float(x), "y": float(y)}]}
            for i, (x, y) in enumerate(zip(xs, ys))]


def _velocity(vx, vy=0.0, n=21, dt=0.1, playback=1.0):
    t = np.arange(n) * dt
    frames = _frames(vx * t, vy * t, dt)
    temporal.smooth_tracks(frames, playback_speed=playback)
    return frames[n // 2]["players"][0]


def test_a_sprint_is_kept_and_anything_faster_is_a_glitch():
    on_cap = _velocity(12.0)
    assert (on_cap["vx"], on_cap["vy"]) == (12.0, 0.0)

    over = _velocity(12.2)
    assert over["vx"] is None and over["vy"] is None
    assert over["x"] == 12.2  # the position stays; only the speed is refused

    # 8 and 8 is 11.3 m/s. 9 and 9 is 12.7 m/s: the cap is the speed, not either axis.
    assert _velocity(8.0, 8.0)["vx"] == 8.0
    diagonal = _velocity(9.0, 9.0)
    assert diagonal["vx"] is None and diagonal["vy"] is None

    # Three samples over 0.10 s have no velocity. Over 0.20 s they do.
    assert _velocity(5.0, n=3, dt=0.05)["vx"] is None
    assert _velocity(5.0, n=3, dt=0.1)["vx"] == 5.0

    # Half-speed replay: 5 m per shot-second is 10 m/s real, 7 is 14 m/s and is not a run.
    assert _velocity(5.0, playback=0.5)["vx"] == 10.0
    assert _velocity(7.0, playback=0.5)["vx"] is None


def test_calibration_is_carried_across_five_blank_frames_and_not_six():
    G = camera()
    good, blank = render(G), np.full((720, 1280, 3), (40, 140, 40), np.uint8)
    H = np.linalg.inv(G)
    good_masks, blank_masks = pitch.line_mask(good), pitch.line_mask(blank)
    fail = {"H": None, "ok": False, "failure": "no pitch keypoints detected", "keypoints": 0}

    def carried(n_blank):
        recs = [{"cal": {"H": H.copy(), "ok": True, "source": "detected"}, "masks": good_masks, "motion": None}]
        for _ in range(n_blank):
            recs.append({"cal": dict(fail), "masks": blank_masks, "motion": np.eye(3)})
        recs.append({"cal": dict(fail), "masks": good_masks, "motion": np.eye(3)})
        temporal.propagate(recs)
        return recs[-1]["cal"]

    # Five frames with no paintable line, then the same camera: the sixth step is still inside the gap.
    kept = carried(5)
    assert kept["ok"] and kept["source"] == "propagated"
    probe = np.array([[640.0, 400.0], [300.0, 600.0]])
    assert np.linalg.norm(pitch.project(kept["H"], probe) - pitch.project(H, probe), axis=1).max() < 0.3

    # One more unverifiable frame and the same picture is left uncalibrated.
    dropped = carried(6)
    assert not dropped["ok"] and dropped.get("source") != "propagated"

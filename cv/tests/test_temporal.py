"""Synthetic checks for v2 logic: calibration propagation, smoothing, pass events, team head-count caps."""

import cv2
import numpy as np

from test_geometry import camera, render
from var_cv import pitch, teams, temporal, track


def textured(G, seed=0):
    img = render(G).astype(np.int16)
    rng = np.random.default_rng(seed)
    noise = cv2.GaussianBlur(rng.normal(0, 25, img.shape[:2]).astype(np.float32), (0, 0), 2.0)
    img[..., 1] += noise.astype(np.int16)  # grass texture so optical flow has something to track
    return np.clip(img, 0, 255).astype(np.uint8)


def test_propagation_carries_calibration_through_a_pan():
    G1 = camera()
    frame1 = textured(G1)
    M = np.array([[1.0, 0.0, -35.0], [0.0, 1.0, 6.0], [0.0, 0.0, 1.0]])  # camera pans: content moves 35 px left
    frame2 = cv2.warpPerspective(frame1, M, (frame1.shape[1], frame1.shape[0]))
    G2 = M @ G1
    motion = track.camera_motion(track.motion_gray(frame1), track.motion_gray(frame2))
    probe = np.array([[640.0, 400.0], [300.0, 600.0]])
    assert np.abs(pitch.project(motion, probe) - pitch.project(M, probe)).max() < 1.0

    fail = {"H": None, "ok": False, "failure": "no pitch keypoints detected", "keypoints": 0}
    recs = [{"cal": {"H": np.linalg.inv(G1), "ok": True, "source": "detected"}, "masks": pitch.line_mask(frame1),
             "motion": None},
            {"cal": dict(fail), "masks": pitch.line_mask(frame2), "motion": motion}]
    temporal.propagate(recs)
    cal = recs[1]["cal"]
    assert cal["ok"] and cal["source"] == "propagated"
    truth = pitch.project(np.linalg.inv(G2), probe)
    assert np.linalg.norm(pitch.project(cal["H"], probe) - truth, axis=1).max() < 0.3


def test_propagation_never_accepts_an_unverifiable_frame():
    G1 = camera()
    blank = np.full((720, 1280, 3), (40, 140, 40), np.uint8)  # grass without any painted line
    recs = [{"cal": {"H": np.linalg.inv(G1), "ok": True, "source": "detected"}, "masks": pitch.line_mask(render(G1)),
             "motion": None},
            {"cal": {"H": None, "ok": False, "failure": "x", "keypoints": 0}, "masks": pitch.line_mask(blank),
             "motion": np.eye(3)}]
    temporal.propagate(recs)
    assert not recs[1]["cal"]["ok"]


def _frames(xs, ys, t0=0.0, dt=0.1):
    return [{"t": round(t0 + i * dt, 3), "shot": 0, "players": [{"track_id": 1, "x": float(x), "y": float(y)}]}
            for i, (x, y) in enumerate(zip(xs, ys))]


def test_smoothing_reduces_noise_and_estimates_velocity():
    rng = np.random.default_rng(1)
    t = np.arange(21) * 0.1
    true_x = 30 + 5.0 * t  # 5 m/s along the pitch
    frames = _frames(true_x + rng.normal(0, 0.15, len(t)), np.full(len(t), 20) + rng.normal(0, 0.15, len(t)))
    temporal.smooth_tracks(frames)
    ps = [f["players"][0] for f in frames]
    raw_err = np.abs([p["raw_x"] - x for p, x in zip(ps, true_x)]).mean()
    smooth_err = np.abs([p["x"] - x for p, x in zip(ps, true_x)]).mean()
    assert smooth_err < raw_err
    vx = [p["vx"] for p in ps[3:-3]]
    assert all(v is not None for v in vx) and abs(np.mean(vx) - 5.0) < 0.5


def _pass_frames(ball_path, passer=(30.0, 30.0), receiver=(50.0, 30.0), receiver_team="A"):
    out = []
    for i, (bx, by) in enumerate(ball_path):
        out.append({"t": round(i * 0.1, 3), "shot": 0,
                    "calibration": {"ok": True, "source": "detected"},
                    "ball": {"x": bx, "y": by, "confidence": 0.8},
                    "players": [{"track_id": 1, "role": "player", "team": "A", "x": passer[0], "y": passer[1]},
                                {"track_id": 2, "role": "player", "team": receiver_team, "x": receiver[0],
                                 "y": receiver[1]},
                                {"track_id": 3, "role": "referee", "team": None, "x": 40.0, "y": 50.0}]})
    return out


def test_pass_detected_at_release_frame():
    path = [(30.3, 30.0)] * 5 + [(30.3 + 2.0 * k, 30.0) for k in range(1, 10)] + [(49.8, 30.0)] * 4
    events = temporal.detect_passes(_pass_frames(path))
    assert len(events) == 1
    e = events[0]
    assert e["t"] == 0.4 and e["passer_track_id"] == 1 and e["receiver_track_id"] == 2 and e["team"] == "A"
    assert 0 < e["confidence"] <= 0.9 and 15 < e["ball_speed_mps"] < 25


def test_no_pass_when_player_keeps_the_ball():
    frames = _pass_frames([(30.3, 30.0)] * 15)
    assert temporal.detect_passes(frames) == []


def test_team_cap_and_duplicates():
    players = [{"track_id": i, "role": "player", "team": "A", "x": 5.0 * i, "y": 10.0, "confidence": 0.9,
                "team_score": 0.5 + 0.03 * i} for i in range(13)]
    players.append({"track_id": 99, "role": "player", "team": "A", "x": 0.2, "y": 10.1, "confidence": 0.5,
                    "team_score": 0.1})  # duplicate box on player 0
    players.append({"track_id": 50, "role": "referee", "team": "B", "x": 40.0, "y": 40.0, "confidence": 0.9})
    kept = teams.cap_per_frame(players)
    assert 99 not in [p["track_id"] for p in kept]
    assert sum(p["team"] == "A" for p in kept) == 11
    assert {p["track_id"] for p in kept if p["team"] is None and p["role"] == "player"} == {0, 1}  # weakest evidence
    assert [p["team"] for p in kept if p["role"] == "referee"] == [None]


def test_duplicate_and_fragmented_tracks_are_merged():
    box = lambda x: (x, 100, x + 20, 150)
    frames = []
    for k in range(6):  # track 1 and its duplicate 2 on the same player; track 3 is someone else
        dets = [{"id": 1, "box": box(100 + 5 * k), "pos": (10 + 0.5 * k, 20.0), "conf": 0.9, "team": "A"},
                {"id": 2, "box": box(102 + 5 * k), "pos": (10.1 + 0.5 * k, 20.0), "conf": 0.5, "team": "A"},
                {"id": 3, "box": box(400), "pos": (30.0, 20.0), "conf": 0.9, "team": "B"}]
        frames.append(dets)
    for k in range(6, 10):  # track 1 is lost; track 4 appears where it should be one sample later
        frames.append([{"id": 3, "box": box(400), "pos": (30.0, 20.0), "conf": 0.9, "team": "B"}]
                      + ([{"id": 4, "box": box(140), "pos": (10 + 0.5 * k, 20.0), "conf": 0.8, "team": "A"}]
                         if k > 6 else []))
    id_map, drop = track.merge_tracks(frames, [0.1 * k for k in range(10)])
    assert id_map[2] == id_map[1] == id_map[4] and id_map[3] == 3
    assert {(k, 2) for k in range(6)} <= drop and not any(t == 1 for _, t in drop)

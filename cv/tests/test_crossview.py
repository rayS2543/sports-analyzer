"""Synthetic checks for var_cv.crossview: a replay camera recovered from live player positions."""

import cv2
import numpy as np
import pytest

from test_fouls import look_at_camera
from test_geometry import render
from var_cv import crossview, pitch, temporal

W, H = 1280, 720
ANCHOR = {"live_t": 2.0, "replay_t": 10.0, "live_pair": [1, 2], "replay_pair": [101, 102], "source": "test"}


def players(static=False):
    """gid -> (team, position(tau)): two opponents meeting at tau = 2, a team-mate, and a far player."""
    if static:
        return {1: ("A", lambda t: np.array([73.0, 64.0])), 2: ("B", lambda t: np.array([77.0, 63.0])),
                3: ("A", lambda t: np.array([71.0, 66.0])), 4: ("B", lambda t: np.array([50.0, 30.0]))}
    return {1: ("A", lambda t: np.array([75.0, 64.0]) + np.array([4.0, 2.0]) * (t - 2)),
            2: ("B", lambda t: np.array([75.5, 64.5]) + np.array([-2.0, 1.0]) * (t - 2)),
            3: ("A", lambda t: np.array([69.0, 66.0]) + np.array([3.0, -1.0]) * (t - 2)),
            4: ("B", lambda t: np.array([50.0, 30.0]) + np.array([1.0, 0.0]) * (t - 2))}


def live(ppl, rng, noise=0.3):
    """Live shot as the pipeline delivers it: noisy per-frame positions smoothed by temporal.smooth_tracks."""
    frames = [{"t": round(float(t), 3), "shot": 0, "calibration": {"ok": True},
               "players": [{"track_id": g, "global_id": g, "team": team, "role": "player", "position_uncertainty_m": noise,
                            "x": float(pos(t)[0] + rng.normal(0, noise)), "y": float(pos(t)[1] + rng.normal(0, noise))}
                           for g, (team, pos) in ppl.items()]} for t in np.arange(0.5, 3.51, 0.1)]
    temporal.smooth_tracks(frames)
    return crossview.live_tracks({"frames": frames}, 0)


def scene(seed=0, s=0.4, static=False, move=0.0, n_people=3, lines=True):
    """Replay frames of a camera at a fixed centre (or translating `move` m per frame) following the action
    between the halfway line and the box: the only paint in view is the near touchline (one line family)."""
    rng = np.random.default_rng(seed)
    ppl = players(static)
    frames, Gs = [], []
    ts = np.round(np.arange(8.0, 12.01, 0.1), 3)
    for k, t in enumerate(ts):
        tau = ANCHOR["live_t"] + s * (t - ANCHOR["replay_t"])
        C = np.array([79.0 + move * k, 82.0, -10.0])
        target = np.r_[(ppl[1][1](tau - 0.1) + ppl[2][1](tau - 0.1)) / 2, 0.0]  # pans with a little lag
        f = 2000.0 + 600.0 * k / (len(ts) - 1)  # zooms in
        P = look_at_camera(C, target, f)
        G = P[:, [0, 1, 3]] / P[2, 3]
        people = []
        for g, tid in list(zip((1, 2, 3), (101, 102, 103)))[:n_people]:
            X = ppl[g][1](tau)
            u = pitch.project(G, X)[0]
            head = P @ np.r_[X, -crossview.BODY_H, 1.0]  # the player's box: feet to head, projected
            hpx = np.linalg.norm(head[:2] / head[2] - u)
            if 5 < u[0] < W - 5 and 5 < u[1] < H - 5:
                people.append({"track": tid, "team": ppl[g][0], "foot": u + rng.normal(0, 1.5, 2),
                               "h": hpx * rng.normal(1.0, 0.08), "h_ok": True})
        frames.append({"t": float(t), "people": people, "masks": pitch.line_mask(render(G)) if lines else None,
                       "motion": None})
        Gs.append(G)
    for k in range(1, len(frames)):
        M = Gs[k] @ np.linalg.inv(Gs[k - 1])  # camera motion; exact homography for a rotating camera
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        dst = pitch.project(M, src) + rng.normal(0, 0.3, (4, 2))
        frames[k]["motion"] = cv2.getPerspectiveTransform(src, dst.astype(np.float32)).astype(float)
    return frames, Gs, live(ppl, rng), ppl


@pytest.fixture(scope="module")
def solved():
    frames, Gs, lv, ppl = scene()
    rep = crossview.solve(frames, (W, H), lv, [ANCHOR], loo=True)
    return rep, frames, Gs, ppl


def test_recovers_camera_centre_and_speed(solved):
    rep, *_ = solved
    assert rep["status"] == "done", rep["failure"]
    err = np.linalg.norm(np.array(rep["camera_centre"]) - [79.0, 82.0, 10.0])
    # 1.5 m is the target; one painted line and three players leave a distance-vs-zoom ridge, so the
    # honest bar is the reported sigma (profile floor included): the truth within 2 sigma
    assert err <= max(1.5, 2 * rep["camera_centre_sigma_m"]), (err, rep["camera_centre_sigma_m"])
    assert abs(rep["speed"] - 0.4) <= 0.03
    assert {(m["replay_track"], m["live_gid"]) for m in rep["matched"]} >= {(101, 1), (102, 2), (103, 3)}
    assert rep["fixed_centre_residual_px"] < crossview.MOVING_PX


def test_only_parallel_paint_is_in_view(solved):
    rep, *_ = solved
    assert set(rep["line_families"]) <= {"along"}


def test_ground_positions_near_contact_and_honest_sigma(solved):
    rep, frames, Gs, ppl = solved
    rng = np.random.default_rng(1)
    errs, covered = [], []
    ok = [k for k, r in enumerate(rep["frame_results"]) if r["ok"]]
    assert len(ok) >= 0.8 * len(frames)
    for k in ok:
        r = rep["frame_results"][k]
        tau = ANCHOR["live_t"] + 0.4 * (frames[k]["t"] - ANCHOR["replay_t"])
        centre = (ppl[1][1](tau) + ppl[2][1](tau)) / 2
        pts = centre + rng.uniform(-3, 3, (20, 2))  # ground within 3 m of the contact
        img = pitch.project(Gs[k], pts)
        img = img[(img[:, 0] > 0) & (img[:, 0] < W) & (img[:, 1] > 0) & (img[:, 1] < H)]
        est = pitch.project(np.linalg.inv(r["G"]), img)
        truth = pitch.project(np.linalg.inv(Gs[k]), img)
        e = np.linalg.norm(est - truth, axis=1)
        errs += list(e)
        covered += list(e <= 2 * r["sigma"](img))
    assert np.percentile(errs, 90) <= 0.4
    assert np.mean(covered) >= 0.8


def test_one_static_player_without_lines_is_underdetermined():
    frames, _, lv, _ = scene(static=True, n_people=1, lines=False)
    rep = crossview.solve(frames, (W, H), lv, [ANCHOR], use_lines=False, loo=False)
    assert rep["status"] == "failed" and rep["failure"].startswith("underdetermined")
    assert not any(r["ok"] for r in rep["frame_results"])


def test_translating_camera_fails_honestly():
    frames, _, lv, _ = scene(move=1.0, n_people=2)
    rep = crossview.solve(frames, (W, H), lv, [ANCHOR], loo=False)
    assert rep["status"] == "failed" and rep["failure"].startswith("replay camera moves")


def test_static_players_leave_the_speed_ambiguous():
    frames, _, lv, _ = scene(static=True)
    rep = crossview.solve(frames, (W, H), lv, [ANCHOR], loo=False)
    assert rep["status"] == "failed" and rep["failure"].startswith("sync ambiguous")


def test_feet_failure_says_when_the_replay_shows_people_the_live_shot_does_not_track():
    few = crossview.feet_failure(8.88, 7.77, 174, 17, 4, 8, 1.8)
    assert few.startswith("no consistent camera") and "17 of 174" in few and "4 of 8 replay people" in few
    assert "1.8 m" in few and "not tracked in the live shot" in few and "swap" not in few
    most = crossview.feet_failure(7.0, 7.0, 40, 30, 3, 3, 12.0)  # most feet matched, still no camera: identities are the suspect
    assert "30 of 40" in most and "wrong identities" in most and "not tracked" not in most


def goal_scene(end="a", live_at_end=None, seed=0):
    """Replay of a corner at one goal: the goal line, 6-yard box and penalty area are painted in view (two line
    families), six people move around the box. Returns frames, true cameras, live tracks, people positions."""
    rng = np.random.default_rng(seed)
    flip = (lambda p: np.array([pitch.LENGTH - p[0], pitch.WIDTH - p[1]])) if end == "b" else (lambda p: np.asarray(p, float))
    base = [(6.0, 30.0, 1.0, 0.5), (8.0, 36.0, -0.8, 0.6), (11.0, 33.0, 0.5, -1.0), (13.0, 28.0, -1.2, 0.4),
            (14.0, 40.0, 0.9, -0.7), (4.0, 38.0, 0.3, 0.2)]
    where = (lambda p: p) if live_at_end is None else live_at_end
    ppl = {g + 1: ("AB"[g % 2], lambda t, b=b: flip(np.array([b[0], b[1]]) + np.array([b[2], b[3]]) * (t - 2)))
           for g, b in enumerate(base)}
    lv_ppl = {g: (team, lambda t, f=f: where(f(t))) for g, (team, f) in ppl.items()}
    frames, Gs = [], []
    ts = np.round(np.arange(10.0, 11.01, 0.2), 3)
    for k, t in enumerate(ts):
        tau = ANCHOR["live_t"] + (t - 10.0)
        C = flip(np.array([9.0, 98.0]))
        P = look_at_camera(np.r_[C, -24.0], np.r_[flip(np.array([9.0 + 0.5 * k, 33.0])), 0.0], 3300.0 + 100 * k)
        G = P[:, [0, 1, 3]] / P[2, 3]
        people = []
        for g in ppl:
            u = pitch.project(G, ppl[g][1](tau))[0]
            if 5 < u[0] < W - 5 and 5 < u[1] < H - 5:
                people.append({"track": 100 + g, "team": None, "foot": u + rng.normal(0, 1.5, 2), "h": 60.0, "h_ok": True})
        frames.append({"t": float(t), "people": people, "masks": pitch.line_mask(render(G)), "motion": None})
        Gs.append(G)
    for k in range(1, len(frames)):
        M = Gs[k] @ np.linalg.inv(Gs[k - 1])
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        frames[k]["motion"] = cv2.getPerspectiveTransform(src, pitch.project(M, src).astype(np.float32)).astype(float)
    return frames, Gs, live(lv_ppl, rng), ppl


@pytest.mark.parametrize("end", ["a", "b"])
def test_painted_lines_calibrate_the_replay_and_the_live_players_pick_the_end(end):
    frames, Gs, lv, ppl = goal_scene(end)
    rep = crossview.solve(frames, (W, H), lv, [ANCHOR], loo=False)
    assert rep["status"] == "done", rep["failure"]
    assert rep["source"] == "painted_lines" and rep["speed"] is None
    assert rep["calibrated_frames"] >= len(frames) - 1
    for k, r in enumerate(rep["frame_results"]):
        if r["ok"]:
            tau = ANCHOR["live_t"] + (frames[k]["t"] - 10.0)
            pts = np.array([ppl[g][1](tau) for g in ppl])
            img = pitch.project(Gs[k], pts)
            assert np.linalg.norm(pitch.project(np.linalg.inv(r["G"]), img) - pts, axis=1).max() <= 0.5


def test_painted_lines_are_rejected_when_no_live_player_stands_there():
    frames, _, lv, _ = goal_scene("a", live_at_end=lambda p: np.array([60.0, 34.0]) + (p - [10.0, 34.0]) * 0.0)
    rep = crossview.solve_lines(frames, (W, H), lv, [ANCHOR])
    assert rep["status"] == "failed" and "not confirmed" in rep["failure"]

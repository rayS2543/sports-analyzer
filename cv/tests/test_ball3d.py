"""ball3d on a synthetic broadcast camera: known intrinsics/pose, rendered ball boxes with pixel noise."""

import copy

import numpy as np

from var_cv import ball3d

W, H_IMG, F = 1280, 720, 1400.0
C_TRUE = np.array([52.5, 100.0, -22.0])  # world z points down (x along length, y towards the camera)
R_BALL = ball3d.BALL_R


def camera(target, f=F):
    z = target - C_TRUE
    z /= np.linalg.norm(z)
    x = np.cross([0, 0, 1.0], z)
    x /= np.linalg.norm(x)
    R = np.array([x, np.cross(z, x), z])
    K = np.array([[f, 0, W / 2], [0, f, H_IMG / 2], [0, 0, 1]])
    return K, R, -R @ C_TRUE


def render(K, R, t, p):
    """(x, y, height of ball bottom) -> ball bbox [x1, y1, x2, y2] in px."""
    c = R @ np.array([p[0], p[1], -(p[2] + R_BALL)]) + t
    u = K @ c
    u = u[:2] / u[2]
    r = K[0, 0] * R_BALL / c[2]
    return u, r


def make_analysis(traj, rng, noise=1.5, cal_m=0.2, players=None, outlier_at=None):
    """traj: list of (t, (x, y, h)). Camera pans to follow the ball (target 5 m ahead of it). Each frame's
    homography is wrong by a random ground shift of cal_m (like a real per-frame calibration)."""
    frames = []
    for k, (t, p) in enumerate(traj):
        K, R, tr = camera(np.array([p[0] + 5, p[1], 0.0]))
        dx, dy = rng.normal(0, cal_m, 2)
        Hm = K @ np.c_[R[:, 0], R[:, 1], tr] @ np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]])
        Hm /= Hm[2, 2]
        u, r = render(K, R, tr, p)
        u = u + rng.normal(0, noise, 2)
        if k == outlier_at:
            u = u + [40, -25]
        r = r + rng.normal(0, 0.5)
        g = np.linalg.solve(Hm, [u[0], u[1] + r, 1])  # naive: bottom of the box on the grass
        frame = {"t": t, "shot": 0,
                 "calibration": {"ok": True, "homography": Hm.tolist(), "reprojection_error_m": 1.5 * cal_m},
                 "ball": {"x": g[0] / g[2], "y": g[1] / g[2], "confidence": 0.8, "image": [u[0], u[1] + r],
                          "bbox": [u[0] - r, u[1] - r, u[0] + r, u[1] + r]},
                 "players": []}
        for pp in (players or {}).get(k, []):
            pu, _ = render(K, R, tr, (*pp, -R_BALL))
            frame["players"].append({"track_id": 1, "bbox": [pu[0] - 15, pu[1] - 60, pu[0] + 15, pu[1]]})
        frames.append(frame)
    return {"video": {"width": W, "height": H_IMG}, "frames": frames}


def lofted_pass(dt=0.1):
    """Dribble 1 s, lofted pass (peak 6.17 m), one bounce, then rolling. Returns traj, landing point, peak."""
    out = []
    p0, v, vz = np.array([30.0, 40.0]), np.array([16.0, -5.0]), 11.0
    T = 2 * vz / ball3d.G
    land = p0 + v * T
    for t in np.arange(0, 5.0, dt):
        if t < 1.0:  # dribble towards the kick point
            xy, h = p0 - [3.0 * (1.0 - t), 0.0], 0.0
        elif t < 1.0 + T:
            s = t - 1.0
            xy, h = p0 + v * s, vz * s - ball3d.G * s * s / 2
        elif t < 1.0 + T + 0.7:  # bounce
            s = t - 1.0 - T
            xy, h = land + 0.7 * v * s, 3.43 * s - ball3d.G * s * s / 2
        else:
            s = t - 1.0 - T - 0.7
            xy, h = land + 0.7 * v * 0.7 + 0.7 * v * s * (1 - 0.05 * s), 0.0
        out.append((round(float(t), 3), (float(xy[0]), float(xy[1]), max(float(h), 0.0))))
    return out, land, vz * vz / (2 * ball3d.G)


def test_camera_recovered_from_homography():
    K, R, t = camera(np.array([60.0, 30.0, 0.0]), f=1800.0)
    cam = ball3d.camera_from_homography(K @ np.c_[R[:, 0], R[:, 1], t], W, H_IMG)
    assert abs(cam["f"] - 1800) < 1
    assert np.allclose(cam["C"], C_TRUE, atol=0.05)
    assert np.allclose(cam["R"], R, atol=1e-6)


def test_lofted_pass_height_and_landing():
    traj, land, peak = lofted_pass()
    rng = np.random.default_rng(0)
    kick = [k for k, (t, _) in enumerate(traj) if 0.85 <= t <= 1.05]
    an = make_analysis(traj, rng, players={k: [(30.0, 40.6)] for k in kick}, outlier_at=5)
    ball3d.apply(an)
    balls = [f["ball"] for f in an["frames"]]
    t = np.array([tt for tt, _ in traj])
    true_h = np.array([p[2] for _, p in traj])
    z = np.array([np.nan if b["z"] is None else b["z"] for b in balls])
    flight = (t > 1.05) & (t < 3.2)
    assert all(b["airborne"] for b, fl in zip(balls, flight) if fl)
    err = np.abs(z - true_h)[flight]
    assert np.sqrt(np.mean(err ** 2)) < 0.4, err
    assert abs(np.nanmax(z[flight]) - peak) < 0.5
    # landing point: where the recovered flight (z parabola, linear ground track) reaches the grass
    tf = t[flight]
    t_land = np.roots(np.polyfit(tf, z[flight], 2)).real.max()
    xy = [np.polyval(np.polyfit(tf, [balls[i][k] for i in np.where(flight)[0]], 1), t_land) for k in "xy"]
    assert abs(t_land - (1.0 + 2 * 11.0 / ball3d.G)) < 0.1
    assert np.linalg.norm(np.array(xy) - land) < 1.5
    # the naive projection puts the airborne ball many metres away; the corrected one does not
    true_xy = np.array([p[:2] for _, p in traj])
    naive = np.array([[b["ground_x"], b["ground_y"]] for b in balls])
    fixed = np.array([[b["x"], b["y"]] for b in balls])
    assert np.linalg.norm(naive - true_xy, axis=1)[flight].max() > 10
    assert np.linalg.norm(fixed - true_xy, axis=1)[flight].max() < 2.0
    # 0.6 m hop after the landing: the landing is a free breakpoint, so the hop is its own flight
    unc = np.array([b["height_uncertainty_m"] for b in balls], float)
    bounce = (t > 3.25) & (t < 3.85)
    assert all(b["airborne"] for b, bo in zip(balls, bounce) if bo)
    assert np.abs(z - true_h)[bounce].max() < 0.3
    assert (np.abs(z - true_h)[bounce] <= 2.5 * unc[bounce]).all()
    assert (np.abs(z - true_h)[flight] <= 2.5 * unc[flight]).all()
    # the false detection gets no height and keeps its naive position (as its own run or a trajectory outlier)
    assert balls[5]["height_model"] in ("outlier", "unfitted") and balls[5]["z"] is None
    assert (balls[5]["x"], balls[5]["y"]) == (balls[5]["ground_x"], balls[5]["ground_y"])
    for b, tt in zip(balls, t):  # dribble before the kick: on the ground
        if tt < 0.8 and b["height_model"] not in ("outlier", "unfitted"):
            assert b["airborne"] is False and b["z"] == 0.0
    assert unc[flight].max() < 1.0


def test_rolling_ball_stays_on_ground():
    traj = []
    for t in np.arange(0, 3.0, 0.1):
        s = 8.0 * t - 0.5 * t * t
        traj.append((round(float(t), 3), (40 + 0.8 * s, 20 + 0.6 * s, 0.0)))
    an = make_analysis(traj, np.random.default_rng(1))
    ball3d.apply(an)
    for f, (_, p) in zip(an["frames"], traj):
        b = f["ball"]
        assert b["height_model"] == "rolling" and b["airborne"] is False and b["z"] == 0.0
        assert np.hypot(b["x"] - p[0], b["y"] - p[1]) < 1.0  # raw per-frame pixel, 1.5 px noise
        assert b["height_uncertainty_m"] is not None


def test_uncalibrated_frames_untouched_and_idempotent():
    traj, _, _ = lofted_pass()
    an = make_analysis(traj, np.random.default_rng(2))
    an["frames"][10]["calibration"] = {"ok": False, "homography": None}
    before = copy.deepcopy(an["frames"][10])
    ball3d.apply(an)
    assert an["frames"][10] == before
    once = copy.deepcopy(an)
    ball3d.apply(an)
    assert an == once


def driven_shot(v0=(28.0, -4.0, 7.0), dt=0.1, T=1.3, k=ball3d.DRAG_K):
    """A hard, low drive with real quadratic drag (integrated at 1 ms), then the ball is off camera."""
    p, v, out, s = np.array([20.0, 40.0, 0.0]), np.array(v0), [], 0.0
    for step in range(int(T / 0.001) + 1):
        if step % int(dt / 0.001) == 0:
            out.append((round(s, 3), (float(p[0]), float(p[1]), max(float(p[2]), 0.0))))
        a = -k * np.linalg.norm(v) * v - [0, 0, ball3d.G]
        v, p, s = v + a * 0.001, p + v * 0.001, s + 0.001
    return out


def test_hard_shot_is_fitted_with_air_drag(monkeypatch):
    traj = driven_shot()
    true = np.array([p for _, p in traj])

    def fitted():
        an = make_analysis(traj, np.random.default_rng(4), players={0: [(20.0, 40.6)], 1: [(20.0, 40.6)]})
        ball3d.apply(an)
        return np.array([[f["ball"]["x"], f["ball"]["y"], f["ball"]["z"] if f["ball"]["z"] is not None else np.nan]
                         for f in an["frames"]])

    with_drag = np.nanmax(np.linalg.norm(fitted() - true, axis=1)[2:])
    monkeypatch.setattr(ball3d, "DRAG_K", 0.0)
    without = np.nanmax(np.linalg.norm(fitted() - true, axis=1)[2:])
    assert with_drag < 1.0 and with_drag < without, (with_drag, without)

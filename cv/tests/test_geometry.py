"""Pure-logic checks on synthetic data: homography + error estimate, line check, shot cuts, tracking."""

import cv2
import numpy as np

from var_cv import pitch, shots, track

W, H_IMG = 1280, 720


def camera():
    """A broadcast-like pitch->image homography (camera above the near touchline, looking at the centre)."""
    src = np.float32([[5, 0], [100, 0], [85, 68], [20, 68]])
    dst = np.float32([[150, 80], [1130, 80], [1500, 800], [-220, 800]])
    return cv2.getPerspectiveTransform(src, dst).astype(np.float64)


def render(G):
    """Green pitch with white lines drawn through G (pitch->image)."""
    img = np.zeros((H_IMG, W, 3), np.uint8)
    img[:] = (40, 140, 40)
    for line in pitch.LINES:
        p = pitch.project(G, line)
        p = p[~np.isnan(p).any(1) & (np.abs(p) < 1e4).all(1)]
        if len(p) > 1:
            cv2.polylines(img, [p.astype(np.int32)], False, (235, 235, 235), 3)
    return img


def test_calibrate_recovers_homography_and_rejects_outlier():
    G = camera()
    rng = np.random.default_rng(0)
    img_pts = pitch.project(G, pitch.VERTICES)
    vis = (img_pts[:, 0] > 0) & (img_pts[:, 0] < W) & (img_pts[:, 1] > 0) & (img_pts[:, 1] < H_IMG)
    img_pts, world = img_pts[vis] + rng.normal(0, 1.0, (vis.sum(), 2)), pitch.VERTICES[vis]
    img_pts[0] += 150  # one mislabelled keypoint
    H, inl, err = pitch.calibrate(img_pts, world)
    assert not inl[0] and inl[1:].all()
    assert err < 0.5  # 1 px keypoint noise -> sub-half-metre leave-one-out error
    probe = np.array([[640.0, 400.0], [300.0, 600.0]])
    truth = pitch.project(np.linalg.inv(G), probe)
    assert np.abs(pitch.project(H, probe) - truth).max() < 0.5


def test_calibrate_needs_five_inliers_for_an_error_estimate():
    G = camera()
    world = pitch.VERTICES[[13, 16, 30, 31]]  # halfway ends + circle sides
    H, _, err = pitch.calibrate(pitch.project(G, world), world)
    assert H is not None and err == float("inf")


def test_line_refinement_fixes_small_error_and_rejects_wrong_calibration():
    G = camera()
    masks = pitch.line_mask(render(G))
    H_true = np.linalg.inv(G)
    none = np.zeros((0, 2))
    # keypoint fit a few pixels off -> refinement snaps onto the painted lines
    r = pitch.refine(H_true @ np.array([[1, 0, 6], [0, 1, -4], [0, 0, 1.0]]), masks, none, none)
    assert pitch.passes(r) and r["support"] > 0.9 and r["error_m"] < 0.3
    probe = np.array([[640.0, 400.0], [100.0, 700.0]])
    assert np.linalg.norm(pitch.project(r["H"], probe) - pitch.project(H_true, probe), axis=1).max() < 0.3
    # per-point uncertainty is finite, small near lines and larger far from the pitch centre
    s = r["sigma"](probe)
    assert np.isfinite(s).all() and s[0] < 0.5
    # a calibration 12 m off along the pitch has no line evidence -> not ok
    wrong = np.array([[1, 0, 12.0], [0, 1, 0], [0, 0, 1]]) @ H_true
    assert not pitch.passes(pitch.refine(wrong, masks, none, none))


def _solid(bgr, seed):
    rng = np.random.default_rng(seed)
    img = np.full((90, 160, 3), bgr, np.uint8)
    return cv2.add(img, rng.integers(0, 20, img.shape, dtype=np.uint8))


def test_hard_cut_splits_shots():
    fps = 60
    frames = [_solid((40, 140, 40), i) for i in range(60)] + [_solid((120, 40, 160), i) for i in range(60)]
    got = shots.find_shots([shots.signature(f) for f in frames], fps)
    assert got == [(0, 59), (60, 119)]


def test_dissolve_is_excluded_from_both_shots():
    fps = 60
    a, b = (40, 140, 40), (140, 90, 30)
    frames = [_solid(a, i) for i in range(60)]
    frames += [cv2.addWeighted(_solid(a, i), 1 - w, _solid(b, i), w, 0) for i, w in enumerate(np.linspace(0, 1, 40))]
    frames += [_solid(b, i) for i in range(60)]
    got = shots.find_shots([shots.signature(f) for f in frames], fps)
    assert len(got) == 2
    (s0, e0), (s1, e1) = got
    assert s0 == 0 and e0 < 75 and s1 > 85 and e1 == 159  # the blend frames belong to no shot


def test_tracking_follows_players_through_a_pan():
    boxes0 = np.array([[100, 100, 120, 150], [300, 100, 320, 150]], float)
    pan = np.array([80.0, 0.0])  # camera pans: everything moves 80 px, far beyond IoU overlap
    boxes1 = boxes0[::-1] + np.r_[pan, pan] + [3, 0, 3, 0]
    ids = track.assign_ids([(boxes0, lambda p: p), (boxes1, lambda p: p + pan)])
    assert list(ids[0]) == [1, 2] and list(ids[1]) == [2, 1]

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


def test_shadowed_painted_lines_remain_calibratable():
    G = camera()
    # Same geometry, dark stadium shadow; paint's absolute contrast falls below 25.
    image = (render(G).astype(float) * 0.25).astype(np.uint8)
    none = np.zeros((0, 2))
    r = pitch.refine(np.linalg.inv(G), pitch.line_mask(image), none, none)
    assert pitch.passes(r) and r["support"] > 0.9


def test_closeup_of_one_line_cannot_establish_metric_positions():
    # Only the halfway line is visible. Sliding metres along it leaves the image
    # unchanged, so perfect painted-line support is not enough for calibration.
    G = np.array([[28., 0., -830.], [0., 31., -31.], [0., 0., 1.]])
    masks = pitch.line_mask(render(G))
    none = np.zeros((0, 2))
    r = pitch.refine(np.linalg.inv(G), masks, none, none)
    assert r["support"] > 0.99 and r["error_m"] < 0.1
    assert not pitch.passes(r)
    # A finite patch must not conceal an unobservable part of the visible grass.
    assert pitch.region_error(lambda pts: np.where(pts[:, 0] < 640, 0.1, np.inf), masks[1]) == float("inf")


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



def _box(x, y, w=30, h=80):
    return [x - w / 2, y - h, x + w / 2, y]


def _track(frames):
    return track.assign_ids([(np.array(b, float).reshape(-1, 4), lambda p: p, *t) for b, *t in frames])


def test_runners_who_cross_keep_their_ids():
    # A runs right at 25 px/sample, B left at 15, level with each other: they swap sides between two
    # samples, and nearest-last-position matching hands each the other's box
    ids = _track([([_box(100 + 25 * k, 300), _box(400 - 15 * k, 300)],) for k in range(14)])
    assert list(ids[-1]) == list(ids[0])


def test_players_hidden_in_one_merged_box_keep_their_ids():
    # A overtakes B (vA 25, vB 5 px/sample, 15 px apart in depth); for two samples the detector returns
    # one wide box. Snapping to that box would leave A behind B's old position when they separate.
    def row(k):
        a, b = 20 + 25 * k, 90 + 5 * k
        return [[min(a, b) - 15, 220, max(a, b) + 15, 315]] if k in (3, 4) else [_box(a, 300), _box(b, 315)]

    ids = _track([(row(k),) for k in range(12)])
    assert list(ids[-1]) == list(ids[0])


def test_a_track_never_continues_onto_the_other_kit_or_a_much_smaller_box():
    box = [_box(200, 300)]
    ids = _track([(box, ["A"]), (box, ["B"])])
    assert ids[0][0] != ids[1][0]
    ids = _track([(box,), ([_box(200, 300, 8, 20)],)])  # a ball-sized box is not the player
    assert ids[0][0] != ids[1][0]
    ids = _track([(box, ["A"]), (box, ["A"]), (box, [None])])  # unlabelled blur does not break a track
    assert ids[0][0] == ids[2][0]


def test_plain_association_has_no_velocity_or_kit_gates():
    # close-ups use tangles=False: runners crossing between samples are matched to the nearest last position
    frames = [(np.array([_box(100 + 25 * k, 300), _box(400 - 15 * k, 300)], float), lambda p: p) for k in range(14)]
    ids = track.assign_ids(frames, tangles=False)
    assert list(ids[-1]) != list(ids[0])
    assert list(track.assign_ids(frames)[-1]) == list(track.assign_ids(frames)[0])

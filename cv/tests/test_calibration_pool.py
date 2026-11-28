"""Keypoints borrowed from a neighbouring frame, and which keypoints may set a pitch.

Offside and foul review measure metres from this homography. A keypoint from the
other side of a cut, or one clipped by the frame edge, must not move the pitch.
"""

import numpy as np

from test_geometry import camera, render
from var_cv import pitch, temporal


def _view(conf=0.9):
    """Rendered pitch, its line masks, and the keypoints of that same camera."""
    image_of_pitch = camera()
    frame = render(image_of_pitch)
    masks = pitch.line_mask(frame)
    img = pitch.project(image_of_pitch, pitch.VERTICES)
    finite = np.isfinite(img).all(1)
    height, width = frame.shape[:2]
    visible = finite & (img[:, 0] > 20) & (img[:, 0] < width - 20) & (img[:, 1] > 20) & (img[:, 1] < height - 20)
    keypoints = np.zeros((len(pitch.VERTICES), 3))
    keypoints[finite, :2] = img[finite]
    keypoints[:, 2] = np.where(visible, conf, 0.0)
    return frame, masks, keypoints, np.linalg.inv(image_of_pitch)


def _blank():
    return {"H": None, "ok": False, "failure": "no pitch keypoints detected", "keypoints": 0,
            "support": 0.0, "worst_line": 0.0, "error_m": None, "sigma": None, "loo_m": None}


def _records(masks, keypoints, length, at, break_at=()):
    records = []
    for i in range(length):
        motion = None if i == 0 or i in break_at else np.eye(3)
        records.append({"cal": _blank(), "masks": masks, "motion": motion, "kps": keypoints if i == at else None})
    return records


def _metres(got, truth):
    probe = np.array([[640.0, 400.0], [300.0, 600.0]])
    return np.linalg.norm(pitch.project(got, probe) - pitch.project(truth, probe), axis=1).max()


def test_a_neighbour_six_samples_away_lends_its_keypoints_and_the_seventh_does_not():
    _frame, masks, keypoints, truth = _view()
    near = _records(masks, keypoints, length=7, at=6)  # index 6 is the edge of the radius
    assert temporal.pool_keypoints(near) >= 1
    assert near[0]["cal"]["ok"] and near[0]["cal"]["source"] == "propagated"
    assert _metres(near[0]["cal"]["H"], truth) < 0.3

    far = _records(masks, keypoints, length=8, at=7)
    temporal.pool_keypoints(far)
    assert not far[0]["cal"]["ok"]
    assert far[0]["cal"]["failure"] == "no pitch keypoints detected"


def test_a_cut_does_not_lend_its_keypoints_to_the_shot_before_it():
    _frame, masks, keypoints, _truth = _view()
    records = _records(masks, keypoints, length=2, at=1, break_at={1})
    temporal.pool_keypoints(records)
    assert not records[0]["cal"]["ok"]
    assert records[1]["cal"]["ok"] and records[1]["cal"]["source"] == "propagated"


def test_a_borrowed_keypoint_must_clear_the_confidence_floor():
    _frame, masks, keypoints, truth = _view(conf=pitch.KP_CONF)
    at_floor = _records(masks, keypoints, length=2, at=1)
    temporal.pool_keypoints(at_floor)
    assert not at_floor[0]["cal"]["ok"]

    keypoints[:, 2] = np.where(keypoints[:, 2] > 0, pitch.KP_CONF + 0.01, 0.0)
    above = _records(masks, keypoints, length=2, at=1)
    assert temporal.pool_keypoints(above) >= 1
    assert above[0]["cal"]["ok"] and _metres(above[0]["cal"]["H"], truth) < 0.3


def test_a_keypoint_on_the_frame_border_is_not_a_landmark():
    frame, masks, keypoints, _truth = _view()
    on_edge = keypoints.copy()
    on_edge[:, 0] = pitch.BORDER_PX
    records = _records(masks, on_edge, length=1, at=0)
    temporal.pool_keypoints(records)
    assert not records[0]["cal"]["ok"]
    assert records[0]["cal"]["failure"] == "no pitch keypoints detected"

    refused = pitch.calibrate_frame(frame, on_edge, masks)
    assert refused["keypoints"] == 0
    assert "0 usable" in refused["failure"]

    just_inside = on_edge.copy()
    just_inside[:, 0] = pitch.BORDER_PX + 0.01
    counted = pitch.calibrate_frame(frame, just_inside, masks)
    assert counted["keypoints"] == int((keypoints[:, 2] > 0).sum())


def test_a_single_frame_accepts_a_weaker_keypoint_than_a_borrowed_one():
    frame, masks, keypoints, truth = _view(conf=0.3)
    at_floor = pitch.calibrate_frame(frame, keypoints, masks)
    assert at_floor["keypoints"] == 0 and not at_floor["ok"]

    visible = int((keypoints[:, 2] > 0).sum())
    keypoints[:, 2] = np.where(keypoints[:, 2] > 0, 0.31, 0.0)
    kept = pitch.calibrate_frame(frame, keypoints, masks)
    assert kept["ok"] and kept["keypoints"] == visible
    assert _metres(kept["H"], truth) < 0.3

    keypoints[:, 2] = np.where(keypoints[:, 2] > 0, pitch.KP_CONF, 0.0)
    strict = pitch.calibrate_frame(frame, keypoints, masks)
    assert strict["ok"] and strict["keypoints"] == visible

    assert "no pitch keypoints" in pitch.calibrate_frame(frame, None, masks)["failure"]

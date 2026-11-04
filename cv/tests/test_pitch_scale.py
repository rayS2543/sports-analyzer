"""Metres per pixel is the local area scale of the image-to-pitch map."""

import numpy as np
import pytest

from var_cv import pitch


def test_uniform_scale_is_metres_per_pixel():
    s = 0.05
    H = np.diag([s, s, 1.0])
    got = pitch.m_per_px(H, [[100, 80], [400, 200]])
    assert got == pytest.approx([s, s])


def test_a_reflection_keeps_the_scale_positive():
    # The Jacobian determinant flips sign when the map mirrors. Position error is a length.
    s = 0.05
    H = np.array([[s, 0, 0], [0, -s, 0], [0, 0, 1.0]])
    assert pitch.m_per_px(H, [[100, 80]]) == pytest.approx([s])


def test_a_point_behind_the_camera_has_no_scale():
    H = np.array([[0.05, 0, 0], [0, 0.05, 0], [0.001, 0.001, -1.0]])
    assert np.isnan(pitch.m_per_px(H, [[0, 0]])[0])

"""How a painted-line camera is scored before it is trusted.

The replay end is chosen from this score. A homography that misses the grass, or
puts the pitch outside the frame, has to come back as no answer rather than a poor one.
"""

import math

import numpy as np

from test_geometry import camera, render
from var_cv import paintcam, pitch


def test_the_true_camera_scores_and_a_pitch_off_the_grass_does_not():
    image_of_pitch = camera()
    masks = pitch.line_mask(render(image_of_pitch))
    distance = pitch._dist_map(*masks, 20.0)
    ys, xs = np.where(masks[0] > 0)
    cloud = np.c_[xs[::50], ys[::50]].astype(float)

    assert paintcam.score(image_of_pitch, masks, distance, cloud) < 0.2

    off_screen = image_of_pitch.copy()
    off_screen[0, 2] += 5000
    assert math.isinf(paintcam.score(off_screen, masks, distance, cloud))

    no_grass = (masks[0], np.zeros_like(masks[1]))
    assert math.isinf(paintcam.score(image_of_pitch, no_grass, distance, cloud))

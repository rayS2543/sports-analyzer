"""Which pixels belong to one painted line.

Replay calibration builds a homography from these lines. A speck that happens to
be collinear, or a gap of a few dozen pixels, must not lengthen the line or split it.
"""

import numpy as np

from var_cv import paintcam


def _column(ys):
    ys = np.asarray(ys, float)
    return np.c_[np.full(len(ys), 400.0), ys]


def test_a_vertical_line_drops_a_short_speck_and_keeps_a_forty_pixel_gap():
    # The line runs down the image. Using x instead of distance along the line would collapse it.
    d = np.array([0.0, 1.0])
    line = _column(np.arange(0, 81))             # span 80
    speck = _column(np.arange(122, 152))         # 42 px after the line, span 29
    other = _column(np.arange(193, 263))         # 42 px after the speck, span 69
    kept = paintcam._runs(np.vstack([other, speck, line]), d)
    assert set(np.round(kept[:, 1]).astype(int)) == set(range(0, 81)) | set(range(193, 263))
    assert np.all(kept[:, 0] == 400.0)

    # 40 px is still one line. 41 px is a break, and a stretch of exactly 60 px is long enough.
    joined = np.vstack([_column(np.arange(0, 81)), _column(np.arange(120, 181))])
    assert len(paintcam._runs(joined, d)) == 81 + 61
    exact = paintcam._runs(np.vstack([_column(np.arange(0, 61)), _column(np.arange(200, 260))]), d)
    assert set(np.round(exact[:, 1]).astype(int)) == set(range(0, 61))
    assert len(paintcam._runs(np.zeros((0, 2)), d)) == 0


def test_scattered_pixels_are_not_a_painted_line():
    # Enough pixels to consult the finder, and not collinear. No line must come back
    # as an empty result: OpenCV 5 reports that as an empty array rather than None.
    rng = np.random.default_rng(0)
    lines = np.zeros((400, 400), np.uint8)
    lines[rng.integers(0, 400, 220), rng.integers(0, 400, 220)] = 255
    region = np.full(lines.shape, 255, np.uint8)
    assert paintcam.detect_lines((lines, region)) == []

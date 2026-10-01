"""Shot-boundary detection from HSV colour histograms.

Two cues, both tuned on the Barcelona-Getafe highlights clip (59.94 fps):
  * hard cut: histogram distance between consecutive frames > HARD_CUT (cuts measured 0.5-0.85,
    in-shot motion incl. fast close-ups stays < 0.2);
  * gradual transition (dissolve/wipe): distance between frames ~0.25 s apart > GRADUAL
    (a wide-shot -> wide-shot dissolve measured 0.38, fast pans <= 0.15).
Frames inside a transition belong to no shot, so nothing is ever tracked across a cut.
"""

import cv2
import numpy as np

HARD_CUT = 0.35
GRADUAL = 0.25
GRADUAL_SPAN_S = 0.25
MIN_SHOT_S = 0.3


def signature(frame):
    """Normalised 32x32 hue/saturation histogram of a downscaled frame."""
    small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    return cv2.normalize(h, h, 1, 0, cv2.NORM_L1)


def _dist(a, b):
    return cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA)


def find_shots(sigs, fps):
    """sigs: per-frame signatures of consecutive frames. Returns [(first, last)] inclusive
    frame indices (into sigs) of each shot, transitions and too-short fragments removed."""
    n = len(sigs)
    if n == 0:
        return []
    k = max(1, round(GRADUAL_SPAN_S * fps))
    cut = np.zeros(n, bool)  # cut[i]: frame i starts a new scene
    for i in range(1, n):
        cut[i] = _dist(sigs[i - 1], sigs[i]) > HARD_CUT
    seg_start = np.maximum.accumulate(np.where(cut | (np.arange(n) == 0), np.arange(n), 0))
    excluded = np.zeros(n, bool)
    for i in range(k, n):
        if seg_start[i] <= i - k and _dist(sigs[i - k], sigs[i]) > GRADUAL:
            excluded[i - k:i + 1] = True  # the change happened somewhere in this span
    shots, start = [], None
    for i in range(n + 1):
        boundary = i == n or excluded[i] or cut[i]
        if boundary and start is not None:
            last = i - 1
            if (last - start + 1) / fps >= MIN_SHOT_S:
                shots.append((start, last))
            start = None
        if i < n and not excluded[i] and start is None:
            start = i
    return shots

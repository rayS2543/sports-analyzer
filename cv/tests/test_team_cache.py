"""The kit model fitted on a wide shot is what later windows reuse.

A close-up must not refit the two teams from a handful of shirts, and a keeper's
kit must not be what tips a window into saving that model.
"""

import json

import numpy as np

from var_cv import analyze
from var_cv.teams import TeamModel


def _feature(bin_index, bgr):
    hist = np.zeros(14)
    hist[bin_index] = 1.0
    return np.sqrt(hist), np.array(bgr, float)


WHITE = _feature(12, (240, 240, 240))
BLUE = _feature(0, (180, 40, 20))


class _People:
    def __init__(self, n, class_id):
        self.class_id = np.full(n, class_id)
        self.xyxy = np.tile(np.array([0.0, 0.0, 40.0, 80.0]), (n, 1))
        self.confidence = np.full(n, 0.9)


def _window(n, class_id=2, calibrated=True):
    feats = [WHITE if i % 2 == 0 else BLUE for i in range(n)]
    return [{"cal": {"ok": calibrated}, "feats": feats, "people": _People(n, class_id)}]


def test_thirty_wide_crops_save_the_kits_and_twenty_nine_do_not(tmp_path):
    cache = tmp_path / "team_model.json"
    short = analyze.team_model(_window(29), cache)
    assert short.predict(WHITE) == "A" and short.predict(BLUE) == "B"
    assert not cache.exists()

    saved = analyze.team_model(_window(30), cache)
    assert saved.predict(WHITE) == "A" and saved.predict(BLUE) == "B"
    assert teams_match(saved, json.loads(cache.read_text()))

    # One of the thirty is a goalkeeper: the outfield count is back to 29, so nothing is saved.
    cache.unlink()
    mixed = _window(29) + _window(1, class_id=1)
    assert analyze.team_model(mixed, cache) is not None
    assert not cache.exists()


def test_a_saved_model_is_reused_and_a_broken_one_is_fitted_again(tmp_path):
    cache = tmp_path / "team_model.json"
    cache.write_text(json.dumps({
        "centres": [WHITE[0].tolist(), BLUE[0].tolist()],
        "radius": 0.2,
        "colours_bgr": [[1, 2, 3], [4, 5, 6]],
    }))
    reused = analyze.team_model(_window(30), cache)
    assert reused.radius == 0.2
    assert reused.colours_bgr[0].tolist() == [1.0, 2.0, 3.0]

    cache.write_text("{")
    refitted = analyze.team_model(_window(30), cache)
    assert refitted.radius != 0.2
    assert refitted.predict(WHITE) == "A"
    assert json.loads(cache.read_text())["radius"] != 0.2


def test_keepers_and_uncalibrated_crops_do_not_become_the_saved_kits(tmp_path):
    cache = tmp_path / "team_model.json"
    assert analyze.team_model(_window(30, class_id=1), cache) is None
    assert not cache.exists()

    fitted = analyze.team_model(_window(30, calibrated=False), cache)
    assert fitted.predict(WHITE) == "A" and fitted.predict(BLUE) == "B"
    assert not cache.exists()


def teams_match(model, payload):
    restored = TeamModel.from_json(payload)
    return restored.predict(WHITE) == model.predict(WHITE) and restored.predict(BLUE) == model.predict(BLUE)

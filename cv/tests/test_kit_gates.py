"""Kit model: too few crops do not invent two teams, and a shirt 3 radii out is neither team."""

import numpy as np

from var_cv import teams


def _crop(signature, bgr):
    return (np.array(signature, np.float64), np.array(bgr, np.float64))


def test_fewer_than_six_crops_do_not_fit_a_model_and_six_separate_the_kits():
    white = _crop([1, 0, 0], [255, 255, 255])
    dark = _crop([0, 0, 1], [20, 20, 20])
    assert teams.fit([white] * 3 + [dark] * 2) is None
    model = teams.fit([white] * 3 + [dark] * 3)
    assert model.predict(white) == "A"  # lighter display colour
    assert model.predict(dark) == "B"


def test_a_kit_is_odd_only_past_three_cluster_radii():
    model = teams.TeamModel([[1.0, 0.0], [0.0, 1.0]], 0.3, [[255, 255, 255], [0, 0, 0]])
    limit = teams.ODD_KIT * model.radius
    on_the_line = (np.array([1.0, limit]), np.zeros(3))
    just_past = (np.array([1.0, np.nextafter(limit, np.inf)]), np.zeros(3))
    assert model.odd(on_the_line) is False
    assert model.odd(just_past) is True

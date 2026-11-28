"""When a player is still the same person after a cut, and where a live position may be filled in.

Offside follows these identities and these positions. A close-up that runs too long, or a
hole between two samples, must not invent someone who was not there.
"""

import numpy as np
import pytest

from var_cv import crossview, reid


def _frame(t, calibrated=True):
    return {"t": t, "calibration": {"ok": calibrated}}


def test_a_live_cut_keeps_its_edge_times_and_stops_after_two_seconds():
    assert reid._live_source([_frame(10.0)], [[_frame(8.0)]], ["wide"]) == "wide"
    assert reid._live_source([_frame(10.0)], [[_frame(7.99)]], ["wide"]) is None

    # The new shot may open with up to half a second uncalibrated. The next hundredth is a close-up.
    assert reid._live_source([_frame(10.0, False), _frame(10.5)], [[_frame(9.0)]], ["wide"]) == "wide"
    assert reid._live_source([_frame(10.0, False), _frame(10.51)], [[_frame(9.0)]], ["wide"]) is None

    # The shot we continue must itself still be calibrated half a second before it ends.
    ending = [_frame(8.0), _frame(8.5, False)]
    assert reid._live_source([_frame(9.0)], [ending], ["wide"]) == "wide"
    ending[-1]["t"] = 8.51
    assert reid._live_source([_frame(9.0)], [ending], ["wide"]) is None

    # A short uncalibrated insert is skipped. One that pushes the live shot more than two
    # seconds back stops the search, even though that older shot was calibrated.
    live = [_frame(6.0), _frame(8.0)]
    short = [_frame(8.1, False), _frame(9.4, False)]
    assert reid._live_source([_frame(9.5)], [live, short], ["live", "close"]) == "live"
    long = [_frame(8.1, False), _frame(10.0, False)]
    assert reid._live_source([_frame(10.1)], [live, long], ["live", "close"]) is None

    assert reid._live_source([_frame(10.0, False)], [[_frame(9.0)]], ["wide"]) is None


def test_a_live_position_is_not_filled_across_a_hole_of_more_than_0_35s():
    track = {"t": np.array([0.0, 0.35]), "xy": np.array([[0.0, 10.0], [10.0, 20.0]]), "sig": np.array([0.2, 0.4])}
    end = track["t"][-1]
    xy, sig = crossview.live_at(track, [0.175, 0.0, end, end + 0.05, -0.05])
    assert xy[0].tolist() == [5.0, 15.0]
    assert sig[0] == pytest.approx(0.3)
    assert np.isfinite(xy[1:]).all() and np.isfinite(sig[1:]).all()
    past = crossview.live_at(track, [end + 0.05 + 0.01, -0.06])[0]
    assert np.isnan(past).all()

    wide = {"t": np.array([0.0, 0.36]), "xy": np.array([[0.0, 0.0], [10.0, 0.0]]), "sig": np.array([0.2, 0.4])}
    hole, hole_sig = crossview.live_at(wide, [0.18, 0.0, 0.36])
    assert np.isnan(hole[0]).all() and np.isnan(hole_sig[0])
    assert hole[1].tolist() == [0.0, 0.0] and hole[2].tolist() == [10.0, 0.0]

    alone = {"t": np.array([1.0]), "xy": np.array([[5.0, 6.0]]), "sig": np.array([0.3])}
    one, one_sig = crossview.live_at(alone, [1.0 - 0.05, 1.0, 1.0 + 0.05, 1.0 - 0.06])
    assert np.isfinite(one[:3]).all() and one_sig[0] == 0.3
    assert np.isnan(one[3]).all()

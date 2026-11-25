"""The analysis window key is the identity of a CV job.

Start and end are rounded to 0.1 s before the 10 s cap is applied, so two
requests for the same moment share one directory. Rounding that swallows or
invents a tenth also moves the moment that offside and foul review judge.
"""

from routes.var_analysis import _window


def test_the_cap_is_applied_to_the_rounded_window():
    assert _window(0, 10) == "0.0-10.0"
    assert _window(0, 10.049) == "0.0-10.0"  # 10.049 s rounds down and still runs
    assert _window(0, 10.05) is None          # 10.05 s rounds up to 10.1 and is refused
    assert _window(0.04, 10.06) is None
    assert _window(0.05, 10.05) == "0.1-10.1"
    assert _window(0.15, 10.15) is None       # 0.1-10.2 is 10.1 s
    assert _window(10.05, 20.05) == "10.1-20.1"


def test_half_tenths_round_to_even_and_keep_one_key():
    # 1.25 and 11.25 are exact halves; half-to-even keeps the span at 10.0 s.
    assert _window(1.25, 11.25) == "1.2-11.2"
    # 1.35 rounds away from the odd tenth. 11.35 is not an exact half and rounds down,
    # so this request is a 9.9 s window, not 10.0.
    assert _window(1.35, 11.35) == "1.4-11.3"
    assert _window(-0.05, 9.95) is None  # rounds to a negative start

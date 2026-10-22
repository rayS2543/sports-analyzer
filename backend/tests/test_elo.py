"""Unit tests for the Elo rating model."""

import math

from elo import (
    HOME_ADVANTAGE,
    INITIAL,
    compute_ratings,
    match_probabilities,
    predict_match,
    ranked_table,
    win_probability,
)


def _match(home, away, hs, aws, day, home_crest=None, away_crest=None):
    return {
        "homeTeam": {"name": home, "crest": home_crest},
        "awayTeam": {"name": away, "crest": away_crest},
        "score": {"fullTime": {"home": hs, "away": aws}},
        "utcDate": f"{day}T18:00:00Z",
    }


def test_compute_ratings_skips_null_scores():
    state = compute_ratings(
        [
            _match("A", "B", None, None, "2024-01-01"),
            _match("A", "B", 1, 0, "2024-01-02"),
        ]
    )
    assert state["played"]["A"] == 1
    assert state["ratings"]["A"] > INITIAL
    assert state["ratings"]["B"] < INITIAL


def test_home_advantage_in_update_softens_home_wins():
    """A home win against equal opponents should not inflate the home side
    as much as an away win would inflate an away side - HA is priced in."""
    home_win = compute_ratings([_match("Home", "Away", 1, 0, "2024-01-01")])
    away_win = compute_ratings([_match("Home", "Away", 0, 1, "2024-01-01")])

    home_gain = home_win["ratings"]["Home"] - INITIAL
    away_gain = away_win["ratings"]["Away"] - INITIAL
    assert away_gain > home_gain > 0


def test_blowout_moves_ratings_more_than_narrow_win():
    narrow = compute_ratings([_match("A", "B", 1, 0, "2024-01-01")])
    blowout = compute_ratings([_match("A", "B", 4, 0, "2024-01-01")])
    assert blowout["ratings"]["A"] > narrow["ratings"]["A"]
    assert blowout["ratings"]["B"] < narrow["ratings"]["B"]


def test_draw_moves_ratings_toward_each_other_when_unequal():
    # Seed unequal ratings via a prior result, then draw.
    seeded = [
        _match("Strong", "Weak", 2, 0, "2024-01-01"),
        _match("Strong", "Weak", 1, 1, "2024-01-08"),
    ]
    after_win = compute_ratings(seeded[:1])
    after_draw = compute_ratings(seeded)
    # Draw: strong side should drop, weak side should rise vs post-win.
    assert after_draw["ratings"]["Strong"] < after_win["ratings"]["Strong"]
    assert after_draw["ratings"]["Weak"] > after_win["ratings"]["Weak"]


def test_match_probabilities_sum_to_100():
    h, d, a = match_probabilities(1600, 1500)
    assert math.isclose(h + d + a, 100.0, abs_tol=0.05)


def test_match_probabilities_favor_higher_rated_home_side():
    h, d, a = match_probabilities(1700, 1400)
    assert h > a
    assert h > d


def test_draw_more_likely_when_teams_are_close():
    _, close_draw, _ = match_probabilities(1500, 1500 + HOME_ADVANTAGE)  # cancel HA
    _, far_draw, _ = match_probabilities(1800, 1400)
    assert close_draw > far_draw


def test_equal_teams_home_favored_due_to_advantage():
    h, d, a = match_probabilities(1500, 1500)
    assert h > a
    assert 20 < d < 35


def test_win_probability_is_draw_renormalized_2way():
    h2, a2 = win_probability(1600, 1500)
    h3, d3, a3 = match_probabilities(1600, 1500)
    assert math.isclose(h2 + a2, 100.0, abs_tol=0.05)
    assert math.isclose(h2 / a2, h3 / a3, rel_tol=0.01)


def test_ranked_table_orders_by_rating():
    state = compute_ratings(
        [
            _match("A", "B", 3, 0, "2024-01-01", home_crest="a.png"),
            _match("A", "C", 2, 0, "2024-01-08", home_crest="a.png"),
        ]
    )
    table = ranked_table(state)
    assert table[0]["team"] == "A"
    assert table[0]["rank"] == 1
    assert table[0]["crest"] == "a.png"
    assert table[0]["played"] == 2
    assert table[0]["delta"] > 0


def test_predict_match_includes_three_way_and_elos():
    state = compute_ratings([_match("A", "B", 2, 0, "2024-01-01")])
    tip = predict_match("A", "B", state)
    assert tip["home_elo"] > tip["away_elo"]
    assert tip["home_win_pct"] > tip["away_win_pct"]
    assert "draw_pct" in tip
    assert tip["predicted_result"] in {"home", "draw", "away"}


def test_upset_swings_ratings_more_than_favorite_win():
    from elo import _mov_multiplier

    assert _mov_multiplier(1, -200) > _mov_multiplier(1, 200)

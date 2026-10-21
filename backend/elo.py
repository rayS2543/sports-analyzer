"""Football Elo rating model for match outcome prediction.

Builds team ratings from finished football-data.org match dicts and turns a
pair of ratings into a home / draw / away probability split.

Accuracy notes (v2)
-------------------
The previous model was a bare chess-style Elo: no home advantage while
updating ratings, no margin-of-victory, and a 2-way win split that ignored
draws (~25% of top-league results). That systematically mis-calibrated
match probabilities.

This version follows the Club Elo / FiveThirtyEight soccer conventions:

- Home advantage is applied both when *updating* ratings and when predicting.
- Margin of victory scales the rating swing (log of goal difference, with a
  diminishing factor when a heavy favorite blows out a weak side).
- Predictions are three-way: draw probability peaks when teams are close and
  falls off as the Elo gap widens; remaining mass is split by the logistic.

Still a lightweight model: single K, no season regression, last-90-days
window only, no xG. Good enough for relative ranking and rough match
lean, not betting-grade calibration.
"""

from __future__ import annotations

import math

INITIAL = 1500
K = 20
HOME_ADVANTAGE = 65
# At equal (home-boosted) strength, top leagues draw ~26-28% of the time.
DRAW_BASE = 0.27
# Elo-gap scale for the Gaussian draw falloff (points).
DRAW_SCALE = 200


def _expected_score(rating_a: float, rating_b: float) -> float:
    """Logistic expected score for A against B (0..1)."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _mov_multiplier(goal_diff: int, winner_minus_loser: float) -> float:
    """FiveThirtyEight-style margin-of-victory multiplier.

    Blowouts move ratings more than 1-0s, but a favorite thrashing a weak
    side is discounted so ratings do not runaway on mismatches.
    """
    gd = abs(int(goal_diff))
    if gd == 0:
        return 1.0
    return math.log(gd + 1.0) * (2.2 / (2.2 + 0.001 * abs(winner_minus_loser)))


def compute_ratings(
    finished_matches,
    initial: float = INITIAL,
    k: float = K,
    home_advantage: float = HOME_ADVANTAGE,
):
    """Compute Elo ratings from finished matches.

    Each match dict looks like a football-data.org match:
    match["homeTeam"]["name"], match["awayTeam"]["name"],
    match["score"]["fullTime"]["home"/"away"], match["utcDate"],
    optional crest on each team.

    Returns a dict:
      {
        "ratings": {team: float},
        "played":  {team: int},
        "crests":  {team: crest_url_or_None},
        "deltas":  {team: rating - initial},
      }
    """
    ratings: dict[str, float] = {}
    played: dict[str, int] = {}
    crests: dict[str, str | None] = {}

    matches = sorted(finished_matches, key=lambda m: m["utcDate"])

    for match in matches:
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        if home_score is None or away_score is None:
            continue

        home_name = match["homeTeam"]["name"]
        away_name = match["awayTeam"]["name"]
        home_crest = match["homeTeam"].get("crest")
        away_crest = match["awayTeam"].get("crest")
        if home_crest:
            crests[home_name] = home_crest
        if away_crest:
            crests[away_name] = away_crest
        crests.setdefault(home_name, home_crest)
        crests.setdefault(away_name, away_crest)

        home_rating = ratings.setdefault(home_name, float(initial))
        away_rating = ratings.setdefault(away_name, float(initial))
        played[home_name] = played.get(home_name, 0) + 1
        played[away_name] = played.get(away_name, 0) + 1

        # Home advantage belongs in the update step, otherwise home wins
        # inflate home teams' "true" strength and away wins do the reverse.
        expected_home = _expected_score(home_rating + home_advantage, away_rating)
        expected_away = 1.0 - expected_home

        if home_score > away_score:
            actual_home, actual_away = 1.0, 0.0
            winner_minus_loser = home_rating - away_rating
        elif away_score > home_score:
            actual_home, actual_away = 0.0, 1.0
            winner_minus_loser = away_rating - home_rating
        else:
            actual_home, actual_away = 0.5, 0.5
            winner_minus_loser = 0.0

        mov = _mov_multiplier(home_score - away_score, winner_minus_loser)
        ratings[home_name] = home_rating + k * mov * (actual_home - expected_home)
        ratings[away_name] = away_rating + k * mov * (actual_away - expected_away)

    deltas = {team: rating - initial for team, rating in ratings.items()}
    return {
        "ratings": ratings,
        "played": played,
        "crests": crests,
        "deltas": deltas,
    }


def match_probabilities(
    home_rating: float,
    away_rating: float,
    home_advantage: float = HOME_ADVANTAGE,
    draw_base: float = DRAW_BASE,
    draw_scale: float = DRAW_SCALE,
):
    """Return (home_win_pct, draw_pct, away_win_pct) as 0-100 floats.

    Draw mass peaks near draw_base when the home-boosted Elo gap is zero and
    falls off as a Gaussian of the gap. Remaining probability is split by the
    standard Elo logistic.
    """
    diff = (home_rating + home_advantage) - away_rating
    p_home_2way = _expected_score(home_rating + home_advantage, away_rating)

    p_draw = draw_base * math.exp(-(diff**2) / (2.0 * draw_scale**2))
    # Soft floor: even mismatches still draw sometimes in football.
    p_draw = max(0.08, min(0.35, p_draw))

    remaining = 1.0 - p_draw
    p_home = remaining * p_home_2way
    p_away = remaining * (1.0 - p_home_2way)
    return p_home * 100.0, p_draw * 100.0, p_away * 100.0


def win_probability(home_rating, away_rating, home_advantage=HOME_ADVANTAGE):
    """Backward-compatible 2-way split (home / away), draw mass excluded.

    Prefer match_probabilities() for new code.
    """
    home, _draw, away = match_probabilities(home_rating, away_rating, home_advantage)
    total = home + away
    if total <= 0:
        return 50.0, 50.0
    return home / total * 100.0, away / total * 100.0


def ranked_table(state, initial: float = INITIAL):
    """Turn a compute_ratings() state into a sorted leaderboard list."""
    ratings = state["ratings"]
    played = state.get("played", {})
    crests = state.get("crests", {})
    deltas = state.get("deltas", {})

    rows = []
    for team, rating in ratings.items():
        rows.append(
            {
                "team": team,
                "crest": crests.get(team),
                "rating": round(rating, 1),
                "played": played.get(team, 0),
                "delta": round(deltas.get(team, rating - initial), 1),
            }
        )
    rows.sort(key=lambda r: (-r["rating"], r["team"]))
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows


def predict_match(home_name, away_name, state, initial: float = INITIAL, home_advantage: float = HOME_ADVANTAGE):
    """Build a prediction dict for one fixture from a rating state."""
    ratings = state["ratings"]
    home_rating = ratings.get(home_name, float(initial))
    away_rating = ratings.get(away_name, float(initial))
    home_pct, draw_pct, away_pct = match_probabilities(home_rating, away_rating, home_advantage)

    outcomes = [
        ("home", home_pct, home_name),
        ("draw", draw_pct, None),
        ("away", away_pct, away_name),
    ]
    outcomes.sort(key=lambda o: -o[1])
    predicted_result, _, predicted_winner = outcomes[0]

    return {
        "home_elo": round(home_rating, 1),
        "away_elo": round(away_rating, 1),
        "home_win_pct": round(home_pct, 1),
        "draw_pct": round(draw_pct, 1),
        "away_win_pct": round(away_pct, 1),
        "predicted_result": predicted_result,
        "predicted_winner": predicted_winner if predicted_result != "draw" else "Draw",
        "elo_gap": round(home_rating + home_advantage - away_rating, 1),
    }

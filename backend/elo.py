"""Simple Elo rating model for predicting match outcomes.

Builds team ratings from a list of finished football-data.org match dicts
and turns a pair of ratings into a win-probability split.
"""


def compute_ratings(finished_matches, initial=1500, k=20):
    """Compute Elo ratings from a list of finished matches.

    Each match dict is expected to look like a football-data.org match:
    match["homeTeam"]["name"], match["awayTeam"]["name"],
    match["score"]["fullTime"]["home"/"away"], match["utcDate"].

    Matches are processed in chronological order (sorted by utcDate).
    Matches with a null score (not actually finished) are skipped.

    Returns a dict of {team_name: rating}, defaulting unseen teams to
    `initial` the moment they first appear.
    """
    ratings = {}

    matches = sorted(finished_matches, key=lambda m: m["utcDate"])

    for match in matches:
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        if home_score is None or away_score is None:
            continue

        home_name = match["homeTeam"]["name"]
        away_name = match["awayTeam"]["name"]

        home_rating = ratings.setdefault(home_name, initial)
        away_rating = ratings.setdefault(away_name, initial)

        expected_home = 1 / (1 + 10 ** ((away_rating - home_rating) / 400))
        expected_away = 1 / (1 + 10 ** ((home_rating - away_rating) / 400))

        if home_score > away_score:
            actual_home, actual_away = 1, 0
        elif away_score > home_score:
            actual_home, actual_away = 0, 1
        else:
            actual_home, actual_away = 0.5, 0.5

        ratings[home_name] = home_rating + k * (actual_home - expected_home)
        ratings[away_name] = away_rating + k * (actual_away - expected_away)

    return ratings


def win_probability(home_rating, away_rating, home_advantage=65):
    """Return (home_win_pct, away_win_pct) as 0-100 floats.

    Uses the standard Elo logistic expectation with a flat home-advantage
    bump added to the home rating before comparing. Simplification (v1):
    this is a straight 2-way split with no separate draw probability.
    """
    boosted_home_rating = home_rating + home_advantage

    expected_home = 1 / (1 + 10 ** ((away_rating - boosted_home_rating) / 400))
    expected_away = 1 - expected_home

    return expected_home * 100, expected_away * 100

# Prediction and Elo rating endpoints.
# See backend/elo.py for the rating model.
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from elo import (
    DRAW_BASE,
    HOME_ADVANTAGE,
    INITIAL,
    K,
    compute_ratings,
    predict_match,
    ranked_table,
)
from football_client import FootballDataError, get
from leagues import DEFAULT_LEAGUE, get_league

predictions_bp = Blueprint("predictions", __name__)

RATING_WINDOW_DAYS = 90


def _league_or_400(league):
    if get_league(league) is None:
        return None, (jsonify({"error": f"Unknown league code '{league}'"}), 400)
    return league, None


def _finished_in_window(league, days=RATING_WINDOW_DAYS):
    """Fetch finished matches for a league and keep the last `days` days."""
    today = datetime.now(timezone.utc).date()
    finished_data = get(f"/competitions/{league}/matches", params={"status": "FINISHED"})
    cutoff = (today - timedelta(days=days)).isoformat()
    matches = [m for m in finished_data.get("matches", []) if m["utcDate"][:10] >= cutoff]
    return matches, today


def compute_predictions_for_league(league):
    finished_matches, today = _finished_in_window(league)
    upcoming_data = get(
        "/matches",
        params={
            "competitions": league,
            # football-data.org marks a fixture TIMED once its kickoff time
            # is confirmed, which is true for most matches within the next
            # 10 days - SCHEDULED alone (no confirmed time yet) misses them.
            "status": "SCHEDULED,TIMED",
            "dateFrom": today.isoformat(),
            "dateTo": (today + timedelta(days=10)).isoformat(),
        },
    )
    state = compute_ratings(finished_matches)
    upcoming_matches = upcoming_data.get("matches", [])

    predictions = []
    for match in upcoming_matches:
        home_name = match["homeTeam"]["name"]
        away_name = match["awayTeam"]["name"]
        tip = predict_match(home_name, away_name, state)

        predictions.append(
            {
                "home": home_name,
                "away": away_name,
                "home_crest": match["homeTeam"].get("crest"),
                "away_crest": match["awayTeam"].get("crest"),
                "date": match["utcDate"][:10],
                **tip,
            }
        )

    predictions.sort(key=lambda p: p["date"])
    return predictions


def compute_ratings_for_league(league, finished_matches=None):
    if finished_matches is None:
        finished_matches, _today = _finished_in_window(league)

    state = compute_ratings(finished_matches)
    table = ranked_table(state)

    return {
        "league": league,
        "window_days": RATING_WINDOW_DAYS,
        "matches_used": len(finished_matches),
        "model": {
            "initial": INITIAL,
            "k": K,
            "home_advantage": HOME_ADVANTAGE,
            "draw_base": DRAW_BASE,
            "includes_draw": True,
            "margin_of_victory": True,
        },
        "ratings": table,
    }


@predictions_bp.route("/predictions")
def get_predictions():
    league = request.args.get("league", DEFAULT_LEAGUE)
    league, err = _league_or_400(league)
    if err:
        return err

    try:
        predictions = compute_predictions_for_league(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    return jsonify(predictions)


@predictions_bp.route("/ratings")
def get_ratings():
    """League Elo table built from the same window as /predictions."""
    league = request.args.get("league", DEFAULT_LEAGUE)
    league, err = _league_or_400(league)
    if err:
        return err

    try:
        ratings = compute_ratings_for_league(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    return jsonify(ratings)

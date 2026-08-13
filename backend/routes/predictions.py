# Prediction endpoints are implemented on top of this blueprint.
# See backend/elo.py for the rating model.
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from elo import compute_ratings, win_probability
from football_client import FootballDataError, get
from leagues import DEFAULT_LEAGUE, get_league

predictions_bp = Blueprint("predictions", __name__)


@predictions_bp.route("/predictions")
def get_predictions():
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    today = datetime.utcnow().date()

    try:
        finished_data = get(
            "/matches",
            params={
                "competitions": league,
                "status": "FINISHED",
                "dateFrom": (today - timedelta(days=90)).isoformat(),
                "dateTo": today.isoformat(),
            },
        )
        upcoming_data = get(
            "/matches",
            params={
                "competitions": league,
                "status": "SCHEDULED",
                "dateFrom": today.isoformat(),
                "dateTo": (today + timedelta(days=10)).isoformat(),
            },
        )
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    finished_matches = finished_data.get("matches", [])
    upcoming_matches = upcoming_data.get("matches", [])

    ratings = compute_ratings(finished_matches)

    predictions = []
    for match in upcoming_matches:
        home_name = match["homeTeam"]["name"]
        away_name = match["awayTeam"]["name"]

        home_rating = ratings.get(home_name, 1500)
        away_rating = ratings.get(away_name, 1500)

        home_win_pct, away_win_pct = win_probability(home_rating, away_rating)
        predicted_winner = home_name if home_win_pct >= away_win_pct else away_name

        predictions.append(
            {
                "home": home_name,
                "away": away_name,
                "date": match["utcDate"][:10],
                "predicted_winner": predicted_winner,
                "home_win_pct": round(home_win_pct, 1),
                "away_win_pct": round(away_win_pct, 1),
            }
        )

    predictions.sort(key=lambda p: p["date"])
    return jsonify(predictions)

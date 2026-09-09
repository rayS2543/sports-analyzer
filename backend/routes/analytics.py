from flask import Blueprint, jsonify, request

import db
from leagues import DEFAULT_LEAGUE, get_league

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/analytics/form/<team_name>")
def get_team_form(team_name):
    """Recent form for a team, built from persisted match history.

    Unlike /matches (a rolling 10-day API window), this reads from the
    local database, which accumulates history every time /matches is
    fetched for a league - so it can report on more than the last 10
    days once enough history has been collected.
    """
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    limit = request.args.get("limit", default=5, type=int)

    matches = db.recent_matches_for_team(team_name, league, limit=limit)
    if not matches:
        return (
            jsonify(
                {
                    "error": "No cached match history for this team yet. "
                    "Fetch /matches for this league first.",
                }
            ),
            404,
        )

    points = sum(
        m["home_points"] if m["home_team"] == team_name else m["away_points"] for m in matches
    )
    form = "".join(
        "W" if m["winner"] == team_name else ("D" if m["winner"] == "Draw" else "L")
        for m in matches
    )

    return jsonify(
        {
            "team": team_name,
            "league": league,
            "matches_considered": len(matches),
            "points": points,
            "form": form,
            "matches": [
                {
                    "date": m["match_date"],
                    "home": m["home_team"],
                    "away": m["away_team"],
                    "score": f'{m["home_score"]} - {m["away_score"]}',
                    "winner": m["winner"],
                }
                for m in matches
            ],
        }
    )

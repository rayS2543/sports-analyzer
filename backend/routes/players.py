from datetime import datetime

from flask import Blueprint, jsonify, request

from api_football_client import ApiFootballError, get
from cache import cached

players_bp = Blueprint("players", __name__)


@cached(ttl_seconds=3600)
def _fetch_player(player_id, season):
    return get("/players", params={"id": player_id, "season": season})


@players_bp.route("/players/<int:player_id>")
def get_player(player_id):
    season = request.args.get("season") or str(datetime.utcnow().year)

    try:
        data = _fetch_player(player_id, season)
    except ApiFootballError as e:
        return jsonify({"error": e.message}), e.status_code

    response = data.get("response", [])
    if not response:
        return jsonify({"error": "Player not found for that season"}), 404

    entry = response[0]
    info = entry.get("player", {})
    stats_list = entry.get("statistics") or []
    season_stats = stats_list[0] if stats_list else {}
    games = season_stats.get("games", {})
    goals = season_stats.get("goals", {})
    cards = season_stats.get("cards", {})
    team = season_stats.get("team", {})

    return jsonify(
        {
            "id": info.get("id"),
            "name": info.get("name"),
            "photo": info.get("photo"),
            "nationality": info.get("nationality"),
            "position": games.get("position"),
            "current_team": team.get("name"),
            "season": season,
            "appearances": games.get("appearences"),
            "goals": goals.get("total"),
            "assists": goals.get("assists"),
            "yellow_cards": cards.get("yellow"),
            "red_cards": cards.get("red"),
            "rating": games.get("rating"),
        }
    )

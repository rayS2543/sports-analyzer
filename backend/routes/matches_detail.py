from flask import Blueprint, jsonify, request

from api_football_client import ApiFootballError, find_fixture_id, get
from cache import cached
from leagues import get_league

matches_detail_bp = Blueprint("matches_detail", __name__)


@cached(ttl_seconds=None)
def _fetch_lineups(fixture_id):
    return get("/fixtures/lineups", params={"fixture": fixture_id})


@cached(ttl_seconds=None)
def _fetch_player_stats(fixture_id):
    return get("/fixtures/players", params={"fixture": fixture_id})


def _build_team(lineup_block, stats_by_player):
    team = lineup_block.get("team", {})

    def build_player(entry, is_starter):
        person = entry.get("player", {})
        stat = stats_by_player.get(person.get("id"), {})
        games = stat.get("games", {})
        goals = stat.get("goals", {})
        cards = stat.get("cards", {})
        return {
            "id": person.get("id"),
            "name": person.get("name"),
            "number": person.get("number"),
            "position": person.get("pos"),
            "starter": is_starter,
            "rating": games.get("rating"),
            "minutes": games.get("minutes"),
            "goals": goals.get("total") or 0,
            "assists": goals.get("assists") or 0,
            "yellow_cards": cards.get("yellow") or 0,
            "red_cards": cards.get("red") or 0,
        }

    starters = [build_player(e, True) for e in lineup_block.get("startXI", [])]
    bench = [build_player(e, False) for e in lineup_block.get("substitutes", [])]

    return {
        "team_name": team.get("name"),
        "formation": lineup_block.get("formation"),
        "starters": starters,
        "bench": bench,
    }


@matches_detail_bp.route("/matches/detail")
def get_match_detail():
    league = request.args.get("league")
    date = request.args.get("date")
    home = request.args.get("home")
    away = request.args.get("away")

    if not league or not date or not home or not away:
        return jsonify({"error": "league, date, home, and away query params are required"}), 400
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    try:
        fixture_id = find_fixture_id(league, date, home, away)
    except ApiFootballError as e:
        return jsonify({"error": e.message}), e.status_code

    if fixture_id is None:
        return jsonify({"available": False, "reason": "Could not match this fixture on API-Football."})

    try:
        lineup_data = _fetch_lineups(fixture_id)
        stats_data = _fetch_player_stats(fixture_id)
    except ApiFootballError as e:
        return jsonify({"error": e.message}), e.status_code

    lineup_response = lineup_data.get("response", [])
    if not lineup_response:
        return jsonify({"available": False, "reason": "Lineup not submitted for this fixture yet."})

    stats_by_player = {}
    for team_block in stats_data.get("response", []):
        for player_entry in team_block.get("players", []):
            person = player_entry.get("player", {})
            stats_list = player_entry.get("statistics") or [{}]
            stats_by_player[person.get("id")] = stats_list[0]

    teams = [_build_team(block, stats_by_player) for block in lineup_response]

    return jsonify(
        {
            "available": True,
            "home": teams[0] if len(teams) > 0 else None,
            "away": teams[1] if len(teams) > 1 else None,
        }
    )

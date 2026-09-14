from flask import Blueprint, jsonify, request

from fotmob_client import FotMobError, POSITION_GROUPS, fetch_lineup, find_fixture
from leagues import get_league

matches_detail_bp = Blueprint("matches_detail", __name__)


def _count_events(performance, event_type):
    return sum(1 for e in (performance.get("events") or []) if e.get("type") == event_type)


def _build_team(team_block):
    def build_player(entry, starter):
        performance = entry.get("performance") or {}
        return {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "number": entry.get("shirtNumber"),
            "position": POSITION_GROUPS.get(entry.get("usualPlayingPositionId")),
            "starter": starter,
            "rating": performance.get("rating"),
            "minutes": None,
            "goals": _count_events(performance, "goal"),
            "assists": _count_events(performance, "assist"),
            "yellow_cards": _count_events(performance, "yellowCard"),
            "red_cards": _count_events(performance, "redCard"),
        }

    starters = [build_player(p, True) for p in team_block.get("starters", [])]
    bench = [build_player(p, False) for p in team_block.get("subs", [])]

    return {
        "team_name": team_block.get("name"),
        "formation": team_block.get("formation"),
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
        fixture = find_fixture(league, date, home, away)
    except FotMobError as e:
        return jsonify({"error": e.message}), e.status_code

    if fixture is None:
        return jsonify({"available": False, "reason": "Could not match this fixture on FotMob."})

    try:
        lineup = fetch_lineup(fixture["page_url"])
    except FotMobError as e:
        return jsonify({"error": e.message}), e.status_code

    if not lineup:
        return jsonify({"available": False, "reason": "Lineup not published for this fixture yet."})

    return jsonify(
        {
            "available": True,
            "home": _build_team(lineup["homeTeam"]),
            "away": _build_team(lineup["awayTeam"]),
        }
    )

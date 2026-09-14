from flask import Blueprint, jsonify, request

from espn_client import EspnError, fetch_lineups, find_event_id
from leagues import get_league

matches_detail_bp = Blueprint("matches_detail", __name__)


def _stat_value(stats, *names):
    for stat in stats or []:
        if stat.get("name") in names or stat.get("abbreviation") in names:
            return stat.get("value")
    return None


def _build_team(roster_block):
    team = roster_block.get("team", {})

    def build_player(entry):
        athlete = entry.get("athlete", {})
        position = entry.get("position") or {}
        stats = entry.get("stats")
        return {
            "id": athlete.get("id"),
            "name": athlete.get("displayName"),
            "number": entry.get("jersey"),
            "position": position.get("abbreviation"),
            "starter": bool(entry.get("starter")),
            "rating": _stat_value(stats, "rating", "playerRating"),
            "minutes": _stat_value(stats, "minutes", "minutesPlayed"),
            "goals": _stat_value(stats, "goals", "totalGoals") or 0,
            "assists": _stat_value(stats, "goalAssists", "totalAssists") or 0,
            "yellow_cards": _stat_value(stats, "yellowCards", "totalYellowCards") or 0,
            "red_cards": _stat_value(stats, "redCards", "totalRedCards") or 0,
        }

    roster = roster_block.get("roster", [])
    starters = [build_player(e) for e in roster if e.get("starter")]
    bench = [build_player(e) for e in roster if not e.get("starter")]

    return {
        "team_name": team.get("displayName"),
        "formation": roster_block.get("formation"),
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
        event_id = find_event_id(league, date, home, away)
    except EspnError as e:
        return jsonify({"error": e.message}), e.status_code

    if event_id is None:
        return jsonify({"available": False, "reason": "Could not match this fixture on ESPN."})

    try:
        data = fetch_lineups(league, event_id)
    except EspnError as e:
        return jsonify({"error": e.message}), e.status_code

    rosters = data.get("rosters") or []
    if not rosters or not any(block.get("roster") for block in rosters):
        return jsonify({"available": False, "reason": "Lineup not published for this fixture yet."})

    teams = [_build_team(block) for block in rosters]

    return jsonify(
        {
            "available": True,
            "home": teams[0] if len(teams) > 0 else None,
            "away": teams[1] if len(teams) > 1 else None,
        }
    )

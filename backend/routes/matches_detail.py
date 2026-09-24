from flask import Blueprint, jsonify, request

from math import isfinite

from fotmob_client import FotMobError, POSITION_GROUPS, fetch_match_content, find_fixture
from leagues import get_league

matches_detail_bp = Blueprint("matches_detail", __name__)


def _count_events(performance, event_type):
    return sum(1 for e in (performance.get("events") or []) if e.get("type") == event_type)


def _coordinate(value, maximum):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and 0 <= value <= maximum


def _build_shots(shotmap):
    if not isinstance(shotmap, dict) or not isinstance(shotmap.get("shots"), list):
        return None
    return [
        {key: shot.get(key) for key in (
            "id", "teamId", "playerId", "playerName", "x", "y", "min", "minAdded",
            "eventType", "isBlocked", "isOnTarget", "expectedGoals", "shotType",
            "situation", "period", "isOwnGoal",
        )}
        for shot in shotmap["shots"]
        if _coordinate(shot.get("x"), 105) and _coordinate(shot.get("y"), 68)
    ]


def _build_team(team_block):
    def build_player(entry, starter):
        performance = entry.get("performance") or {}
        layout = entry.get("verticalLayout") or {}
        return {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "number": entry.get("shirtNumber"),
            "position": POSITION_GROUPS.get(entry.get("usualPlayingPositionId")),
            "starter": starter,
            "captain": bool(entry.get("isCaptain")),
            "pitch_position": {"x": layout["x"], "y": layout["y"]}
            if _coordinate(layout.get("x"), 1) and _coordinate(layout.get("y"), 1) else None,
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
        "id": team_block.get("id"),
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
        content = fetch_match_content(fixture["page_url"])
    except FotMobError as e:
        return jsonify({"error": e.message}), e.status_code

    lineup = content.get("lineup") or {}
    shots = _build_shots(content.get("shotmap"))
    if not lineup.get("homeTeam") or not lineup.get("awayTeam"):
        return jsonify({"available": False, "reason": "Lineup not published for this fixture yet.", "shots": shots})

    return jsonify(
        {
            "available": True,
            "shots": shots,
            "home": {**_build_team(lineup["homeTeam"]), **(content.get("teamAssets") or {}).get("home", {})},
            "away": {**_build_team(lineup["awayTeam"]), **(content.get("teamAssets") or {}).get("away", {})},
        }
    )

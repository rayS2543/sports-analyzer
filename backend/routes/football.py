from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from football_client import FootballDataError, get
from leagues import DEFAULT_LEAGUE, LEAGUES, get_league

football_bp = Blueprint("football", __name__)


@football_bp.route("/leagues")
def list_leagues():
    return jsonify([{"code": code, **info} for code, info in LEAGUES.items()])


@football_bp.route("/matches/today")
def get_todays_matches():
    """Today's fixtures across every supported league, tagged with league info.

    Loops per league (rather than one combined call) so a single league
    being unavailable on the current API plan doesn't take down the rest.
    """
    today = datetime.utcnow().date().isoformat()

    all_matches = []
    for code, info in LEAGUES.items():
        try:
            data = get("/matches", params={"competitions": code, "dateFrom": today, "dateTo": today})
        except FootballDataError:
            continue

        for match in data.get("matches", []):
            all_matches.append(
                {
                    "id": match["id"],
                    "league_code": code,
                    "league_name": info["name"],
                    "home": match["homeTeam"]["name"],
                    "away": match["awayTeam"]["name"],
                    "home_score": match["score"]["fullTime"]["home"],
                    "away_score": match["score"]["fullTime"]["away"],
                    "status": match["status"],
                    "kickoff": match["utcDate"],
                }
            )

    all_matches.sort(key=lambda m: m["kickoff"])
    return jsonify(all_matches)


@football_bp.route("/matches")
def get_matches():
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    today = datetime.utcnow().date()
    date_from = (today - timedelta(days=10)).isoformat()
    date_to = today.isoformat()

    try:
        data = get(
            "/matches",
            params={"competitions": league, "dateFrom": date_from, "dateTo": date_to},
        )
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    if "matches" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleanedData = []
    for match in data["matches"]:
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        if home_score is None or away_score is None:
            continue
        if home_score > away_score:
            winner = match["homeTeam"]["name"]
            home_points, away_points = 3, 0
        elif away_score > home_score:
            winner = match["awayTeam"]["name"]
            home_points, away_points = 0, 3
        else:
            winner = "Draw"
            home_points, away_points = 1, 1
        cleanedData.append(
            {
                "id": match["id"],
                "home": match["homeTeam"]["name"],
                "away": match["awayTeam"]["name"],
                "score": f"{home_score} - {away_score}",
                "winner": winner,
                "home_points": home_points,
                "away_points": away_points,
                "date": match["utcDate"][:10],
            }
        )
    cleanedData.sort(key=lambda m: (m["date"], m["home"], m["away"]))
    return jsonify(cleanedData)


@football_bp.route("/teams")
def get_teams():
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    try:
        data = get(f"/competitions/{league}/teams")
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    if "teams" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleanedData = [
        {
            "name": team["name"],
            "shortName": team["shortName"],
            "tla": team["tla"],
            "crest": team["crest"],
        }
        for team in data["teams"]
    ]
    return jsonify(cleanedData)


@football_bp.route("/standings")
def get_standings():
    """Return the competition standings (ordered by position).

    Uses football-data.org's /competitions/{league}/standings, which
    includes a `position` field for each team. Normalized to a simple
    list of teams with position and common stats.
    """
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    try:
        data = get(f"/competitions/{league}/standings")
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    if "standings" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    # football-data can return multiple standings (TOTAL, HOME, AWAY). We want TOTAL
    total = None
    for s in data["standings"]:
        if s.get("type") == "TOTAL":
            total = s
            break
    if total is None:
        total = data["standings"][0]

    cleaned = []
    for entry in total.get("table", []):
        team = entry.get("team", {})
        cleaned.append(
            {
                "position": entry.get("position"),
                "team_name": team.get("name"),
                "tla": team.get("tla"),
                "crest": team.get("crest"),
                "playedGames": entry.get("playedGames"),
                "won": entry.get("won"),
                "draw": entry.get("draw"),
                "lost": entry.get("lost"),
                "points": entry.get("points"),
                "goalsFor": entry.get("goalsFor"),
                "goalsAgainst": entry.get("goalsAgainst"),
                "goalDifference": entry.get("goalDifference"),
            }
        )

    cleaned.sort(key=lambda e: e.get("position") if e.get("position") is not None else 999)
    return jsonify(cleaned)

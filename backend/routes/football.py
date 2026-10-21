from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import db
from football_client import FootballDataError, get
from fotmob_client import FotMobError, _normalize, champions_league_fixtures
from leagues import DEFAULT_LEAGUE, LEAGUES, get_league

football_bp = Blueprint("football", __name__)

RECENT_RESULTS = 10
CHAMPIONS_LEAGUE = "CL"


def _calendar_day(value):
    """Return YYYY-MM-DD, or None when the value is not a real calendar day."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def _clean_today_match(match, today, fallback_code=None):
    kickoff = match.get("utcDate") or ""
    if kickoff[:10] != today:
        return None

    code = (match.get("competition") or {}).get("code") or fallback_code
    info = get_league(code)
    if info is None:
        return None

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    full_time = (match.get("score") or {}).get("fullTime") or {}
    if not home.get("name") or not away.get("name"):
        return None

    return {
        "id": match.get("id"),
        "league_code": code,
        "league_name": info["name"],
        "home": home.get("name"),
        "away": away.get("name"),
        "home_crest": home.get("crest"),
        "away_crest": away.get("crest"),
        "home_score": full_time.get("home"),
        "away_score": full_time.get("away"),
        "status": match.get("status"),
        "kickoff": kickoff,
    }


@football_bp.route("/leagues")
def list_leagues():
    return jsonify([{"code": code, **info} for code, info in LEAGUES.items()])


@football_bp.route("/matches/today")
def get_todays_matches():
    """Today's fixtures across every supported league, tagged with league info.

    Domestic leagues and Champions League share one football-data.org request.
    UCL is also read from that competition's match list. When neither feed
    includes a Champions League fixture, FotMob's public day list fills it in.
    `date` is the viewer's local calendar day (YYYY-MM-DD); omitted, it is
    today in UTC.
    """
    requested = request.args.get("date")
    if requested is None:
        today = datetime.now(timezone.utc).date().isoformat()
    else:
        today = _calendar_day(requested)
        if today is None:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400

    collected = {}
    primary_error = None

    def add_cleaned(cleaned):
        key = cleaned["id"]
        if key is None:
            key = (cleaned["home"], cleaned["away"], cleaned["kickoff"])
        collected[key] = cleaned

    def absorb(data, fallback_code=None):
        for match in data.get("matches") or []:
            cleaned = _clean_today_match(match, today, fallback_code)
            if cleaned is not None:
                add_cleaned(cleaned)

    try:
        data = get(
            "/matches",
            params={
                "competitions": ",".join(LEAGUES),
                "dateFrom": today,
                "dateTo": today,
                "limit": 100,
            },
        )
        absorb(data)
    except FootballDataError as e:
        primary_error = e

    # The free plan often rejects this resource even when CL is on the list feed.
    try:
        data = get(
            f"/competitions/{CHAMPIONS_LEAGUE}/matches",
            params={"dateFrom": today, "dateTo": today},
        )
        absorb(data, fallback_code=CHAMPIONS_LEAGUE)
    except FootballDataError:
        pass

    seen_cl = {
        (_normalize(m["home"]), _normalize(m["away"]))
        for m in collected.values()
        if m["league_code"] == CHAMPIONS_LEAGUE
    }
    try:
        for fixture in champions_league_fixtures(today):
            pair = (_normalize(fixture["home"]), _normalize(fixture["away"]))
            if pair in seen_cl:
                continue
            seen_cl.add(pair)
            add_cleaned(fixture)
    except FotMobError:
        pass

    if not collected and primary_error:
        return jsonify({"error": primary_error.message}), primary_error.status_code

    all_matches = sorted(collected.values(), key=lambda m: (m["kickoff"], m["home"], m["away"]))
    return jsonify(all_matches)


@football_bp.route("/matches")
def get_matches():
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    try:
        # Same call (and cache entry) /predictions uses for its Elo history.
        data = get(f"/competitions/{league}/matches", params={"status": "FINISHED"})
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
                "home_crest": match["homeTeam"].get("crest"),
                "away_crest": match["awayTeam"].get("crest"),
                "score": f"{home_score} - {away_score}",
                "winner": winner,
                "home_points": home_points,
                "away_points": away_points,
                "date": match["utcDate"][:10],
            }
        )
    cleanedData.sort(key=lambda m: (m["date"], m["home"], m["away"]), reverse=True)
    # Persist the whole season so /analytics/form has history; show only the latest.
    db.upsert_matches(cleanedData, league)
    return jsonify(cleanedData[:RECENT_RESULTS])


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

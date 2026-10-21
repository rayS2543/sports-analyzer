from datetime import datetime

from flask import Blueprint, jsonify, request

import db
from football_client import FootballDataError, get
from leagues import DEFAULT_LEAGUE, LEAGUES, get_league

football_bp = Blueprint("football", __name__)

RECENT_RESULTS = 10
TEAM_RECENT_LIMIT = 8
TEAM_UPCOMING_LIMIT = 5
FORM_LIMIT = 5


def _result_of(home_name, away_name, home_score, away_score):
    if home_score > away_score:
        return home_name, 3, 0
    if away_score > home_score:
        return away_name, 0, 3
    return "Draw", 1, 1


def _clean_finished_match(match):
    home_score = match["score"]["fullTime"]["home"]
    away_score = match["score"]["fullTime"]["away"]
    if home_score is None or away_score is None:
        return None
    winner, home_points, away_points = _result_of(
        match["homeTeam"]["name"], match["awayTeam"]["name"], home_score, away_score
    )
    return {
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


def _clean_upcoming_match(match):
    return {
        "id": match["id"],
        "home": match["homeTeam"]["name"],
        "away": match["awayTeam"]["name"],
        "home_crest": match["homeTeam"].get("crest"),
        "away_crest": match["awayTeam"].get("crest"),
        "date": match["utcDate"][:10],
        "kickoff": match["utcDate"],
        "status": match.get("status", "SCHEDULED"),
        "competition": (match.get("competition") or {}).get("code"),
    }


def _competition_teams(league):
    data = get(f"/competitions/{league}/teams")
    if "teams" not in data:
        raise FootballDataError("Unexpected football-data.org response.", status_code=500)
    return [
        {
            "id": team["id"],
            "name": team["name"],
            "shortName": team["shortName"],
            "tla": team["tla"],
            "crest": team["crest"],
        }
        for team in data["teams"]
    ]


def _find_team(teams, name):
    needle = (name or "").casefold()
    for team in teams:
        if team["name"].casefold() == needle:
            return team
    for team in teams:
        if (team.get("shortName") or "").casefold() == needle:
            return team
    return None


def _standing_for_team(league, team_name):
    data = get(f"/competitions/{league}/standings")
    if "standings" not in data:
        return None

    total = None
    for standing in data["standings"]:
        if standing.get("type") == "TOTAL":
            total = standing
            break
    if total is None and data["standings"]:
        total = data["standings"][0]
    if total is None:
        return None

    needle = team_name.casefold()
    for entry in total.get("table", []):
        team = entry.get("team") or {}
        if (team.get("name") or "").casefold() != needle:
            continue
        return {
            "position": entry.get("position"),
            "playedGames": entry.get("playedGames"),
            "won": entry.get("won"),
            "draw": entry.get("draw"),
            "lost": entry.get("lost"),
            "points": entry.get("points"),
            "goalsFor": entry.get("goalsFor"),
            "goalsAgainst": entry.get("goalsAgainst"),
            "goalDifference": entry.get("goalDifference"),
        }
    return None


def _form_from_matches(team_name, matches, limit=FORM_LIMIT):
    recent = matches[:limit]
    points = sum(
        m["home_points"] if m["home"] == team_name else m["away_points"] for m in recent
    )
    form = "".join(
        "W" if m["winner"] == team_name else ("D" if m["winner"] == "Draw" else "L") for m in recent
    )
    return {
        "form": form,
        "points": points,
        "matches_considered": len(recent),
    }


@football_bp.route("/leagues")
def list_leagues():
    return jsonify([{"code": code, **info} for code, info in LEAGUES.items()])


@football_bp.route("/matches/today")
def get_todays_matches():
    """Today's fixtures across every supported league, tagged with league info.

    One combined request: the free tier allows only 10 calls/minute, and a
    cold dashboard load used to spend 5 of them here.
    """
    today = datetime.utcnow().date().isoformat()

    try:
        data = get("/matches", params={"competitions": ",".join(LEAGUES), "dateFrom": today, "dateTo": today})
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    all_matches = []
    for match in data.get("matches", []):
        code = match["competition"]["code"]
        all_matches.append(
            {
                "id": match["id"],
                "league_code": code,
                "league_name": LEAGUES[code]["name"],
                "home": match["homeTeam"]["name"],
                "away": match["awayTeam"]["name"],
                "home_crest": match["homeTeam"].get("crest"),
                "away_crest": match["awayTeam"].get("crest"),
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

    try:
        # Same call (and cache entry) /predictions uses for its Elo history.
        data = get(f"/competitions/{league}/matches", params={"status": "FINISHED"})
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    if "matches" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleanedData = []
    for match in data["matches"]:
        cleaned = _clean_finished_match(match)
        if cleaned is not None:
            cleanedData.append(cleaned)
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
        cleanedData = _competition_teams(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    return jsonify(cleanedData)


@football_bp.route("/teams/detail")
def get_team_detail():
    """Club profile: meta, table row, form, squad, recent results, and upcoming fixtures.

    Resolves the club by name within a competition, then loads football-data.org's
    /teams/{id} (squad) and /teams/{id}/matches for finished + scheduled games.
    Finished matches are also persisted so /analytics/form stays warm.
    """
    league = request.args.get("league", DEFAULT_LEAGUE)
    name = request.args.get("name", "").strip()
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400
    if not name:
        return jsonify({"error": "Missing team name"}), 400

    try:
        listed = _find_team(_competition_teams(league), name)
        if listed is None:
            return jsonify({"error": f"Team '{name}' not found in {league}"}), 404

        detail = get(f"/teams/{listed['id']}")
        finished_payload = get(
            f"/teams/{listed['id']}/matches",
            params={"status": "FINISHED", "limit": TEAM_RECENT_LIMIT},
        )
        upcoming_payload = get(
            f"/teams/{listed['id']}/matches",
            params={"status": "SCHEDULED", "limit": TEAM_UPCOMING_LIMIT},
        )
        standing = _standing_for_team(league, listed["name"])
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    recent = []
    for match in finished_payload.get("matches") or []:
        cleaned = _clean_finished_match(match)
        if cleaned is None:
            continue
        cleaned["competition"] = (match.get("competition") or {}).get("code")
        recent.append(cleaned)
    recent.sort(key=lambda m: (m["date"], m["home"], m["away"]), reverse=True)

    # Keep league-scoped history warm for /analytics/form when possible.
    league_recent = [m for m in recent if m.get("competition") in (None, league)]
    if league_recent:
        db.upsert_matches(league_recent, league)

    upcoming = [_clean_upcoming_match(m) for m in (upcoming_payload.get("matches") or [])]
    upcoming.sort(key=lambda m: (m["kickoff"], m["home"], m["away"]))

    coach = detail.get("coach") or {}
    squad = [
        {
            "id": player.get("id"),
            "name": player.get("name"),
            "position": player.get("position"),
            "nationality": player.get("nationality"),
            "shirtNumber": player.get("shirtNumber"),
            "dateOfBirth": player.get("dateOfBirth"),
        }
        for player in (detail.get("squad") or [])
    ]
    position_order = {"Goalkeeper": 0, "Defence": 1, "Midfield": 2, "Offence": 3}
    squad.sort(
        key=lambda p: (
            position_order.get(p.get("position"), 9),
            p.get("shirtNumber") is None,
            p.get("shirtNumber") or 0,
            p.get("name") or "",
        )
    )

    form = _form_from_matches(listed["name"], recent)

    return jsonify(
        {
            "id": listed["id"],
            "name": detail.get("name") or listed["name"],
            "shortName": detail.get("shortName") or listed.get("shortName"),
            "tla": detail.get("tla") or listed.get("tla"),
            "crest": detail.get("crest") or listed.get("crest"),
            "founded": detail.get("founded"),
            "venue": detail.get("venue"),
            "clubColors": detail.get("clubColors"),
            "coach": {
                "name": coach.get("name"),
                "nationality": coach.get("nationality"),
            }
            if coach.get("name")
            else None,
            "league": league,
            "standing": standing,
            "form": form["form"],
            "form_points": form["points"],
            "matches_considered": form["matches_considered"],
            "squad": squad,
            "recent_matches": recent,
            "upcoming_matches": upcoming,
        }
    )


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

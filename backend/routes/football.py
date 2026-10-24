from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import db
from football_client import FootballDataError, get
from fotmob_client import FotMobError, _normalize, champions_league_fixtures
from leagues import DEFAULT_LEAGUE, LEAGUES, get_league
from routes.predictions import compute_predictions_for_league, compute_ratings_for_league

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


def _fetch_todays_matches(today):
    collected = {}
    primary_error = None

    def add_cleaned(cleaned):
        # football-data.org and FotMob ids live in different spaces, so key on the fixture itself.
        collected[(cleaned["league_code"], _normalize(cleaned["home"]), _normalize(cleaned["away"]), cleaned["kickoff"][:10])] = cleaned

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
        raise primary_error

    return sorted(collected.values(), key=lambda m: (m["kickoff"], m["home"], m["away"]))


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

    try:
        all_matches = _fetch_todays_matches(today)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    return jsonify(all_matches)


def _fetch_matches(league):
    data = get(f"/competitions/{league}/matches", params={"status": "FINISHED"})
    if "matches" not in data:
        raise FootballDataError("Unexpected API response", status_code=500, data=data)

    cleanedData = []
    for match in data["matches"]:
        cleaned = _clean_finished_match(match)
        if cleaned is not None:
            cleanedData.append(cleaned)
    cleanedData.sort(key=lambda m: (m["date"], m["home"], m["away"]), reverse=True)
    # Persist the whole season so /analytics/form has history; show only the latest.
    db.upsert_matches(cleanedData, league)
    return cleanedData[:RECENT_RESULTS]


@football_bp.route("/matches")
def get_matches():
    league = request.args.get("league", DEFAULT_LEAGUE)
    if get_league(league) is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    try:
        # Same call (and cache entry) /predictions uses for its Elo history.
        cleanedData = _fetch_matches(league)
    except FootballDataError as e:
        body = {"error": e.message}
        if e.data is not None:
            body["data"] = e.data
        return jsonify(body), e.status_code

    return jsonify(cleanedData)


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


def _fetch_standings(league):
    data = get(f"/competitions/{league}/standings")
    if "standings" not in data:
        raise FootballDataError("Unexpected API response", status_code=500, data=data)

    # football-data can return multiple standings (TOTAL, HOME, AWAY). We want TOTAL
    total = None
    for s in data["standings"]:
        if s.get("type") == "TOTAL":
            total = s
            break
    if total is None and data["standings"]:
        total = data["standings"][0]

    if total is None:
        return []

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
    return cleaned


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
        cleaned = _fetch_standings(league)
    except FootballDataError as e:
        body = {"error": e.message}
        if e.data is not None:
            body["data"] = e.data
        return jsonify(body), e.status_code

    return jsonify(cleaned)


@football_bp.route("/dashboard-overview")
def dashboard_overview():
    """Consolidated dashboard overview cutting multiple round-trips to one.

    Combines today's matches, league standings, recent results, Elo ratings,
    match predictions, and team rosters into 1 single response.
    """
    league = request.args.get("league", DEFAULT_LEAGUE)
    league_info = get_league(league)
    if league_info is None:
        return jsonify({"error": f"Unknown league code '{league}'"}), 400

    requested = request.args.get("date")
    if requested is None:
        today = datetime.now(timezone.utc).date().isoformat()
    else:
        today = _calendar_day(requested)
        if today is None:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400

    overview = {
        "league": league,
        "league_name": league_info.get("name"),
        "date": today,
        "leagues": [{"code": code, **info} for code, info in LEAGUES.items()],
    }

    # 1. Today's fixtures across leagues
    try:
        today_matches = _fetch_todays_matches(today)
    except FootballDataError:
        today_matches = []
    overview["today_matches"] = today_matches
    overview["today_games"] = today_matches

    # 2. Standings
    try:
        overview["standings"] = _fetch_standings(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    # 3. Recent matches
    try:
        matches = _fetch_matches(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code
    overview["matches"] = matches
    overview["recent_matches"] = matches

    # 4. Teams roster
    try:
        overview["teams"] = _competition_teams(league)
    except FootballDataError as e:
        return jsonify({"error": e.message}), e.status_code

    # 5. Predictions & Elo Ratings
    try:
        overview["predictions"] = compute_predictions_for_league(league)
    except FootballDataError:
        overview["predictions"] = []

    try:
        overview["ratings"] = compute_ratings_for_league(league)
    except FootballDataError:
        overview["ratings"] = None

    return jsonify(overview)

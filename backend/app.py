from flask import Flask, jsonify, request
from flask_cors import CORS
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

from backend import db

# load API keys and config
load_dotenv()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
CORS(app)

db.init_db()

# football-data.org competition codes we support via ?competition=
ALLOWED_COMPETITIONS = {"PD", "PL", "SA", "BL1", "FL1"}
DEFAULT_COMPETITION = "PD"

CACHE_TTL_SECONDS = int(os.getenv("SPORTS_ANALYZER_CACHE_TTL", "300"))


def _competition_param():
    competition = request.args.get("competition", DEFAULT_COMPETITION).upper()
    if competition not in ALLOWED_COMPETITIONS:
        competition = DEFAULT_COMPETITION
    return competition


def _fetch_with_cache(cache_key, url, headers):
    """Fetch JSON from the upstream API, caching the result.

    Falls back to the last cached payload (however stale) if the upstream
    request fails outright or comes back rate-limited, so a flaky/limited
    football-data.org doesn't take the whole app down.
    Returns (data, error_response) - exactly one of which is not None.
    """
    cached = db.get_cached(cache_key, CACHE_TTL_SECONDS)
    if cached is not None:
        return cached, None

    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as exc:
        stale = db.get_cached(cache_key, None)
        if stale is not None:
            return stale, None
        return None, ({"error": "Upstream API request failed", "detail": str(exc)}, 502)

    if response.status_code == 429:
        stale = db.get_cached(cache_key, None)
        if stale is not None:
            return stale, None
        return None, ({"error": "Rate limited by upstream API"}, 429)

    data = response.json()
    db.set_cached(cache_key, data)
    return data, None


@app.route("/")
def home():
    return jsonify({"message": "Sports Analyzer backend running"})


@app.route("/matches")
def get_matches():
    competition = _competition_param()
    api_key = os.getenv("FOOTBALL_API_KEY")
    today = datetime.utcnow().date()
    date_from = (today - timedelta(days=10)).isoformat()
    date_to = today.isoformat()
    url = (
        f"https://api.football-data.org/v4/matches?competitions={competition}"
        f"&dateFrom={date_from}&dateTo={date_to}"
    )
    headers = {"X-Auth-Token": api_key}

    cache_key = f"matches:{competition}:{date_from}:{date_to}"
    data, error = _fetch_with_cache(cache_key, url, headers)
    if error is not None:
        body, status = error
        return jsonify(body), status

    if "matches" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleanedData = []
    for match in data["matches"]:
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        if home_score > away_score:
            winner = match["homeTeam"]["name"]
            home_points, away_points = 3, 0
        elif away_score > home_score:
            winner = match["awayTeam"]["name"]
            home_points, away_points = 0, 3
        else:
            # draw
            winner = "Draw"
            home_points, away_points = 1, 1
        cleanedData.append({
            "home": match["homeTeam"]["name"],
            "away": match["awayTeam"]["name"],
            "score": f"{home_score} - {away_score}",
            "winner": winner,
            "home_points": home_points,
            "away_points": away_points,
            "date": match["utcDate"][:10],
        })
    # Make results deterministic for debugging (sort by date, then names)
    cleanedData.sort(key=lambda m: (m["date"], m["home"], m["away"]))

    db.upsert_matches(cleanedData, competition)

    return jsonify(cleanedData)


# page to present team stats :P
@app.route("/teams")
def get_teams():
    competition = _competition_param()
    api_key = os.getenv("FOOTBALL_API_KEY")
    url = f"https://api.football-data.org/v4/competitions/{competition}/teams"
    headers = {"X-Auth-Token": api_key}

    cache_key = f"teams:{competition}"
    data, error = _fetch_with_cache(cache_key, url, headers)
    if error is not None:
        body, status = error
        return jsonify(body), status

    if "teams" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500
    cleanedData = []
    for team in data["teams"]:
        cleanedData.append({
            "name": team["name"],
            "shortName": team["shortName"],
            "tla": team["tla"],
            "crest": team["crest"],
        })
    return jsonify(cleanedData)


@app.route("/standings")
def get_standings():
    """Return the competition standings (ordered by position).

    Uses the football-data.org endpoint /competitions/<competition>/standings
    which includes a `position` field for each team. The result is
    normalized to a simple list of teams with position and common stats.
    """
    competition = _competition_param()
    api_key = os.getenv("FOOTBALL_API_KEY")
    url = f"https://api.football-data.org/v4/competitions/{competition}/standings"
    headers = {"X-Auth-Token": api_key}

    cache_key = f"standings:{competition}"
    data, error = _fetch_with_cache(cache_key, url, headers)
    if error is not None:
        body, status = error
        return jsonify(body), status

    if "standings" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    # football-data can return multiple standings (TOTAL, HOME, AWAY). We want TOTAL
    total = None
    for s in data["standings"]:
        if s.get("type") == "TOTAL":
            total = s
            break

    if total is None:
        # fallback to first available standings table
        total = data["standings"][0]

    cleaned = []
    for entry in total.get("table", []):
        team = entry.get("team", {})
        cleaned.append({
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
        })

    # Ensure ordering by position
    cleaned.sort(key=lambda e: e.get("position") if e.get("position") is not None else 999)
    return jsonify(cleaned)


@app.route("/analytics/form/<team_name>")
def get_team_form(team_name):
    """Recent form for a team, built from persisted match history.

    Unlike /matches (a rolling 10-day API window), this reads from the
    local database, which accumulates history every time /matches is
    fetched - so it can report on more than the last 10 days once enough
    history has been collected.
    """
    competition = _competition_param()
    limit = request.args.get("limit", default=5, type=int)

    matches = db.recent_matches_for_team(team_name, competition, limit=limit)
    if not matches:
        return jsonify({
            "error": "No cached match history for this team yet. "
                     "Fetch /matches for this competition first.",
        }), 404

    points = sum(
        m["home_points"] if m["home_team"] == team_name else m["away_points"]
        for m in matches
    )
    form = "".join(
        "W" if m["winner"] == team_name else ("D" if m["winner"] == "Draw" else "L")
        for m in matches
    )

    return jsonify({
        "team": team_name,
        "competition": competition,
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
    })


if __name__ == "__main__":
    app.run(debug=True)

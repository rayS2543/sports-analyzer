"""Sports Analyzer backend.

A small Flask API that proxies and normalizes football-data.org responses
for recent matches, teams, and league standings.
"""
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
CORS(app)

API_BASE_URL = os.getenv("FOOTBALL_API_BASE_URL", "https://api.football-data.org/v4")
COMPETITION = os.getenv("FOOTBALL_COMPETITION", "PD")
REQUEST_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

# Simple in-process cache so repeated requests don't hammer the upstream API
# (football-data.org's free tier is rate limited to 10 requests/minute).
_cache: dict[str, tuple[float, object]] = {}


def _cached_get(cache_key: str, url: str, headers: dict) -> tuple[dict | None, str | None]:
    """Fetch JSON from `url`, using a short-lived in-memory cache.

    Returns a (data, error) tuple; exactly one of the two is set.
    """
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1], None

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return None, f"Upstream request failed: {exc}"

    data = response.json()
    _cache[cache_key] = (now, data)
    return data, None


def _auth_headers() -> dict:
    api_key = os.getenv("FOOTBALL_API_KEY")
    return {"X-Auth-Token": api_key} if api_key else {}


@app.route("/")
def home():
    return jsonify({"message": "Sports Analyzer backend running"})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/matches")
def get_matches():
    if not os.getenv("FOOTBALL_API_KEY"):
        return jsonify({"error": "FOOTBALL_API_KEY is not configured"}), 500

    today = datetime.now(timezone.utc).date()
    date_from = (today - timedelta(days=10)).isoformat()
    date_to = today.isoformat()
    url = (
        f"{API_BASE_URL}/matches"
        f"?competitions={COMPETITION}&dateFrom={date_from}&dateTo={date_to}"
    )

    data, error = _cached_get(f"matches:{date_from}:{date_to}", url, _auth_headers())
    if error:
        return jsonify({"error": error}), 502
    if "matches" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleaned_data = []
    for match in data["matches"]:
        home_score = match["score"]["fullTime"]["home"]
        away_score = match["score"]["fullTime"]["away"]
        if home_score is None or away_score is None:
            # Match hasn't finished yet; skip incomplete fixtures.
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
        cleaned_data.append(
            {
                "home": match["homeTeam"]["name"],
                "away": match["awayTeam"]["name"],
                "score": f"{home_score} - {away_score}",
                "winner": winner,
                "home_points": home_points,
                "away_points": away_points,
                "date": match["utcDate"][:10],
            }
        )

    cleaned_data.sort(key=lambda m: (m["date"], m["home"], m["away"]))
    return jsonify(cleaned_data)


@app.route("/teams")
def get_teams():
    if not os.getenv("FOOTBALL_API_KEY"):
        return jsonify({"error": "FOOTBALL_API_KEY is not configured"}), 500

    url = f"{API_BASE_URL}/competitions/{COMPETITION}/teams"
    data, error = _cached_get("teams", url, _auth_headers())
    if error:
        return jsonify({"error": error}), 502
    if "teams" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    cleaned_data = [
        {
            "name": team["name"],
            "shortName": team["shortName"],
            "tla": team["tla"],
            "crest": team["crest"],
        }
        for team in data["teams"]
    ]
    return jsonify(cleaned_data)


@app.route("/standings")
def get_standings():
    """Return the competition standings (ordered by position).

    Uses the football-data.org endpoint /competitions/{COMPETITION}/standings
    which includes a `position` field for each team. The result is
    normalized to a simple list of teams with position and common stats.
    """
    if not os.getenv("FOOTBALL_API_KEY"):
        return jsonify({"error": "FOOTBALL_API_KEY is not configured"}), 500

    url = f"{API_BASE_URL}/competitions/{COMPETITION}/standings"
    data, error = _cached_get("standings", url, _auth_headers())
    if error:
        return jsonify({"error": error}), 502
    if "standings" not in data:
        return jsonify({"error": "Unexpected API response", "data": data}), 500

    total = next((s for s in data["standings"] if s.get("type") == "TOTAL"), None)
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


if __name__ == "__main__":
    app.run(debug=True)

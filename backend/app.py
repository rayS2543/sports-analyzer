from flask import Flask, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta

# load API keys and config
load_dotenv()

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
CORS(app)

@app.route("/")
def home():
    return jsonify({"message": "Sports Analyzer backend running"})

@app.route("/matches")
def get_matches():
    api_key = os.getenv("FOOTBALL_API_KEY")
    #url = "https://api.football-data.org/v4/matches?status=FINISHED" last 3 matches in PD PL and ISA
    today = datetime.utcnow().date()
    date_from = (today - timedelta(days=10)).isoformat()
    date_to = today.isoformat()
    url = f"https://api.football-data.org/v4/matches?competitions=PD&dateFrom={date_from}&dateTo={date_to}"
    headers = {"X-Auth-Token": api_key}

    response = requests.get(url, headers=headers)
    data = response.json()

    if "matches" not in data:
        return jsonify({"error" : "Unexpected API response", "data": data }) , 500

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

    # Debug: print the first three matches so you can see what the API returned
    """
    for i, m in enumerate(cleanedData[:3]):
        print(f"[{i}] {m['date']} | {m['home']} vs {m['away']} -> {m['score']}")
    """
    return jsonify(cleanedData)

#page to present team stats :P
@app.route("/teams")
def get_teams():
    api_key = os.getenv("FOOTBALL_API_KEY")
    url = "https://api.football-data.org/v4/competitions/PD/teams"
    headers = {"X-Auth-Token": api_key}

    response = requests.get(url, headers=headers)
    data = response.json()

    if "teams" not in data:
        return jsonify({"error" : "Unexpected API response", "data": data }) , 500
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

    Uses the football-data.org endpoint /competitions/PD/standings which
    includes a `position` field for each team. The result is normalized to
    a simple list of teams with position and common stats.
    """
    api_key = os.getenv("FOOTBALL_API_KEY")
    url = "https://api.football-data.org/v4/competitions/PD/standings"
    headers = {"X-Auth-Token": api_key}

    response = requests.get(url, headers=headers)
    data = response.json()

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
    




if __name__ == "__main__":
    app.run(debug=True)
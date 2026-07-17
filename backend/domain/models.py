"""Pure functions that shape raw provider payloads into the platform's
plain-dict domain representation. Kept separate from adapters (which
know how to fetch) and repositories (which know how to orchestrate).
"""


def standing_entry_to_dict(entry):
    team = entry.get("team", {})
    return {
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


def match_to_result_summary(match):
    home_score = match["score"]["fullTime"]["home"]
    away_score = match["score"]["fullTime"]["away"]
    if home_score > away_score:
        winner = match["homeTeam"]["name"]
        home_points, away_points = 3, 0
    elif away_score > home_score:
        winner = match["awayTeam"]["name"]
        home_points, away_points = 0, 3
    else:
        winner = "Draw"
        home_points, away_points = 1, 1

    return {
        "home": match["homeTeam"]["name"],
        "away": match["awayTeam"]["name"],
        "score": f"{home_score} - {away_score}",
        "winner": winner,
        "home_points": home_points,
        "away_points": away_points,
        "date": match["utcDate"][:10],
    }


def match_to_team_form_entry(match, team_id):
    home_team_id = match["homeTeam"]["id"]
    home_score = match["score"]["fullTime"]["home"]
    away_score = match["score"]["fullTime"]["away"]

    if team_id == home_team_id:
        result = "Win" if home_score > away_score else "Loss" if home_score < away_score else "Draw"
    else:
        result = "Win" if away_score > home_score else "Loss" if away_score < home_score else "Draw"

    return {
        "home": match["homeTeam"]["name"],
        "away": match["awayTeam"]["name"],
        "score": f"{home_score} - {away_score}",
        "result": result,
        "date": match["utcDate"][:10],
    }

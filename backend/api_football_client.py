import os
import re

import requests

from cache import cached

BASE_URL = "https://v3.football.api-sports.io"

# API-Football's numeric league IDs for our 5 supported competitions.
# Cross-check against API-Football's own /leagues endpoint once a real
# key exists — these are not something this sandbox can verify live.
LEAGUE_ID_MAP = {
    "PD": 140,  # La Liga
    "PL": 39,  # Premier League
    "SA": 135,  # Serie A
    "BL1": 78,  # Bundesliga
    "FL1": 61,  # Ligue 1
}


class ApiFootballError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _headers():
    return {"x-apisports-key": os.getenv("API_FOOTBALL_KEY")}


def get(path, params=None):
    """GET an endpoint under API-Football's v3 API.

    Mirrors football_client.get()'s error-handling shape so route
    handlers deal with one consistent error type regardless of provider.
    """
    try:
        response = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        raise ApiFootballError(f"Could not reach api-football.com: {e}", status_code=502)

    if response.status_code == 403:
        raise ApiFootballError("This request isn't available on the current API-Football plan.", status_code=403)
    if response.status_code == 429:
        raise ApiFootballError(
            "API-Football rate limit hit (free tier is 100 requests/day), please try again later.",
            status_code=429,
        )
    if not response.ok:
        raise ApiFootballError(f"Unexpected API-Football response ({response.status_code}).", status_code=502)

    data = response.json()
    if data.get("errors"):
        # API-Football returns HTTP 200 with an "errors" payload for bad
        # requests (e.g. an invalid/expired key), so check it explicitly.
        raise ApiFootballError(f"API-Football error: {data['errors']}", status_code=502)
    return data


def _normalize(name):
    name = (name or "").lower()
    for suffix in (" fc", "fc ", " cf", "cf ", " sad", " ac", "ac "):
        name = name.replace(suffix, " ")
    return re.sub(r"\s+", " ", name).strip()


@cached(ttl_seconds=None)
def find_fixture_id(league_code, date, home_name, away_name):
    """Resolve a football-data.org (league, date, home, away) match to an
    API-Football fixture id by fetching that league's fixtures on that
    date and matching normalized team names.

    Returns None for "no confident match" (unmapped league, name mismatch,
    or no fixture that day) rather than raising — that's an expected,
    common outcome the caller should treat as an empty state.
    """
    league_id = LEAGUE_ID_MAP.get(league_code)
    if league_id is None:
        return None

    season = date[:4]
    data = get("/fixtures", params={"league": league_id, "season": season, "date": date})

    home_norm = _normalize(home_name)
    away_norm = _normalize(away_name)

    for fixture in data.get("response", []):
        teams = fixture.get("teams", {})
        fixture_home = _normalize(teams.get("home", {}).get("name"))
        fixture_away = _normalize(teams.get("away", {}).get("name"))
        if fixture_home == home_norm and fixture_away == away_norm:
            return fixture["fixture"]["id"]

    return None

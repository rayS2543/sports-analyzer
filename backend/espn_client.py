import re

import requests

from cache import cached

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# ESPN's undocumented but free, keyless "site API" league slugs for our 5
# supported competitions. No account or API key required.
LEAGUE_SLUG_MAP = {
    "PD": "esp.1",  # La Liga
    "PL": "eng.1",  # Premier League
    "SA": "ita.1",  # Serie A
    "BL1": "ger.1",  # Bundesliga
    "FL1": "fra.1",  # Ligue 1
}


class EspnError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get(path, params=None):
    """GET an endpoint under ESPN's public site API.

    This is an unofficial, unauthenticated API (no key, no rate-limit
    documentation) that ESPN's own web/app clients use, so it can change
    or start blocking us without notice. Treat it as a best-effort free
    fallback, not a guaranteed data source.
    """
    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        raise EspnError(f"Could not reach ESPN: {e}", status_code=502)

    if not response.ok:
        raise EspnError(f"Unexpected ESPN response ({response.status_code}).", status_code=502)

    return response.json()


def _normalize(name):
    name = (name or "").lower()
    for suffix in (" fc", "fc ", " cf", "cf ", " sad", " ac", "ac "):
        name = name.replace(suffix, " ")
    return re.sub(r"\s+", " ", name).strip()


@cached(ttl_seconds=None)
def find_event_id(league_code, date, home_name, away_name):
    """Resolve a (league, date, home, away) match to an ESPN event id by
    scanning that league's scoreboard on that date and matching normalized
    team names.

    Returns None for "no confident match" (unmapped league, name mismatch,
    or no event that day) rather than raising — an expected, common outcome
    the caller should treat as an empty state.
    """
    slug = LEAGUE_SLUG_MAP.get(league_code)
    if slug is None:
        return None

    data = get(f"/{slug}/scoreboard", params={"dates": date.replace("-", "")})

    home_norm = _normalize(home_name)
    away_norm = _normalize(away_name)

    for event in data.get("events", []):
        competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
        event_home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        event_away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        if (
            _normalize((event_home.get("team") or {}).get("displayName")) == home_norm
            and _normalize((event_away.get("team") or {}).get("displayName")) == away_norm
        ):
            return event.get("id")

    return None


@cached(ttl_seconds=None)
def fetch_lineups(league_code, event_id):
    slug = LEAGUE_SLUG_MAP.get(league_code)
    return get(f"/{slug}/summary", params={"event": event_id})

import os

import requests

from cache import cached

BASE_URL = "https://api.football-data.org/v4"


class FootballDataError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _headers():
    api_key = os.getenv("FOOTBALL_API_KEY")
    return {"X-Auth-Token": api_key}


@cached(ttl_seconds=180)
def get(path, params=None):
    """GET an endpoint under football-data.org's v4 API.

    Raises FootballDataError with a clean message on non-2xx responses,
    including the free-tier 403 you get for competitions outside the
    current plan, so route handlers don't need to special-case it.

    Cached for 3 minutes (keyed by path + params) since football-data.org's
    free tier rate-limits hard and every dashboard load fans out to
    /matches, /teams, and /standings at once.
    """
    try:
        response = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        raise FootballDataError(f"Could not reach football-data.org: {e}", status_code=502)

    if response.status_code == 403:
        raise FootballDataError(
            "This competition isn't available on the current football-data.org plan.",
            status_code=403,
        )
    if response.status_code == 429:
        raise FootballDataError(
            "football-data.org rate limit hit, please try again shortly.",
            status_code=429,
        )
    if not response.ok:
        raise FootballDataError(
            f"Unexpected football-data.org response ({response.status_code}).",
            status_code=502,
        )

    return response.json()

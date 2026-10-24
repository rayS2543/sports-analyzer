import json
import os
import threading

import requests

import db

BASE_URL = "https://api.football-data.org/v4"

TTL_TEAMS = 86400  # 24h
TTL_STANDINGS = 1800  # 30m
TTL_FINISHED_MATCHES = 86400  # 24h
TTL_LIVE_FIXTURES = 60  # 60s
DEFAULT_TTL = 180  # 3m

_locks = {}
_locks_guard = threading.Lock()


def _get_lock(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


class FootballDataError(Exception):
    def __init__(self, message, status_code=502, data=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data


def _headers():
    api_key = os.getenv("FOOTBALL_API_KEY")
    return {"X-Auth-Token": api_key}


def _cache_key(path, params):
    if params:
        normalized = json.dumps(params, sort_keys=True, default=str)
        return f"{path}?{normalized}"
    return path


def _resolve_ttl(path, params):
    if "/teams" in path and "/matches" not in path:
        return TTL_TEAMS
    if "/standings" in path:
        return TTL_STANDINGS
    if params and params.get("status") == "FINISHED":
        return TTL_FINISHED_MATCHES
    if params and params.get("dateFrom") and params.get("dateFrom") == params.get("dateTo"):
        return TTL_LIVE_FIXTURES
    return DEFAULT_TTL


def get(path, params=None, ttl_seconds=None):
    """GET an endpoint under football-data.org's v4 API backed by SQLite SWR cache.

    - If fresh (< TTL), returns in <1ms without hitting upstream.
    - Tailored TTLs:
        - Teams: 86,400s (24h)
        - Standings: 1,800s (30m)
        - Finished matches: 86,400s (24h)
        - Today's live fixtures: 60s
    - On 429 (Rate Limit) or network failure:
        - Returns stale cached data if present (stale-while-revalidate).
        - Raises FootballDataError if cold cache.
    """
    cache_key = _cache_key(path, params)
    cached_data, is_stale = db.cache_get(cache_key)

    if cached_data is not None and not is_stale:
        return cached_data

    lock = _get_lock(cache_key)
    with lock:
        # Re-check cache inside lock to coalesce concurrent identical requests
        cached_data, is_stale = db.cache_get(cache_key)
        if cached_data is not None and not is_stale:
            return cached_data

        ttl = ttl_seconds if ttl_seconds is not None else _resolve_ttl(path, params)

        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                headers=_headers(),
                params=params,
                timeout=10,
            )
        except requests.exceptions.RequestException as e:
            if cached_data is not None:
                return cached_data
            raise FootballDataError(f"Could not reach football-data.org: {e}", status_code=502)

        if response.status_code == 403:
            raise FootballDataError(
                "This competition isn't available on the current football-data.org plan.",
                status_code=403,
            )
        if response.status_code == 429:
            if cached_data is not None:
                return cached_data
            raise FootballDataError(
                "football-data.org rate limit hit, please try again shortly.",
                status_code=429,
            )
        if not response.ok:
            if cached_data is not None:
                return cached_data
            raise FootballDataError(
                f"Unexpected football-data.org response ({response.status_code}).",
                status_code=502,
            )

        try:
            data = response.json()
        except Exception as e:
            if cached_data is not None:
                return cached_data
            raise FootballDataError(f"Invalid JSON from football-data.org: {e}", status_code=502)

        db.cache_set(cache_key, data, ttl)
        return data

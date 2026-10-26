from datetime import date, timedelta
from unittest.mock import patch
import pytest
import requests

import db
import football_client
from football_client import (
    DEFAULT_TTL,
    TTL_FINISHED_MATCHES,
    TTL_LIVE_FIXTURES,
    TTL_STANDINGS,
    TTL_TEAMS,
    FootballDataError,
    _resolve_ttl,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


def test_db_cache_basic_lifecycle():
    assert db.cache_get("non_existent_key") == (None, True)

    db.cache_set("test_key", {"hello": "world"}, ttl_seconds=60)
    data, is_stale = db.cache_get("test_key")
    assert data == {"hello": "world"}
    assert is_stale is False

    db.cache_clear()
    assert db.cache_get("test_key") == (None, True)


def test_db_cache_expiration():
    db.cache_set("expired_key", {"msg": "old"}, ttl_seconds=-5)
    data, is_stale = db.cache_get("expired_key")
    assert data == {"msg": "old"}
    assert is_stale is True


def test_db_cache_indefinite():
    db.cache_set("eternal_key", [1, 2, 3], ttl_seconds=None)
    data, is_stale = db.cache_get("eternal_key")
    assert data == [1, 2, 3]
    assert is_stale is False


def test_db_reset_db_clears_cache():
    db.cache_set("temp_key", "val", ttl_seconds=100)
    db.reset_db()
    data, is_stale = db.cache_get("temp_key")
    assert data is None
    assert is_stale is True


def test_tailored_ttls_resolution():
    assert _resolve_ttl("/competitions/PD/teams", None) == TTL_TEAMS
    assert _resolve_ttl("/teams/86", None) == TTL_TEAMS
    assert _resolve_ttl("/competitions/PD/standings", None) == TTL_STANDINGS
    assert _resolve_ttl("/competitions/PD/matches", {"status": "FINISHED"}) == TTL_FINISHED_MATCHES
    assert (
        _resolve_ttl("/matches", {"dateFrom": "2026-10-23", "dateTo": "2026-10-23"})
        == TTL_LIVE_FIXTURES
    )
    assert _resolve_ttl("/some/other/endpoint", None) == DEFAULT_TTL


def test_football_client_get_caches_and_serves_hit():
    payload = {"teams": [{"id": 1, "name": "Real Madrid"}]}
    with patch("football_client.requests.get", return_value=FakeResponse(payload)) as mock_req:
        res1 = football_client.get("/competitions/PD/teams")
        assert res1 == payload
        assert mock_req.call_count == 1

        # Second call hits SQLite cache without network
        res2 = football_client.get("/competitions/PD/teams")
        assert res2 == payload
        assert mock_req.call_count == 1


def test_football_client_swr_serves_stale_snapshot_on_429():
    key = "/competitions/PD/teams"
    stale_payload = {"teams": [{"id": 1, "name": "Real Madrid (Stale)"}]}
    db.cache_set(key, stale_payload, ttl_seconds=-10)

    with patch(
        "football_client.requests.get",
        return_value=FakeResponse({"error": "rate limit"}, status_code=429),
    ) as mock_req:
        res = football_client.get(key)
        assert res == stale_payload
        assert mock_req.call_count == 1


def test_football_client_cold_cache_raises_429():
    with patch(
        "football_client.requests.get",
        return_value=FakeResponse({"error": "rate limit"}, status_code=429),
    ):
        with pytest.raises(FootballDataError) as exc_info:
            football_client.get("/competitions/PD/standings")
        assert exc_info.value.status_code == 429


def test_football_client_swr_serves_stale_snapshot_on_network_error():
    key = "/competitions/PD/matches"
    stale_payload = {"matches": [{"id": 10, "homeTeam": {"name": "Barca"}}]}
    db.cache_set(key, stale_payload, ttl_seconds=-10)

    with patch(
        "football_client.requests.get",
        side_effect=requests.ConnectionError("Connection dropped"),
    ) as mock_req:
        res = football_client.get(key)
        assert res == stale_payload
        assert mock_req.call_count == 1


def test_football_client_cold_cache_raises_502_on_network_error():
    with patch(
        "football_client.requests.get",
        side_effect=requests.ConnectionError("Connection dropped"),
    ):
        with pytest.raises(FootballDataError) as exc_info:
            football_client.get("/competitions/PD/matches")
        assert exc_info.value.status_code == 502


def test_dashboard_overview_success(client):
    today_iso = "2026-10-23"
    finished_match = {
        "id": 101,
        "homeTeam": {"name": "Barcelona", "crest": "barca.png"},
        "awayTeam": {"name": "Real Madrid", "crest": "real.png"},
        "score": {"fullTime": {"home": 2, "away": 1}},
        "utcDate": f"{today_iso}T15:00:00Z",
        "status": "FINISHED",
    }
    upcoming_match = {
        "id": 102,
        "homeTeam": {"name": "Sevilla", "crest": "sevilla.png"},
        "awayTeam": {"name": "Valencia", "crest": "valencia.png"},
        "score": {"fullTime": {"home": None, "away": None}},
        "utcDate": f"{today_iso}T20:00:00Z",
        "status": "SCHEDULED",
        "competition": {"code": "PD"},
    }
    standings_payload = {
        "standings": [
            {
                "type": "TOTAL",
                "table": [
                    {
                        "position": 1,
                        "team": {"name": "Barcelona", "tla": "BAR", "crest": "barca.png"},
                        "playedGames": 10,
                        "won": 8,
                        "draw": 1,
                        "lost": 1,
                        "points": 25,
                        "goalsFor": 24,
                        "goalsAgainst": 8,
                        "goalDifference": 16,
                    }
                ],
            }
        ]
    }
    teams_payload = {
        "teams": [
            {
                "id": 1,
                "name": "Barcelona",
                "shortName": "Barça",
                "tla": "BAR",
                "crest": "barca.png",
            }
        ]
    }

    def fake_get(url, headers=None, params=None, timeout=10):
        if "/standings" in url:
            return FakeResponse(standings_payload)
        if "/teams" in url:
            return FakeResponse(teams_payload)
        if params and params.get("status") == "FINISHED":
            return FakeResponse({"matches": [finished_match]})
        if params and params.get("status") == "SCHEDULED,TIMED":
            return FakeResponse({"matches": [upcoming_match]})
        if params and params.get("dateFrom") == today_iso:
            return FakeResponse({"matches": [upcoming_match]})
        return FakeResponse({"matches": []})

    with (
        patch("football_client.requests.get", side_effect=fake_get),
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp = client.get(f"/dashboard-overview?league=PD&date={today_iso}")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["league"] == "PD"
    assert data["league_name"] == "La Liga"
    assert data["date"] == today_iso
    assert isinstance(data["leagues"], list)
    assert len(data["leagues"]) > 0

    assert isinstance(data["today_matches"], list)
    assert isinstance(data["standings"], list)
    assert len(data["standings"]) == 1
    assert data["standings"][0]["team_name"] == "Barcelona"

    assert isinstance(data["matches"], list)
    assert len(data["matches"]) == 1
    assert data["matches"][0]["winner"] == "Barcelona"

    assert isinstance(data["teams"], list)
    assert len(data["teams"]) == 1
    assert data["teams"][0]["shortName"] == "Barça"

    assert isinstance(data["predictions"], list)
    assert isinstance(data["ratings"], dict)
    assert "ratings" in data["ratings"]


def test_dashboard_overview_invalid_league(client):
    resp = client.get("/dashboard-overview?league=INVALID")
    assert resp.status_code == 400
    assert "Unknown league code" in resp.get_json()["error"]


def test_dashboard_overview_invalid_date(client):
    resp = client.get("/dashboard-overview?league=PD&date=23-10-2026")
    assert resp.status_code == 400
    assert "date must be YYYY-MM-DD" in resp.get_json()["error"]


def test_dashboard_overview_swr_resilience_on_rate_limit(client):
    today_iso = "2026-10-23"
    finished_match = {
        "id": 101,
        "homeTeam": {"name": "Barcelona", "crest": "barca.png"},
        "awayTeam": {"name": "Real Madrid", "crest": "real.png"},
        "score": {"fullTime": {"home": 2, "away": 1}},
        "utcDate": f"{today_iso}T15:00:00Z",
        "status": "FINISHED",
    }
    standings_payload = {
        "standings": [
            {
                "type": "TOTAL",
                "table": [
                    {
                        "position": 1,
                        "team": {"name": "Barcelona", "tla": "BAR", "crest": "barca.png"},
                        "playedGames": 10,
                        "won": 8,
                        "draw": 1,
                        "lost": 1,
                        "points": 25,
                        "goalsFor": 24,
                        "goalsAgainst": 8,
                        "goalDifference": 16,
                    }
                ],
            }
        ]
    }
    teams_payload = {
        "teams": [
            {"id": 1, "name": "Barcelona", "shortName": "Barça", "tla": "BAR", "crest": "barca.png"}
        ]
    }

    def fake_get(url, headers=None, params=None, timeout=10):
        if "/standings" in url:
            return FakeResponse(standings_payload)
        if "/teams" in url:
            return FakeResponse(teams_payload)
        if params and params.get("status") == "FINISHED":
            return FakeResponse({"matches": [finished_match]})
        return FakeResponse({"matches": []})

    with (
        patch("football_client.requests.get", side_effect=fake_get),
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp1 = client.get(f"/dashboard-overview?league=PD&date={today_iso}")
        assert resp1.status_code == 200

    # Expire all cached entries in SQLite to force revalidation
    with db.get_connection() as conn:
        conn.execute("UPDATE api_cache SET expires_at = 0")

    # Now upstream returns 429 for all calls
    with (
        patch(
            "football_client.requests.get",
            return_value=FakeResponse({"error": "rate limit"}, status_code=429),
        ),
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp2 = client.get(f"/dashboard-overview?league=PD&date={today_iso}")
        assert resp2.status_code == 200
        data = resp2.get_json()
        assert len(data["standings"]) == 1
        assert len(data["teams"]) == 1
        assert len(data["matches"]) == 1

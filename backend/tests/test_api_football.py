"""API-Football errors and fixture identity, plus the player page that depends on them."""

import pytest
import requests

import api_football_client
from api_football_client import ApiFootballError, ApiFootballPlanRestrictedError, find_fixture_id, get
from routes import players as player_routes


class _Response:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload


def _install(monkeypatch, payload=None, status_code=200, error=None):
    def fake_get(url, headers=None, params=None, timeout=10):
        fake_get.calls.append({"url": url, "params": params})
        if error is not None:
            raise error
        return _Response(payload, status_code)

    fake_get.calls = []
    monkeypatch.setattr(api_football_client.requests, "get", fake_get)
    return fake_get


@pytest.mark.parametrize(
    "status,payload,error,exc_type,code,fragment",
    [
        (None, None, requests.ConnectionError("down"), ApiFootballError, 502, "Could not reach"),
        (403, {}, None, ApiFootballError, 403, "isn't available"),
        (429, {}, None, ApiFootballError, 429, "rate limit"),
        (500, {}, None, ApiFootballError, 502, "Unexpected API-Football"),
        (200, {"errors": {"access": "Invalid api key"}}, None, ApiFootballError, 502, "Invalid api key"),
        (200, {"errors": ["bad token"]}, None, ApiFootballError, 502, "bad token"),
        (
            200,
            {"errors": {"plan": "Your plan does not include this endpoint."}},
            None,
            ApiFootballError,
            502,
            "does not include",
        ),
    ],
)
def test_get_classifies_transport_and_plan_failures(monkeypatch, status, payload, error, exc_type, code, fragment):
    _install(monkeypatch, payload, status or 200, error)
    with pytest.raises(exc_type) as caught:
        get("/players", params={"id": 1})
    assert type(caught.value) is exc_type
    assert caught.value.status_code == code
    assert fragment in caught.value.message


def test_a_season_plan_limit_stays_distinct_from_a_missing_fixture(monkeypatch):
    calls = _install(
        monkeypatch,
        {"errors": {"plan": "Free plans do not have access to this season."}},
    )
    with pytest.raises(ApiFootballPlanRestrictedError) as caught:
        find_fixture_id("PD", "2026-10-28", "FC Barcelona", "Real Madrid CF")
    assert caught.value.status_code == 200
    assert "season" in caught.value.message
    assert calls.calls  # the limit is a real response, not "no fixture that day"


def test_fixture_id_ignores_legal_suffixes_but_not_a_different_club(monkeypatch):
    def fixture(id_, home, away):
        return {"fixture": {"id": id_}, "teams": {"home": {"name": home}, "away": {"name": away}}}

    calls = _install(
        monkeypatch,
        {
            "response": [
                fixture(10, "Barcelona", "Real Madrid"),
                fixture(11, "Paris Saint-Germain", "Milan"),
                fixture(12, "Real Sociedad", "Cadiz"),
            ]
        },
    )

    assert find_fixture_id("PD", "2026-10-28", "FC Barcelona", "Real Madrid CF") == 10
    assert find_fixture_id("SA", "2026-10-28", "AC Milan", "Paris FC") is None
    assert find_fixture_id("PD", "2026-10-28", "Real Madrid CF", "FC Barcelona") is None
    assert find_fixture_id("PD", "2026-10-28", "Real Madrid CF", "Real Sociedad") is None
    assert calls.calls[0]["params"] == {"league": 140, "season": "2026", "date": "2026-10-28"}
    # Same identity is cached; a swapped pair is a different key and is fetched again.
    assert len(calls.calls) == 4


def test_unmapped_league_does_not_call_api_football(monkeypatch):
    def fake_get(*args, **kwargs):
        raise AssertionError("unmapped league must not spend a request")

    monkeypatch.setattr(api_football_client.requests, "get", fake_get)
    assert find_fixture_id("ZZ", "2026-10-28", "FC Barcelona", "Real Madrid CF") is None


def _player_payload():
    return {
        "response": [
            {
                "player": {
                    "id": 276,
                    "name": "Lamine Yamal",
                    "photo": "https://example.com/yamal.png",
                    "nationality": "Spain",
                },
                "statistics": [
                    {
                        "team": {"name": "Barcelona"},
                        "games": {"appearences": 35, "position": "Attacker", "rating": "7.85"},
                        "goals": {"total": 15, "assists": 12},
                        "cards": {"yellow": 4, "red": 0},
                    },
                    {
                        "team": {"name": "Spain"},
                        "games": {"appearences": 8, "position": "Attacker", "rating": "8.10"},
                        "goals": {"total": 4, "assists": 3},
                        "cards": {"yellow": 1, "red": 1},
                    },
                ],
            }
        ]
    }


def test_player_reports_club_stats_and_reuses_them_for_that_season(client, monkeypatch):
    calls = _install(monkeypatch, _player_payload())

    first = client.get("/players/276?season=2025")
    second = client.get("/players/276?season=2025")
    other_season = client.get("/players/276?season=2024")

    assert first.status_code == 200
    assert first.get_json() == {
        "id": 276,
        "name": "Lamine Yamal",
        "photo": "https://example.com/yamal.png",
        "nationality": "Spain",
        "position": "Attacker",
        "current_team": "Barcelona",
        "season": "2025",
        "appearances": 35,
        "goals": 15,
        "assists": 12,
        "yellow_cards": 4,
        "red_cards": 0,
        "rating": "7.85",
    }
    assert second.get_json() == first.get_json()
    assert [call["params"]["season"] for call in calls.calls] == ["2025", "2024"]
    assert other_season.get_json()["season"] == "2024"
    assert other_season.get_json()["appearances"] == 35


def test_player_without_statistics_is_found_but_unknown_player_is_not(client, monkeypatch):
    payloads = [
        {"response": [{"player": {"id": 5, "name": "Unused", "nationality": "Spain"}, "statistics": []}]},
        {"response": []},
    ]

    def fake_get(url, headers=None, params=None, timeout=10):
        return _Response(payloads.pop(0))

    monkeypatch.setattr(api_football_client.requests, "get", fake_get)

    empty_stats = client.get("/players/5?season=2025")
    missing = client.get("/players/5?season=2024")

    assert empty_stats.status_code == 200
    body = empty_stats.get_json()
    assert body["name"] == "Unused"
    assert body["current_team"] is None
    assert body["appearances"] is None
    assert body["goals"] is None
    assert body["yellow_cards"] is None
    assert missing.status_code == 404
    assert "not found" in missing.get_json()["error"].lower()


def test_player_forwards_the_upstream_status(client, monkeypatch):
    _install(monkeypatch, status_code=429)
    limited = client.get("/players/276?season=2025")
    assert limited.status_code == 429
    assert "rate limit" in limited.get_json()["error"].lower()

    _install(
        monkeypatch,
        {"errors": {"plan": "Free plans do not have access to this season."}},
    )
    restricted = client.get("/players/276?season=2020")
    assert restricted.status_code == 200
    assert "season" in restricted.get_json()["error"].lower()
    assert "name" not in restricted.get_json()


def test_player_defaults_the_season_to_the_utc_year(client, monkeypatch):
    from datetime import datetime

    class Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2024, 3, 2)

    calls = _install(monkeypatch, {"response": []})
    monkeypatch.setattr(player_routes, "datetime", Frozen)

    resp = client.get("/players/9")

    assert resp.status_code == 404
    assert calls.calls[0]["params"] == {"id": 9, "season": "2024"}

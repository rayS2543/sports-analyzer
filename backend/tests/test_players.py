from unittest.mock import patch

import requests


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


PLAYER = {
    "response": [
        {
            "player": {"id": 7, "name": "Vinicius", "photo": "p.jpg", "nationality": "Brazil"},
            "statistics": [
                {
                    "team": {"name": "Real Madrid"},
                    "games": {"position": "Attacker", "appearences": 20, "rating": "7.40"},
                    "goals": {"total": 8, "assists": 5},
                    "cards": {"yellow": 3, "red": 0},
                }
            ],
        }
    ]
}


def test_player_maps_the_provider_row_and_caches_only_a_success(client):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=10):
        calls.append(params)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("down")
        return FakeResponse(PLAYER)

    with patch("api_football_client.requests.get", side_effect=fake_get):
        failed = client.get("/players/7?season=2025")
        loaded = client.get("/players/7?season=2025")
        again = client.get("/players/7?season=2025")

    assert failed.status_code == 502
    assert "Could not reach api-football.com" in failed.get_json()["error"]
    assert loaded.status_code == 200
    assert loaded.get_json() == {
        "id": 7,
        "name": "Vinicius",
        "photo": "p.jpg",
        "nationality": "Brazil",
        "position": "Attacker",
        "current_team": "Real Madrid",
        "season": "2025",
        "appearances": 20,
        "goals": 8,
        "assists": 5,
        "yellow_cards": 3,
        "red_cards": 0,
        "rating": "7.40",
    }
    assert again.get_json()["name"] == "Vinicius"
    assert calls == [{"id": 7, "season": "2025"}, {"id": 7, "season": "2025"}]


def test_missing_player_and_empty_statistics(client):
    with patch("api_football_client.requests.get", return_value=FakeResponse({"response": []})):
        missing = client.get("/players/7?season=2025")
    assert missing.status_code == 404

    bare = {"response": [{"player": {"id": 7, "name": "Vinicius"}, "statistics": []}]}
    with patch("api_football_client.requests.get", return_value=FakeResponse(bare)):
        data = client.get("/players/8?season=2025").get_json()
    assert data["name"] == "Vinicius"
    assert data["goals"] is None
    assert data["appearances"] is None
    assert data["current_team"] is None


def test_plan_restriction_is_distinct_from_a_hard_provider_error(client):
    restricted = FakeResponse({"errors": {"plan": "Free plans do not cover this season."}})
    with patch("api_football_client.requests.get", return_value=restricted):
        resp = client.get("/players/7?season=2024")
    assert resp.status_code == 200
    assert "season" in resp.get_json()["error"].lower()

    rejected = FakeResponse({"errors": {"token": "Invalid key"}})
    with patch("api_football_client.requests.get", return_value=rejected):
        resp = client.get("/players/7?season=2023")
    assert resp.status_code == 502

    limited = FakeResponse({}, status_code=429)
    with patch("api_football_client.requests.get", return_value=limited):
        resp = client.get("/players/7?season=2022")
    assert resp.status_code == 429


def test_omitted_season_uses_the_current_utc_year(client):
    seen = {}

    def fake_get(url, headers=None, params=None, timeout=10):
        seen.update(params)
        return FakeResponse({"response": []})

    class Frozen:
        @staticmethod
        def utcnow():
            class Now:
                year = 2026

            return Now()

    with (
        patch("api_football_client.requests.get", side_effect=fake_get),
        patch("routes.players.datetime", Frozen),
    ):
        assert client.get("/players/7").status_code == 404
    assert seen["season"] == "2026"

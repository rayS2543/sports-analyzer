import itertools
import json
from unittest.mock import patch

import pytest
import requests

_match_ids = itertools.count(1)


class FakeResponse:
    """Minimal stand-in for requests.Response.

    football_client.get() checks .status_code/.ok before calling .json(),
    so this needs those too, not just .json().
    """

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def make_match(home, away, home_score, away_score, date):
    return {
        "id": next(_match_ids),
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
        "utcDate": f"{date}T18:30:00Z",
    }


# ---------------------------------------------------------------------------
# /
# ---------------------------------------------------------------------------


def test_home_returns_running_message(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.get_json() == {"message": "Sports Analyzer backend running"}


def test_health_returns_ok(client):
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_matches_returns_502_on_upstream_failure(client):
    with patch("football_client.requests.get", side_effect=requests.ConnectionError("boom")):
        resp = client.get("/matches")

    assert resp.status_code == 502


def test_matches_skips_fixtures_without_a_final_score(client):
    payload = {
        "matches": [
            make_match("Real Madrid", "Barcelona", None, None, "2024-01-05"),
            make_match("Sevilla", "Valencia", 1, 0, "2024-01-06"),
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["home"] == "Sevilla"


# ---------------------------------------------------------------------------
# /matches
# ---------------------------------------------------------------------------


def test_matches_computes_winner_and_points_for_home_win(client):
    match = make_match("Real Madrid", "Barcelona", 3, 1, "2024-01-05")
    payload = {"matches": [match]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data == [
        {
            "id": match["id"],
            "home": "Real Madrid",
            "away": "Barcelona",
            "score": "3 - 1",
            "winner": "Real Madrid",
            "home_points": 3,
            "away_points": 0,
            "date": "2024-01-05",
        }
    ]


def test_matches_computes_winner_and_points_for_away_win(client):
    payload = {"matches": [make_match("Sevilla", "Valencia", 0, 2, "2024-01-06")]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    data = resp.get_json()
    assert data[0]["winner"] == "Valencia"
    assert data[0]["home_points"] == 0
    assert data[0]["away_points"] == 3


def test_matches_computes_draw(client):
    payload = {"matches": [make_match("Betis", "Getafe", 1, 1, "2024-01-07")]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    data = resp.get_json()
    assert data[0]["winner"] == "Draw"
    assert data[0]["home_points"] == 1
    assert data[0]["away_points"] == 1


def test_matches_are_sorted_by_date_then_team_names(client):
    payload = {
        "matches": [
            make_match("Zaragoza", "Alaves", 1, 0, "2024-02-01"),
            make_match("Alaves", "Zaragoza", 1, 0, "2024-01-01"),
            make_match("Barcelona", "Alaves", 1, 0, "2024-01-01"),
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    data = resp.get_json()
    ordered = [(m["date"], m["home"], m["away"]) for m in data]
    assert ordered == [
        ("2024-01-01", "Alaves", "Zaragoza"),
        ("2024-01-01", "Barcelona", "Alaves"),
        ("2024-02-01", "Zaragoza", "Alaves"),
    ]


def test_matches_date_is_truncated_to_day(client):
    payload = {"matches": [make_match("Girona", "Osasuna", 2, 0, "2024-03-09")]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    assert resp.get_json()[0]["date"] == "2024-03-09"


def test_matches_returns_500_on_unexpected_api_response(client):
    payload = {"message": "Restricted"}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/matches")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "Unexpected API response"
    assert body["data"] == payload


# ---------------------------------------------------------------------------
# /teams
# ---------------------------------------------------------------------------


def test_teams_returns_cleaned_team_list(client):
    payload = {
        "teams": [
            {
                "name": "Real Madrid CF",
                "shortName": "Real Madrid",
                "tla": "RMA",
                "crest": "https://crests.example/rma.png",
                "founded": 1902,
            }
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/teams")

    assert resp.status_code == 200
    assert resp.get_json() == [
        {
            "name": "Real Madrid CF",
            "shortName": "Real Madrid",
            "tla": "RMA",
            "crest": "https://crests.example/rma.png",
        }
    ]


def test_teams_returns_500_on_unexpected_api_response(client):
    payload = {"message": "Restricted"}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/teams")

    assert resp.status_code == 500
    assert resp.get_json()["error"] == "Unexpected API response"


# ---------------------------------------------------------------------------
# /standings
# ---------------------------------------------------------------------------


def _standings_entry(position, name, points):
    return {
        "position": position,
        "team": {"name": name, "tla": name[:3].upper(), "crest": "crest.png"},
        "playedGames": 20,
        "won": 10,
        "draw": 5,
        "lost": 5,
        "points": points,
        "goalsFor": 30,
        "goalsAgainst": 20,
        "goalDifference": 10,
    }


def test_standings_uses_total_table_and_orders_by_position(client):
    payload = {
        "standings": [
            {
                "type": "HOME",
                "table": [_standings_entry(1, "Home Only Team", 99)],
            },
            {
                "type": "TOTAL",
                "table": [
                    _standings_entry(2, "Second Place", 40),
                    _standings_entry(1, "First Place", 45),
                ],
            },
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/standings")

    assert resp.status_code == 200
    data = resp.get_json()
    assert [entry["team_name"] for entry in data] == ["First Place", "Second Place"]
    assert data[0]["points"] == 45


def test_standings_falls_back_to_first_table_when_no_total(client):
    payload = {
        "standings": [
            {
                "type": "HOME",
                "table": [_standings_entry(1, "Only Table Team", 50)],
            }
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/standings")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["team_name"] == "Only Table Team"


def test_standings_returns_500_on_unexpected_api_response(client):
    payload = {"message": "Restricted"}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/standings")

    assert resp.status_code == 500
    assert resp.get_json()["error"] == "Unexpected API response"


# ---------------------------------------------------------------------------
# /analytics/form/<team_name>
# ---------------------------------------------------------------------------


def test_form_returns_404_without_prior_match_history(client):
    resp = client.get("/analytics/form/Real Madrid")

    assert resp.status_code == 404


def test_form_returns_400_for_unknown_league(client):
    resp = client.get("/analytics/form/Real Madrid?league=ZZ")

    assert resp.status_code == 400


def test_form_is_built_from_matches_persisted_by_a_prior_fetch(client):
    payload = {
        "matches": [
            make_match("Real Madrid", "Barcelona", 3, 1, "2024-01-05"),
            make_match("Sevilla", "Real Madrid", 0, 0, "2024-01-12"),
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        client.get("/matches")

    resp = client.get("/analytics/form/Real Madrid")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["team"] == "Real Madrid"
    assert data["league"] == "PD"
    assert data["matches_considered"] == 2
    assert data["form"] == "DW"
    assert data["points"] == 4


def test_form_respects_the_limit_query_param(client):
    payload = {
        "matches": [
            make_match("Real Madrid", "Barcelona", 3, 1, "2024-01-05"),
            make_match("Sevilla", "Real Madrid", 0, 0, "2024-01-12"),
        ]
    }

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        client.get("/matches")

    resp = client.get("/analytics/form/Real Madrid?limit=1")

    data = resp.get_json()
    assert data["matches_considered"] == 1
    assert data["form"] == "D"

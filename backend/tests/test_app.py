import itertools
import json
import threading
import time
from datetime import date, timedelta
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


def test_leagues_include_champions_league(client):
    codes = [league["code"] for league in client.get("/leagues").get_json()]

    assert "CL" in codes


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


def _route_today(url, payload):
    """Dispatch a fake football-data.org response by which feed was requested."""

    def fake_get(url_called, **kwargs):
        if url_called.endswith("/competitions/CL/matches"):
            body = payload.get("cl", {"matches": []})
        else:
            body = payload.get("domestic", {"matches": []})
        status = payload.get("status", {}).get("cl" if url_called.endswith("/competitions/CL/matches") else "domestic", 200)
        return FakeResponse(body, status_code=status)

    return fake_get


def test_matches_today_uses_one_combined_request_and_tags_each_league(client):
    pl = dict(make_match("Arsenal", "Chelsea", None, None, "2026-10-12"), competition={"code": "PL"}, status="TIMED")
    pd = dict(make_match("Sevilla", "Valencia", 1, 0, "2026-10-12"), competition={"code": "PD"}, status="FINISHED")
    pl["utcDate"] = "2026-10-12T14:00:00Z"
    pd["utcDate"] = "2026-10-12T20:00:00Z"

    with (
        patch("football_client.requests.get", side_effect=_route_today("", {"domestic": {"matches": [pl, pd]}})) as upstream,
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp = client.get("/matches/today?date=2026-10-12")

    assert upstream.call_count == 2
    domestic_params = upstream.call_args_list[0].kwargs["params"]
    assert domestic_params["competitions"] == "PD,PL,SA,BL1,FL1,CL"
    assert domestic_params["dateFrom"] == "2026-10-12"
    assert upstream.call_args_list[1].args[0].endswith("/competitions/CL/matches")
    assert [(m["league_code"], m["league_name"]) for m in resp.get_json()] == [("PL", "Premier League"), ("PD", "La Liga")]


def test_matches_today_merges_champions_league_fixtures(client):
    earlier = dict(make_match("PSV", "Sporting CP", 2, 2, "2026-09-01"), status="FINISHED")
    live = dict(make_match("Arsenal", "Bayern Munich", 1, 0, "2026-10-21"), status="IN_PLAY")
    live["utcDate"] = "2026-10-21T19:00:00Z"
    domestic = dict(make_match("Athletic Club", "Levante", 1, 2, "2026-10-21"), competition={"code": "PD"}, status="IN_PLAY")
    domestic["utcDate"] = "2026-10-21T18:00:00Z"

    payload = {"domestic": {"matches": [domestic]}, "cl": {"matches": [earlier, live]}}
    fotmob_only = {
        "id": 99,
        "league_code": "CL",
        "league_name": "Champions League",
        "home": "Real Madrid",
        "away": "RB Leipzig",
        "home_crest": None,
        "away_crest": None,
        "home_score": 4,
        "away_score": 1,
        "status": "FINISHED",
        "kickoff": "2026-10-21T19:00:00Z",
    }
    with (
        patch("football_client.requests.get", side_effect=_route_today("", payload)),
        patch("routes.football.champions_league_fixtures", return_value=[fotmob_only]),
    ):
        resp = client.get("/matches/today?date=2026-10-21")

    assert resp.status_code == 200
    assert [(m["home"], m["away"], m["league_code"], m["league_name"], m["home_score"]) for m in resp.get_json()] == [
        ("Athletic Club", "Levante", "PD", "La Liga", 1),
        ("Arsenal", "Bayern Munich", "CL", "Champions League", 1),
        ("Real Madrid", "RB Leipzig", "CL", "Champions League", 4),
    ]


def test_matches_today_keeps_domestic_fixtures_when_champions_league_is_restricted(client):
    pd = dict(make_match("Sevilla", "Valencia", 1, 0, "2026-10-12"), competition={"code": "PD"}, status="FINISHED")

    payload = {
        "domestic": {"matches": [pd]},
        "cl": {},
        "status": {"cl": 403},
    }
    with (
        patch("football_client.requests.get", side_effect=_route_today("", payload)),
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp = client.get("/matches/today?date=2026-10-12")

    assert resp.status_code == 200
    assert [m["home"] for m in resp.get_json()] == ["Sevilla"]


def test_matches_today_uses_fotmob_when_football_data_has_no_ucl_access(client):
    fotmob_match = {
        "id": 6106238,
        "league_code": "CL",
        "league_name": "Champions League",
        "home": "Bayern München",
        "away": "Arsenal",
        "home_crest": "https://images.fotmob.com/image_resources/logo/teamlogo/9823.png",
        "away_crest": "https://images.fotmob.com/image_resources/logo/teamlogo/9825.png",
        "home_score": 2,
        "away_score": 2,
        "status": "FINISHED",
        "kickoff": "2026-10-21T19:00:00Z",
    }
    already = dict(
        make_match("FC Bayern München", "Arsenal FC", 2, 2, "2026-10-21"),
        competition={"code": "CL"},
        status="FINISHED",
    )
    already["utcDate"] = "2026-10-21T19:00:00Z"
    extra = dict(fotmob_match)
    extra["id"] = 6106244
    extra["home"] = "Real Madrid"
    extra["away"] = "RB Leipzig"

    with (
        patch("football_client.requests.get", side_effect=_route_today("", {"status": {"domestic": 403, "cl": 403}})),
        patch("routes.football.champions_league_fixtures", return_value=[fotmob_match, extra]),
    ):
        resp = client.get("/matches/today?date=2026-10-21")

    assert resp.status_code == 200
    rows = [(m["home"], m["away"], m["league_code"]) for m in resp.get_json()]
    assert ("Bayern München", "Arsenal", "CL") in rows
    assert ("Real Madrid", "RB Leipzig", "CL") in rows

    # A football-data row for the same fixture is not duplicated by FotMob's name.
    with (
        patch("football_client.requests.get", side_effect=_route_today("", {"domestic": {"matches": [already]}})),
        patch("routes.football.champions_league_fixtures", return_value=[fotmob_match]),
    ):
        resp = client.get("/matches/today?date=2026-10-21")

    assert [m["home"] for m in resp.get_json()] == ["FC Bayern München"]


def test_matches_today_collapses_one_fixture_when_provider_ids_differ(client):
    """football-data's combined feed, its UCL feed, and FotMob use different ids for one match."""
    domestic = dict(
        make_match("FC Bayern München", "Arsenal FC", None, None, "2026-10-21"),
        competition={"code": "CL"},
        status="TIMED",
        id=111,
    )
    domestic["utcDate"] = "2026-10-21T16:00:00Z"
    other = dict(
        make_match("Sevilla", "Valencia", None, None, "2026-10-21"),
        competition={"code": "PD"},
        status="TIMED",
        id=222,
    )
    other["utcDate"] = "2026-10-21T18:00:00Z"
    dedicated = dict(
        make_match("Bayern München", "Arsenal", 1, 0, "2026-10-21"),
        status="IN_PLAY",
        id=999,
    )
    dedicated["utcDate"] = "2026-10-21T19:00:00Z"
    fotmob = {
        "id": 6106238,
        "league_code": "CL",
        "league_name": "Champions League",
        "home": "Bayern München",
        "away": "Arsenal",
        "home_crest": None,
        "away_crest": None,
        "home_score": 2,
        "away_score": 2,
        "status": "FINISHED",
        "kickoff": "2026-10-21T19:00:00Z",
    }

    with (
        patch(
            "football_client.requests.get",
            side_effect=_route_today("", {"domestic": {"matches": [domestic, other]}, "cl": {"matches": [dedicated]}}),
        ),
        patch("routes.football.champions_league_fixtures", return_value=[fotmob]),
    ):
        resp = client.get("/matches/today?date=2026-10-21")

    assert resp.status_code == 200
    assert [
        (m["home"], m["away"], m["id"], m["home_score"], m["status"], m["league_code"]) for m in resp.get_json()
    ] == [
        ("Sevilla", "Valencia", 222, None, "TIMED", "PD"),
        ("Bayern München", "Arsenal", 999, 1, "IN_PLAY", "CL"),
    ]


def test_matches_today_rejects_a_bad_date(client):
    resp = client.get("/matches/today?date=21-10-2026")

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "date must be YYYY-MM-DD"


def test_matches_today_surfaces_upstream_errors(client):
    with (
        patch("football_client.requests.get", return_value=FakeResponse({}, status_code=429)),
        patch("routes.football.champions_league_fixtures", return_value=[]),
    ):
        resp = client.get("/matches/today")

    assert resp.status_code == 429
    assert "rate limit" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# /matches
# ---------------------------------------------------------------------------


def test_matches_returns_latest_ten_finished_matches_however_old(client):
    # e.g. an international break or a Champions League gap: nothing recent, results still show.
    payload = {"matches": [make_match(f"Home{i}", f"Away{i}", 1, 0, f"2026-09-{i + 1:02d}") for i in range(12)]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)) as upstream:
        data = client.get("/matches?league=CL").get_json()

    assert upstream.call_args.args[0].endswith("/competitions/CL/matches")
    assert len(data) == 10
    assert data[0]["date"] == "2026-09-12"
    assert data[-1]["date"] == "2026-09-03"


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
            "home_crest": None,
            "away_crest": None,
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
        ("2024-02-01", "Zaragoza", "Alaves"),
        ("2024-01-01", "Barcelona", "Alaves"),
        ("2024-01-01", "Alaves", "Zaragoza"),
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
# /predictions
# ---------------------------------------------------------------------------


def test_predictions_requests_timed_matches_alongside_scheduled(client):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=10):
        calls.append(params)
        return FakeResponse({"matches": []})

    with patch("football_client.requests.get", side_effect=fake_get):
        client.get("/predictions")

    upcoming_call = next(c for c in calls if c["status"] != "FINISHED")
    assert upcoming_call["status"] == "SCHEDULED,TIMED"


def test_predictions_fetches_finished_history_in_one_call_and_keeps_last_90_days(client):
    today = date.today()
    recent = (today - timedelta(days=5)).isoformat()
    old = (today - timedelta(days=200)).isoformat()
    calls = []

    def fake_get(url, headers=None, params=None, timeout=10):
        calls.append((url, params))
        if params.get("status") == "FINISHED":
            return FakeResponse(
                {
                    "matches": [
                        make_match("Real Madrid", "Barcelona", 3, 0, recent),
                        # Barcelona's old win must not count: outside the 90-day window.
                        make_match("Barcelona", "Real Madrid", 9, 0, old),
                    ]
                }
            )
        return FakeResponse({"matches": [make_match("Real Madrid", "Barcelona", None, None, today.isoformat())]})

    with patch("football_client.requests.get", side_effect=fake_get):
        resp = client.get("/predictions?league=PD")

    assert len([c for c in calls if c[1].get("status") == "FINISHED"]) == 1
    assert resp.get_json()[0]["predicted_winner"] == "Real Madrid"


def test_concurrent_identical_requests_share_one_upstream_call(client):
    def slow_get(*args, **kwargs):
        time.sleep(0.1)
        return FakeResponse({"standings": [{"type": "TOTAL", "table": []}]})

    with patch("football_client.requests.get", side_effect=slow_get) as upstream:
        threads = [threading.Thread(target=client.get, args=("/standings?league=PD",)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert upstream.call_count == 1


def test_predictions_picks_higher_rated_team_as_winner(client):
    finished_payload = {
        "matches": [make_match("Real Madrid", "Barcelona", 3, 0, date.today().isoformat())]
    }
    upcoming_payload = {
        "matches": [make_match("Real Madrid", "Barcelona", None, None, "2024-02-01")]
    }

    def fake_get(url, headers=None, params=None, timeout=10):
        if params.get("status") == "FINISHED":
            return FakeResponse(finished_payload)
        return FakeResponse(upcoming_payload)

    with patch("football_client.requests.get", side_effect=fake_get):
        resp = client.get("/predictions")

    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["predicted_winner"] == "Real Madrid"
    assert data[0]["predicted_result"] == "home"
    assert data[0]["home_win_pct"] > data[0]["away_win_pct"]
    assert data[0]["draw_pct"] > 0
    assert data[0]["home_elo"] > data[0]["away_elo"]


# ---------------------------------------------------------------------------
# /ratings
# ---------------------------------------------------------------------------


def test_ratings_returns_ranked_table_from_finished_window(client):
    today = date.today()
    recent = (today - timedelta(days=3)).isoformat()
    old = (today - timedelta(days=200)).isoformat()

    def fake_get(url, headers=None, params=None, timeout=10):
        assert params.get("status") == "FINISHED"
        return FakeResponse(
            {
                "matches": [
                    make_match("Real Madrid", "Girona", 2, 0, recent),
                    make_match("Barcelona", "Alaves", 1, 0, recent),
                    make_match("Alaves", "Real Madrid", 9, 0, old),
                ]
            }
        )

    with patch("football_client.requests.get", side_effect=fake_get):
        resp = client.get("/ratings?league=PD")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["league"] == "PD"
    assert body["window_days"] == 90
    assert body["matches_used"] == 2
    assert body["model"]["includes_draw"] is True
    assert body["ratings"][0]["team"] == "Real Madrid"
    assert body["ratings"][0]["rank"] == 1
    assert body["ratings"][0]["rating"] > 1500


def test_ratings_rejects_unknown_league(client):
    resp = client.get("/ratings?league=NOPE")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /teams
# ---------------------------------------------------------------------------


def test_teams_returns_cleaned_team_list(client):
    payload = {
        "teams": [
            {
                "id": 86,
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
            "id": 86,
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
    assert resp.get_json()["error"] == "Unexpected football-data.org response."


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


def test_refetched_score_replaces_the_persisted_result(client):
    import cache

    first = {"matches": [make_match("Real Madrid", "Barcelona", 1, 0, "2024-01-05")]}
    corrected = {"matches": [make_match("Real Madrid", "Barcelona", 0, 2, "2024-01-05")]}

    with patch("football_client.requests.get", return_value=FakeResponse(first)):
        client.get("/matches")
    cache.clear()
    with patch("football_client.requests.get", return_value=FakeResponse(corrected)):
        client.get("/matches")

    data = client.get("/analytics/form/Real Madrid").get_json()
    assert data["form"] == "L"
    assert data["points"] == 0
    assert data["matches"][0]["score"] == "0 - 2"
    assert data["matches"][0]["winner"] == "Barcelona"


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


# ---------------------------------------------------------------------------
# /teams/detail
# ---------------------------------------------------------------------------


def test_team_detail_requires_name(client):
    resp = client.get("/teams/detail?league=PD")

    assert resp.status_code == 400
    assert "name" in resp.get_json()["error"].lower()


def test_team_detail_returns_404_for_unknown_club(client):
    payload = {"teams": [{"id": 1, "name": "Other Club", "shortName": "Other", "tla": "OTH", "crest": "c.png"}]}

    with patch("football_client.requests.get", return_value=FakeResponse(payload)):
        resp = client.get("/teams/detail?league=PD&name=Real%20Madrid")

    assert resp.status_code == 404


def test_team_detail_returns_roster_form_and_fixtures(client):
    teams_payload = {
        "teams": [
            {
                "id": 86,
                "name": "Real Madrid CF",
                "shortName": "Real Madrid",
                "tla": "RMA",
                "crest": "https://crests.example/rma.png",
            }
        ]
    }
    detail_payload = {
        "id": 86,
        "name": "Real Madrid CF",
        "shortName": "Real Madrid",
        "tla": "RMA",
        "crest": "https://crests.example/rma.png",
        "founded": 1902,
        "venue": "Santiago Bernabéu",
        "clubColors": "White",
        "coach": {"name": "Carlo Ancelotti", "nationality": "Italy"},
        "squad": [
            {
                "id": 1,
                "name": "Courtois",
                "position": "Goalkeeper",
                "nationality": "Belgium",
                "shirtNumber": 1,
                "dateOfBirth": "1992-05-11",
            },
            {
                "id": 2,
                "name": "Vinicius Junior",
                "position": "Offence",
                "nationality": "Brazil",
                "shirtNumber": 7,
                "dateOfBirth": "2000-07-12",
            },
        ],
    }
    finished_match = make_match("Real Madrid CF", "Barcelona", 2, 1, "2024-01-10")
    finished_match["homeTeam"]["crest"] = "rma.png"
    finished_match["awayTeam"]["crest"] = "bar.png"
    finished_match["competition"] = {"code": "PD"}
    finished_match["status"] = "FINISHED"
    upcoming_match = make_match("Sevilla", "Real Madrid CF", None, None, "2024-01-20")
    upcoming_match["homeTeam"]["crest"] = "sev.png"
    upcoming_match["awayTeam"]["crest"] = "rma.png"
    upcoming_match["competition"] = {"code": "PD"}
    upcoming_match["status"] = "SCHEDULED"
    standings_payload = {
        "standings": [
            {
                "type": "TOTAL",
                "table": [
                    {
                        "position": 1,
                        "team": {"name": "Real Madrid CF", "tla": "RMA", "crest": "rma.png"},
                        "playedGames": 18,
                        "won": 14,
                        "draw": 3,
                        "lost": 1,
                        "points": 45,
                        "goalsFor": 40,
                        "goalsAgainst": 12,
                        "goalDifference": 28,
                    }
                ],
            }
        ]
    }

    def fake_get(url, headers=None, params=None, timeout=10):
        if url.endswith("/competitions/PD/teams"):
            return FakeResponse(teams_payload)
        if url.endswith("/teams/86"):
            return FakeResponse(detail_payload)
        if url.endswith("/teams/86/matches"):
            if params and params.get("status") == "FINISHED":
                return FakeResponse({"matches": [finished_match]})
            return FakeResponse({"matches": [upcoming_match]})
        if url.endswith("/competitions/PD/standings"):
            return FakeResponse(standings_payload)
        raise AssertionError(f"Unexpected URL {url}")

    with patch("football_client.requests.get", side_effect=fake_get):
        resp = client.get("/teams/detail?league=PD&name=Real%20Madrid%20CF")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Real Madrid CF"
    assert data["venue"] == "Santiago Bernabéu"
    assert data["coach"]["name"] == "Carlo Ancelotti"
    assert data["standing"]["position"] == 1
    assert data["form"] == "W"
    assert data["form_points"] == 3
    assert [p["name"] for p in data["squad"]] == ["Courtois", "Vinicius Junior"]
    assert data["recent_matches"][0]["score"] == "2 - 1"
    assert data["upcoming_matches"][0]["home"] == "Sevilla"

    form_resp = client.get("/analytics/form/Real%20Madrid%20CF?league=PD")
    assert form_resp.status_code == 200
    assert form_resp.get_json()["form"] == "W"


def test_team_detail_resolves_short_name_and_keeps_other_competitions_out_of_league_form(client):
    teams_payload = {
        "teams": [
            {
                "id": 86,
                "name": "Real Madrid CF",
                "shortName": "Real Madrid",
                "tla": "RMA",
                "crest": "https://crests.example/rma.png",
            }
        ]
    }
    detail_payload = {
        "id": 86,
        "name": "Real Madrid CF",
        "shortName": "Real Madrid",
        "tla": "RMA",
        "crest": "https://crests.example/rma.png",
        "squad": [],
    }
    league_match = make_match("Real Madrid CF", "Barcelona", 2, 1, "2024-01-10")
    league_match["competition"] = {"code": "PD"}
    unlabeled = make_match("Sevilla", "Real Madrid CF", 1, 1, "2024-01-12")
    ucl_match = make_match("Manchester City", "Real Madrid CF", 3, 0, "2024-01-17")
    ucl_match["competition"] = {"code": "CL"}

    def fake_get(url, headers=None, params=None, timeout=10):
        if url.endswith("/competitions/PD/teams"):
            return FakeResponse(teams_payload)
        if url.endswith("/teams/86"):
            return FakeResponse(detail_payload)
        if url.endswith("/teams/86/matches"):
            if params and params.get("status") == "FINISHED":
                return FakeResponse({"matches": [league_match, unlabeled, ucl_match]})
            return FakeResponse({"matches": []})
        if url.endswith("/competitions/PD/standings"):
            return FakeResponse({"standings": []})
        raise AssertionError(f"Unexpected URL {url}")

    with patch("football_client.requests.get", side_effect=fake_get):
        resp = client.get("/teams/detail?league=PD&name=Real%20Madrid")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Real Madrid CF"
    assert [(m["home"], m["away"], m["competition"]) for m in data["recent_matches"]] == [
        ("Manchester City", "Real Madrid CF", "CL"),
        ("Sevilla", "Real Madrid CF", None),
        ("Real Madrid CF", "Barcelona", "PD"),
    ]
    # The profile string follows every match shown, including other competitions.
    assert data["form"] == "LDW"
    assert data["form_points"] == 4

    form = client.get("/analytics/form/Real%20Madrid%20CF?league=PD").get_json()
    assert form["form"] == "DW"
    assert form["points"] == 4
    assert [(m["home"], m["score"]) for m in form["matches"]] == [
        ("Sevilla", "1 - 1"),
        ("Real Madrid CF", "2 - 1"),
    ]

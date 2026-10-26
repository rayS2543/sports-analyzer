import pytest
import requests

import fotmob_client


@pytest.mark.parametrize("league,home,away,provider_home,provider_away", [
    ("PD", "Valencia CF", "Real Sociedad de Fútbol", "Valencia", "Real Sociedad"),
    ("PD", "Club Atlético de Madrid", "Real Madrid CF", "Atlético Madrid", "Real Madrid"),
    ("PL", "Brighton & Hove Albion FC", "AFC Bournemouth", "Brighton & Hove Albion", "AFC Bournemouth"),
    ("SA", "FC Internazionale Milano", "ACF Fiorentina", "Inter", "Fiorentina"),
    ("BL1", "TSG 1899 Hoffenheim", "1. FSV Mainz 05", "Hoffenheim", "Mainz 05"),
    ("FL1", "Olympique de Marseille", "Stade Rennais FC 1901", "Marseille", "Rennes"),
    ("CL", "PSV", "Sporting Clube de Portugal", "PSV Eindhoven", "Sporting CP"),
    ("CL", "PAE AEK", "SK Slavia Praha", "AEK Athens", "Slavia Prague"),
])
def test_fixture_matching_handles_provider_names(monkeypatch, league, home, away, provider_home, provider_away):
    fixture = {"id": 123, "pageUrl": "/match#123", "status": {"utcTime": "2026-09-20T14:00:00Z"},
               "home": {"name": provider_home}, "away": {"name": provider_away}}
    monkeypatch.setattr(fotmob_client, "_fetch_page_props", lambda path: {"fixtures": {"allMatches": [fixture]}})
    assert fotmob_client.find_fixture(league, "2026-09-20", home, away) == {"id": 123, "page_url": "/match#123"}
    assert fotmob_client.find_fixture(league, "2026-09-21", home, away) is None
    assert fotmob_client.find_fixture(league, "2026-09-20", away, home) is None


def test_champions_league_fixtures_reads_the_league_stage_only(monkeypatch):
    payload = {
        "leagues": [
            {
                "id": 42,
                "name": "Champions League - League Stage",
                "matches": [
                    {
                        "id": 1,
                        "home": {"id": 10, "name": "Bayern München", "score": 2},
                        "away": {"id": 11, "name": "Arsenal", "score": 2},
                        "status": {"utcTime": "2026-10-21T19:00:00.000Z", "finished": True, "started": True},
                    },
                    {
                        "id": 2,
                        "home": {"id": 12, "name": "Tomorrow FC", "score": 0},
                        "away": {"id": 13, "name": "Other", "score": 0},
                        "status": {"utcTime": "2026-10-22T19:00:00.000Z", "started": False},
                    },
                ],
            },
            {
                "id": 999,
                "name": "UEFA Youth League",
                "matches": [
                    {
                        "id": 3,
                        "home": {"name": "Bayern München U19"},
                        "away": {"name": "Arsenal U19"},
                        "status": {"utcTime": "2026-10-21T14:00:00.000Z", "finished": True},
                    }
                ],
            },
        ]
    }

    class Response:
        ok = True
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(fotmob_client.requests, "get", lambda *args, **kwargs: Response())
    fixtures = fotmob_client.champions_league_fixtures("2026-10-21")

    assert fixtures == [
        {
            "id": 1,
            "league_code": "CL",
            "league_name": "Champions League",
            "home": "Bayern München",
            "away": "Arsenal",
            "home_crest": "https://images.fotmob.com/image_resources/logo/teamlogo/10.png",
            "away_crest": "https://images.fotmob.com/image_resources/logo/teamlogo/11.png",
            "home_score": 2,
            "away_score": 2,
            "status": "FINISHED",
            "kickoff": "2026-10-21T19:00:00.000Z",
        }
    ]


def test_champions_league_fixtures_map_status_and_hide_scores_until_kickoff(monkeypatch):
    """A 0-0 sitting on a fixture that has not started is not a result.

    Postponed and cancelled are different, and a club with no id has no crest.
    """
    day = "2026-10-22"
    payload = {
        "leagues": [
            {
                "id": 42,
                "matches": [
                    {
                        "id": 1,
                        "home": {"id": 10, "name": "Arsenal", "score": 0},
                        "away": {"name": "Bayern München", "score": 0},
                        "status": {"utcTime": f"{day}T19:00:00.000Z"},
                    },
                    {
                        "id": 2,
                        "home": {"id": 12, "name": "Real Madrid", "score": 1},
                        "away": {"id": 13, "name": "RB Leipzig", "score": 0},
                        "status": {"utcTime": f"{day}T16:00:00.000Z", "started": True, "ongoing": True},
                    },
                    {
                        "id": 3,
                        "home": {"id": 14, "name": "Inter", "score": 0},
                        "away": {"id": 15, "name": "Barcelona", "score": 0},
                        "status": {
                            "utcTime": f"{day}T18:00:00.000Z",
                            "cancelled": True,
                            "reason": {"shortKey": "postponed"},
                        },
                    },
                    {
                        "id": 4,
                        "home": {"id": 16, "name": "PSV", "score": None},
                        "away": {"id": 17, "name": "Sporting", "score": None},
                        "status": {
                            "utcTime": f"{day}T20:00:00.000Z",
                            "cancelled": True,
                            "reason": {"shortKey": "cancelled"},
                        },
                    },
                    {
                        "id": 5,
                        "home": {},
                        "away": {"name": "Someone"},
                        "status": {"utcTime": f"{day}T21:00:00.000Z"},
                    },
                ],
            }
        ]
    }

    class Response:
        ok = True
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(fotmob_client.requests, "get", lambda *args, **kwargs: Response())
    by_id = {row["id"]: row for row in fotmob_client.champions_league_fixtures(day)}

    assert set(by_id) == {1, 2, 3, 4}
    assert by_id[1]["status"] == "TIMED"
    assert by_id[1]["home_score"] is None and by_id[1]["away_score"] is None
    assert by_id[1]["home_crest"].endswith("/10.png")
    assert by_id[1]["away_crest"] is None
    assert by_id[2]["status"] == "IN_PLAY"
    assert (by_id[2]["home_score"], by_id[2]["away_score"]) == (1, 0)
    assert by_id[3]["status"] == "POSTPONED"
    assert by_id[4]["status"] == "CANCELLED"


def test_champions_league_fixture_failures_are_not_cached(monkeypatch):
    calls = {"n": 0}

    class Response:
        def __init__(self, ok, status_code, body):
            self.ok = ok
            self.status_code = status_code
            self._body = body

        def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    def get(*args, **kwargs):
        calls["n"] += 1
        n = calls["n"]
        if n == 1:
            raise requests.exceptions.ConnectionError("down")
        if n == 2:
            return Response(False, 503, {})
        if n == 3:
            return Response(True, 200, ValueError("not json"))
        return Response(True, 200, {"leagues": []})

    monkeypatch.setattr(fotmob_client.requests, "get", get)
    day = "2026-11-02"
    for _ in range(3):
        with pytest.raises(fotmob_client.FotMobError):
            fotmob_client.champions_league_fixtures(day)
    assert fotmob_client.champions_league_fixtures(day) == []
    assert fotmob_client.champions_league_fixtures(day) == []
    assert calls["n"] == 4


def test_accents_normalize_without_merging_different_clubs():
    assert fotmob_client._normalize("Atlético Madrid") == fotmob_client._normalize("Atletico Madrid")
    assert fotmob_client._normalize("Bayern München") == fotmob_client._normalize("Bayern Munchen")
    assert fotmob_client._normalize("Real Madrid") != fotmob_client._normalize("Atlético Madrid")
    assert fotmob_client._normalize("Paris FC") != fotmob_client._normalize("Paris Saint-Germain")

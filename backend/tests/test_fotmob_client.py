import requests
import pytest

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


def _day_match(match_id, home, away, status, score=(0, 0), kickoff="2026-10-21T19:00:00.000Z"):
    home_side = {"id": 10, "score": score[0]}
    if home is not None:
        home_side["name"] = home
    return {
        "id": match_id,
        "home": home_side,
        "away": {"id": 11, "name": away, "score": score[1]},
        "status": {"utcTime": kickoff, **status},
    }


def test_champions_league_statuses_and_unplayed_scores(monkeypatch):
    """A postponed or not-yet-started match must not render as 0-0, and a
    cancelled match must not be labelled in play."""
    payload = {
        "leagues": [
            {
                "id": 42,
                "matches": [
                    _day_match(1, "Bayern München", "Arsenal", {"finished": True}, (2, 1)),
                    _day_match(2, "Tomorrow FC", "Other", {"cancelled": True, "reason": {"shortKey": "postponed"}}),
                    _day_match(3, "Gone FC", "Club", {"cancelled": True}),
                    _day_match(4, "Live FC", "Side", {"ongoing": True, "started": True}, (1, 0)),
                    _day_match(5, "Later FC", "Side", {}),
                    _day_match(6, None, "Nobody", {"finished": True}, (1, 1)),
                    _day_match(7, "Awarded FC", "Side", {"awarded": True, "finished": True}, (3, 0)),
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
    fixtures = {row["id"]: row for row in fotmob_client.champions_league_fixtures("2026-10-21")}

    assert set(fixtures) == {1, 2, 3, 4, 5, 7}
    assert (fixtures[1]["status"], fixtures[1]["home_score"], fixtures[1]["away_score"]) == ("FINISHED", 2, 1)
    assert (fixtures[2]["status"], fixtures[2]["home_score"], fixtures[2]["away_score"]) == ("POSTPONED", None, None)
    assert fixtures[3]["status"] == "CANCELLED"
    assert (fixtures[4]["status"], fixtures[4]["home_score"]) == ("IN_PLAY", 1)
    assert (fixtures[5]["status"], fixtures[5]["home_score"], fixtures[5]["away_score"]) == ("TIMED", None, None)
    assert (fixtures[7]["status"], fixtures[7]["home_score"]) == ("FINISHED", 3)


def test_champions_league_fixtures_fail_closed(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(fotmob_client.requests, "get", boom)
    with pytest.raises(fotmob_client.FotMobError) as timeout:
        fotmob_client.champions_league_fixtures("2026-10-21")
    assert timeout.value.status_code == 502

    class BadJson:
        ok = True
        status_code = 200

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(fotmob_client.requests, "get", lambda *args, **kwargs: BadJson())
    with pytest.raises(fotmob_client.FotMobError) as parsed:
        fotmob_client.champions_league_fixtures("2026-10-21")
    assert parsed.value.status_code == 502


def test_accents_normalize_without_merging_different_clubs():
    assert fotmob_client._normalize("Atlético Madrid") == fotmob_client._normalize("Atletico Madrid")
    assert fotmob_client._normalize("Bayern München") == fotmob_client._normalize("Bayern Munchen")
    assert fotmob_client._normalize("Real Madrid") != fotmob_client._normalize("Atlético Madrid")
    assert fotmob_client._normalize("Paris FC") != fotmob_client._normalize("Paris Saint-Germain")

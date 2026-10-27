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


def test_unknown_league_does_not_fetch_a_match_page(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("fetched")

    monkeypatch.setattr(fotmob_client.requests, "get", fail)

    assert fotmob_client.find_fixture("ZZ", "2026-09-20", "Home", "Away") is None


def test_match_page_requires_embedded_json(monkeypatch):
    pages = [
        fotmob_client.requests.exceptions.ConnectionError("down"),
        503,
        "<html>no next data</html>",
        '<script id="__NEXT_DATA__">{</script>',
        '<script id="__NEXT_DATA__">{"props":{"pageProps":{"content":{"ok":true}}}}</script>',
    ]
    calls = {"n": 0}

    def get(url, headers=None, timeout=10):
        calls["n"] += 1
        page = pages[calls["n"] - 1]
        if isinstance(page, Exception):
            raise page
        if isinstance(page, int):
            return type("Response", (), {"ok": False, "status_code": page, "text": ""})()
        return type("Response", (), {"ok": True, "status_code": 200, "text": page})()

    monkeypatch.setattr(fotmob_client.requests, "get", get)

    for _ in range(4):
        with pytest.raises(fotmob_client.FotMobError) as exc:
            fotmob_client._fetch_page_props("/match/1")
        assert exc.value.status_code == 502

    assert fotmob_client._fetch_page_props("/match/1")["content"]["ok"] is True
    assert calls["n"] == 5


def test_accents_normalize_without_merging_different_clubs():
    assert fotmob_client._normalize("Atlético Madrid") == fotmob_client._normalize("Atletico Madrid")
    assert fotmob_client._normalize("Bayern München") == fotmob_client._normalize("Bayern Munchen")
    assert fotmob_client._normalize("Real Madrid") != fotmob_client._normalize("Atlético Madrid")
    assert fotmob_client._normalize("Paris FC") != fotmob_client._normalize("Paris Saint-Germain")

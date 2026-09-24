import pytest

import fotmob_client


@pytest.mark.parametrize("league,home,away,provider_home,provider_away", [
    ("PD", "Valencia CF", "Real Sociedad de Fútbol", "Valencia", "Real Sociedad"),
    ("PD", "Club Atlético de Madrid", "Real Madrid CF", "Atlético Madrid", "Real Madrid"),
    ("PL", "Brighton & Hove Albion FC", "AFC Bournemouth", "Brighton & Hove Albion", "AFC Bournemouth"),
    ("SA", "FC Internazionale Milano", "ACF Fiorentina", "Inter", "Fiorentina"),
    ("BL1", "TSG 1899 Hoffenheim", "1. FSV Mainz 05", "Hoffenheim", "Mainz 05"),
    ("FL1", "Olympique de Marseille", "Stade Rennais FC 1901", "Marseille", "Rennes"),
])
def test_fixture_matching_handles_provider_names(monkeypatch, league, home, away, provider_home, provider_away):
    fixture = {"id": 123, "pageUrl": "/match#123", "status": {"utcTime": "2026-09-20T14:00:00Z"},
               "home": {"name": provider_home}, "away": {"name": provider_away}}
    monkeypatch.setattr(fotmob_client, "_fetch_page_props", lambda path: {"fixtures": {"allMatches": [fixture]}})
    assert fotmob_client.find_fixture(league, "2026-09-20", home, away) == {"id": 123, "page_url": "/match#123"}
    assert fotmob_client.find_fixture(league, "2026-09-21", home, away) is None
    assert fotmob_client.find_fixture(league, "2026-09-20", away, home) is None


def test_accents_normalize_without_merging_different_clubs():
    assert fotmob_client._normalize("Atlético Madrid") == fotmob_client._normalize("Atletico Madrid")
    assert fotmob_client._normalize("Bayern München") == fotmob_client._normalize("Bayern Munchen")
    assert fotmob_client._normalize("Real Madrid") != fotmob_client._normalize("Atlético Madrid")
    assert fotmob_client._normalize("Paris FC") != fotmob_client._normalize("Paris Saint-Germain")

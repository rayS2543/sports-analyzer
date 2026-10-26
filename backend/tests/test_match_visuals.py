from unittest.mock import Mock

from fotmob_client import FotMobError
from routes import matches_detail


def test_match_detail_preserves_pitch_and_shot_data(client, monkeypatch):
    player = {"id": 7, "name": "Player", "shirtNumber": "9", "isCaptain": True,
              "verticalLayout": {"x": 0.3, "y": 0.8}}
    team = {"id": 1, "name": "Home", "formation": "4-4-2", "starters": [player]}
    shot = {"id": 8, "teamId": 1, "playerId": 7, "x": 94, "y": 34,
            "expectedGoals": 0.42, "period": "SecondHalf", "goalCrossedY": 33.1, "goalCrossedZ": 1.2}
    content = {"lineup": {"homeTeam": team, "awayTeam": {**team, "id": 2}},
               "shotmap": {"shots": [shot, {**shot, "x": None}, {**shot, "y": 80}]}}
    monkeypatch.setattr(matches_detail, "find_fixture", lambda *args: {"page_url": "/match"})
    monkeypatch.setattr(matches_detail, "fetch_match_content", lambda *args: content)
    data = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away").get_json()
    assert data["home"]["starters"][0]["pitch_position"] == {"x": 0.3, "y": 0.8}
    assert data["home"]["starters"][0]["captain"] is True
    assert len(data["shots"]) == 1
    assert data["shots"][0]["expectedGoals"] == 0.42
    assert (data["shots"][0]["goalCrossedY"], data["shots"][0]["goalCrossedZ"]) == (33.1, 1.2)
    assert data["away"]["id"] == 2


def test_missing_coverage_and_invalid_positions():
    assert matches_detail._build_shots(None) is None
    assert matches_detail._build_shots({"shots": []}) == []
    team = matches_detail._build_team({"starters": [{"verticalLayout": {"x": -1, "y": 0.5}}]})
    assert team["starters"][0]["pitch_position"] is None


def test_unpublished_lineup_still_returns_plottable_shots(client, monkeypatch):
    shot = {"id": 1, "x": 90, "y": 34, "eventType": "Goal"}
    boundary = {"id": 4, "x": 105, "y": 0}
    content = {
        "lineup": {"homeTeam": {}},
        "shotmap": {"shots": [
            shot,
            {"id": 2, "x": True, "y": 34},
            {"id": 3, "x": float("nan"), "y": 10},
            boundary,
            {"id": 5, "x": "90", "y": 34},
            {"id": 6, "x": 106, "y": 10},
        ]},
    }
    monkeypatch.setattr(matches_detail, "find_fixture", lambda *args: {"page_url": "/match"})
    monkeypatch.setattr(matches_detail, "fetch_match_content", lambda *args: content)
    data = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away").get_json()
    assert data["available"] is False
    assert data["reason"] == "Lineup not published for this fixture yet."
    assert [s["id"] for s in data["shots"]] == [1, 4]


def test_lineup_counts_events_and_merges_club_assets(client, monkeypatch):
    player = {
        "id": 7,
        "name": "Player",
        "usualPlayingPositionId": 0,
        "shirtNumber": 1,
        "performance": {"events": [
            {"type": "goal"}, {"type": "goal"}, {"type": "assist"},
            {"type": "yellowCard"}, {"type": "redCard"}, {"type": "other"},
        ]},
        "verticalLayout": {"x": True, "y": 0.1},
    }
    content = {
        "lineup": {
            "homeTeam": {"id": 1, "name": "Home", "starters": [player], "subs": [{"id": 8, "name": "Sub"}]},
            "awayTeam": {"id": 2, "name": "Away", "starters": [], "subs": []},
        },
        "shotmap": None,
        "teamAssets": {"home": {"crest": "h.png", "color": "#111"}, "away": {"crest": "a.png"}},
    }
    monkeypatch.setattr(matches_detail, "find_fixture", lambda *args: {"page_url": "/match"})
    monkeypatch.setattr(matches_detail, "fetch_match_content", lambda *args: content)
    data = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away").get_json()
    starter = data["home"]["starters"][0]
    assert data["available"] is True
    assert data["shots"] is None
    assert starter["position"] == "GK"
    assert starter["pitch_position"] is None
    assert (starter["goals"], starter["assists"], starter["yellow_cards"], starter["red_cards"]) == (2, 1, 1, 1)
    assert data["home"]["bench"][0]["goals"] == 0
    assert data["home"]["crest"] == "h.png"
    assert data["home"]["color"] == "#111"
    assert data["away"]["crest"] == "a.png"


def test_match_detail_rejects_bad_queries_without_calling_fotmob(client, monkeypatch):
    find = Mock()
    monkeypatch.setattr(matches_detail, "find_fixture", find)
    assert client.get("/matches/detail?date=2026-09-20&home=Home&away=Away").status_code == 400
    assert client.get("/matches/detail?league=ZZ&date=2026-09-20&home=Home&away=Away").status_code == 400
    find.assert_not_called()


def test_unmatched_fixture_does_not_fetch_the_match_page(client, monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(matches_detail, "find_fixture", lambda *args: None)
    monkeypatch.setattr(matches_detail, "fetch_match_content", fetch)
    data = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away").get_json()
    assert data == {"available": False, "reason": "Could not match this fixture on FotMob."}
    fetch.assert_not_called()


def test_match_detail_surfaces_fotmob_errors(client, monkeypatch):
    monkeypatch.setattr(matches_detail, "find_fixture", Mock(side_effect=FotMobError("FotMob is down", status_code=502)))
    resp = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away")
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "FotMob is down"


def test_match_assets_reuse_the_existing_page_fetch(monkeypatch):
    import fotmob_client
    monkeypatch.setattr(fotmob_client, "_fetch_page_props", lambda path: {
        "content": {"lineup": {}},
        "general": {"teamColors": {"darkMode": {"home": "#C63527", "away": "#FFFFFF"}}},
        "seo": {"eventJSONLD": {"homeTeam": {"logo": "home.png"}, "awayTeam": {"logo": "away.png"}}},
    })
    content = fotmob_client.fetch_match_content("/test-assets")
    assert content["teamAssets"]["home"] == {"crest": "home.png", "color": "#C63527"}
    assert content["teamAssets"]["away"]["crest"] == "away.png"

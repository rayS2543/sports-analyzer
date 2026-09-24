from routes import matches_detail


def test_match_detail_preserves_pitch_and_shot_data(client, monkeypatch):
    player = {"id": 7, "name": "Player", "shirtNumber": "9", "isCaptain": True,
              "verticalLayout": {"x": 0.3, "y": 0.8}}
    team = {"id": 1, "name": "Home", "formation": "4-4-2", "starters": [player]}
    shot = {"id": 8, "teamId": 1, "playerId": 7, "x": 94, "y": 34,
            "expectedGoals": 0.42, "period": "SecondHalf"}
    content = {"lineup": {"homeTeam": team, "awayTeam": {**team, "id": 2}},
               "shotmap": {"shots": [shot, {**shot, "x": None}, {**shot, "y": 80}]}}
    monkeypatch.setattr(matches_detail, "find_fixture", lambda *args: {"page_url": "/match"})
    monkeypatch.setattr(matches_detail, "fetch_match_content", lambda *args: content)
    data = client.get("/matches/detail?league=PD&date=2026-09-20&home=Home&away=Away").get_json()
    assert data["home"]["starters"][0]["pitch_position"] == {"x": 0.3, "y": 0.8}
    assert data["home"]["starters"][0]["captain"] is True
    assert len(data["shots"]) == 1
    assert data["shots"][0]["expectedGoals"] == 0.42
    assert data["away"]["id"] == 2


def test_missing_coverage_and_invalid_positions():
    assert matches_detail._build_shots(None) is None
    assert matches_detail._build_shots({"shots": []}) == []
    team = matches_detail._build_team({"starters": [{"verticalLayout": {"x": -1, "y": 0.5}}]})
    assert team["starters"][0]["pitch_position"] is None


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

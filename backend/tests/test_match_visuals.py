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


def test_summary_links_each_goal_to_its_shot_and_hides_unstarted_matches():
    shots = [{"id": 5, "playerId": 7, "min": 25, "eventType": "Goal"},
             {"id": 6, "playerId": 7, "min": 25, "eventType": "AttemptSaved"}]
    goal = {"side": "home", "player_id": 7, "name": "Player", "minute": 25, "added": None, "own_goal": False}
    summary = {"started": True, "scores": [1, 0], "places": [7, None], "goals": [goal, {**goal, "minute": 80}]}
    built = matches_detail._build_summary(summary, shots)
    assert (built["home_score"], built["away_score"], built["home_place"], built["away_place"]) == (1, 0, 7, None)
    assert [g["shot_id"] for g in built["goals"]] == [5, None]
    assert matches_detail._build_summary({**summary, "started": False}, shots) is None
    assert matches_detail._build_summary(None, shots) is None

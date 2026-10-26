from unittest.mock import Mock, patch

import pytest
import requests


def response(data):
    return Mock(json=lambda: data, raise_for_status=lambda: None)


def test_discovers_provider_fixture_ids(client):
    data = {"events": [{"id": "748191", "name": "Getafe at Barcelona", "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"displayName": "Barcelona"}},
        {"homeAway": "away", "team": {"displayName": "Getafe"}},
    ]}]}]}
    with patch("routes.var_clips.requests.get", return_value=response(data)) as get:
        result = client.get("/var/fixtures?league=PD&date=2025-09-21")
    assert result.status_code == 200
    assert result.json["fixtures"][0]["home"] == "Barcelona"
    assert result.json["fixtures"][0]["id"] == "748191"
    assert get.call_args.kwargs["params"] == {"dates": "20250921"}


def test_clips_keep_provenance_without_claiming_analysis(client):
    source = "https://espnmedia-cdn.akamaized.net/espn/example.mp4"
    data = {"videos": [{"id": 42, "headline": "Highlights", "duration": 74, "links": {
        "source": {"href": source}, "web": {"href": "https://www.espn.com/video/clip?id=42"},
    }}, {"id": 43, "links": {"source": {"href": "http://127.0.0.1/private"}}}]}
    with patch("routes.var_clips.requests.get", return_value=response(data)) as get:
        first = client.get("/var/clips?league=PD&event=748191")
        client.get("/var/clips?league=PD&event=748191")
    assert first.status_code == 200
    assert first.json["analysis_status"] == "not_analyzed"
    assert first.json["clips"][0]["source_url"] == source
    assert len(first.json["clips"]) == 1
    assert get.call_count == 1


@pytest.mark.parametrize("url", ["/var/fixtures?date=2025-02-30", "/var/fixtures?date=20250921", "/var/clips?event=../secret", "/var/clips?league=bad&event=42"])
def test_invalid_inputs_do_not_call_provider(client, url):
    with patch("routes.var_clips.requests.get") as get:
        assert client.get(url).status_code == 400
        get.assert_not_called()


def test_no_footage_is_distinct_from_provider_failure(client):
    with patch("routes.var_clips.requests.get", return_value=response({})):
        assert client.get("/var/clips?event=42").json["clips"] == []
    with patch("routes.var_clips.requests.get", side_effect=requests.Timeout):
        assert client.get("/var/clips?event=43").status_code == 502


def test_classify_separates_recaps_from_single_incidents():
    from routes.var_clips import classify
    assert classify("Real Madrid's opener wiped off by VAR", 48) == "offside"
    assert classify("Carlos Espi's bicycle kick ruled out after VAR review", 58) == "offside"
    assert classify("Mbapp\u00e9 is sent off for reckless challenge", 65) == "foul"
    assert classify("Real Madrid vs. Alav\u00e9s highlights", 90) == "highlights"
    assert classify("Goal ruled out for offside", 300) == "highlights"  # too long to be one incident
    assert classify("Great save by the keeper", 30) == "other"
    assert classify(None, None) == "other"


def test_discover_lists_short_offside_clips_across_days_and_skips_recaps(client):
    def video(i, title, seconds):
        return {"id": i, "headline": title, "duration": seconds, "links": {"source": {"href": f"https://espnmedia-cdn.akamaized.net/{i}.mp4"}}}

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            day = params["dates"]
            return response({"events": [{"id": day, "name": f"Match {day}", "competitions": [{"status": {"type": {"state": "post"}}}]},
                                         {"id": "live", "name": "Live", "competitions": [{"status": {"type": {"state": "in"}}}]}]})
        return response({"videos": [video(1, "Goal wiped off by VAR", 40), video(2, "Match highlights", 60), video(3, "Goal ruled out", 400)]})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-02")
    assert result.status_code == 200
    assert [(c["date"], c["id"], c["kind"]) for c in result.json["clips"]] == [("2026-03-02", "1", "offside"), ("2026-03-01", "1", "offside")]
    assert all(c["event"] != "live" for c in result.json["clips"])


@pytest.mark.parametrize("query", ["league=bad&from=2026-03-01&to=2026-03-02", "from=2026-03-01&to=2026-04-30", "from=2026-03-05&to=2026-03-01",
                                    "from=nope&to=2026-03-02", "from=2026-03-01&to=2026-03-02&kind=weird"])
def test_discover_rejects_bad_ranges_without_calling_the_provider(client, query):
    with patch("routes.var_clips.requests.get") as get:
        assert client.get(f"/var/discover?{query}").status_code == 400
    get.assert_not_called()


def test_discover_finds_var_offside_reviews_from_commentary_and_attaches_a_named_clip(client):
    commentary = [
        {"text": "Offside, Real Madrid. Carlos Esp\u00ed is caught offside.", "time": {"displayValue": "87'"}},
        {"text": "GOAL OVERTURNED BY VAR: Carlos Esp\u00ed (Real Madrid) scores but the goal is ruled out after a VAR review.", "time": {"displayValue": "87'"}},
        {"text": "VAR Decision: No Goal Real Betis 1-0 Real Madrid.", "time": {"displayValue": "89'"}},
        {"text": "Offside, Real Betis. Fran Garc\u00eda is caught offside.", "time": {"displayValue": "73'"}},
        {"text": "VAR Decision: Goal Barcelona 1-0 Getafe.", "time": {"displayValue": "20'"}},
    ]
    videos = [{"id": 1, "headline": "Carlos Espi's incredible bicycle kick ruled out", "duration": 58, "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/1.mp4"}}},
              {"id": 2, "headline": "Mbappe misses penalty", "duration": 44, "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/2.mp4"}}}]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [{"id": "9", "name": "Real Betis vs Real Madrid", "competitions": [{"status": {"type": {"state": "post"}}}]}]})
        return response({"videos": videos, "commentary": commentary})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-09-04&to=2026-09-04")
    reviews = result.json["reviews"]
    assert [(r["minute"], r["player"], r["outcome"], r["clip"] and r["clip"]["id"]) for r in reviews] == [("87'", "Carlos Esp\u00ed", "goal ruled out", "1")]


def test_a_review_without_a_named_clip_falls_back_to_the_matchs_short_highlights_reel(client):
    commentary = [{"text": "Offside, Celta Vigo. Mikel Oyarzabal is caught offside.", "time": {"displayValue": "48'"}},
                  {"text": "GOAL OVERTURNED BY VAR: Mikel Oyarzabal (Real Sociedad) scores but the goal is ruled out after a VAR review.", "time": {"displayValue": "48'"}}]
    source = lambda i: {"source": {"href": f"https://espnmedia-cdn.akamaized.net/{i}.mp4"}}
    videos = [{"id": 1, "headline": "Celta Vigo vs. Real Sociedad - Game Highlights", "duration": 74, "links": source(1)},
              {"id": 2, "headline": "Full match highlights", "duration": 600, "links": source(2)},
              {"id": 3, "headline": "Andrei Radu makes a great save", "duration": 20, "links": source(3)}]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [{"id": "5", "name": "Real Sociedad at Celta Vigo", "competitions": [{"status": {"type": {"state": "post"}}}]}]})
        return response({"videos": videos, "commentary": commentary})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        review = client.get("/var/discover?league=PD&from=2026-10-19&to=2026-10-19").json["reviews"][0]
    assert review["clip"] is None and review["highlights"]["id"] == "1"  # the 10-minute reel is too long to be one incident


def test_classify_tags_goal_clips_but_not_penalties_or_saves():
    from routes.var_clips import classify
    assert classify("Pablo Dur\u00e1n gets on the scoresheet for Celta Vigo", 61) == "goal"
    assert classify("Lamine Yamal doubles Barcelona's lead", 66) == "goal"
    assert classify("Carlos Soler scores penalty goal vs. Valencia", 43) == "other"  # a penalty has no offside to check
    assert classify("Andrei Radu makes a great save", 20) == "other"
    assert classify("Mbapp\u00e9 scores in the 11'", 50) == "goal"


def test_every_league_the_var_page_offers_is_a_provider_league():
    from routes.var_clips import ESPN_LEAGUES
    assert {"PD", "PL", "SA", "BL1", "FL1", "CL"} <= set(ESPN_LEAGUES)  # the picker lists these; an unknown one is a 400


@pytest.mark.parametrize("text,expected", [
    ("44656413", "44656413"),
    (" 44656413 ", "44656413"),
    ("https://www.espn.com/watch/syndicatedplayer/_/id/44656413", "44656413"),
    ("https://www.espn.com/video/clip/_/id/44656413/kylian-mbappe-is-sent-off", "44656413"),
    ("https://www.espn.com/video/clip?id=44656413", "44656413"),
    ("https://www.espn.com/soccer/story/_/id/44656783/alaves-vs-real-madrid", None),  # an article id is not a video id
    ("https://evil.example/watch/x/_/id/44656413", None),
    ("https://www.espn.com.evil.example/video/clip?id=44656413", None),
    ("javascript:alert(1)", None),
    ("", None),
])
def test_clip_id_from_accepts_only_espn_video_links_or_ids(text, expected):
    from routes.var_clips import clip_id_from
    assert clip_id_from(text) == expected


def test_a_clip_is_looked_up_by_link_from_espns_video_api_with_a_fixed_host(client):
    source = "https://espnmedia-cdn.akamaized.net/espn/media/mbappe.mp4"
    data = {"videos": [{"id": 44656413, "headline": "Mbappé is sent off", "duration": 65, "links": {
        "source": {"href": source}, "web": {"href": "https://www.espn.com/video/clip?id=44656413"}}}]}
    with patch("routes.var_clips.requests.get", return_value=Mock(status_code=200, json=lambda: data, raise_for_status=lambda: None)) as get:
        result = client.get("/var/clip?link=https://www.espn.com/watch/syndicatedplayer/_/id/44656413")
    assert result.status_code == 200
    assert result.json["clip"] == {"id": "44656413", "title": "Mbappé is sent off", "duration_seconds": 65, "source_url": source,
                                   "page_url": "https://www.espn.com/video/clip?id=44656413"}
    assert get.call_args.args[0] == "https://api-app.espn.com/v1/video/clips/44656413"


def test_a_clip_lookup_that_cannot_resolve_is_a_clean_error(client):
    with patch("routes.var_clips.requests.get") as get:
        assert client.get("/var/clip?link=https://example.com/video/clip?id=44656413").status_code == 400
        assert client.get("/var/clip").status_code == 400
    get.assert_not_called()
    with patch("routes.var_clips.requests.get", return_value=Mock(status_code=404)):
        assert client.get("/var/clip?link=44656413").status_code == 404
    unusable = {"videos": [{"id": 44656413, "headline": "x", "links": {"source": {"href": "http://127.0.0.1/private.mp4"}}}]}
    with patch("routes.var_clips.requests.get", return_value=Mock(status_code=200, json=lambda: unusable, raise_for_status=lambda: None)):
        assert client.get("/var/clip?link=44656413").status_code == 404  # a source off ESPN's CDN is not used

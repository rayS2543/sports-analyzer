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

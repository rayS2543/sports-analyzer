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


def test_clips_drop_credentialed_lookalike_and_nonstandard_urls(client):
    cdn = "espnmedia-cdn.akamaized.net"
    data = {"videos": [
        {"id": 1, "headline": "credentials", "duration": 10, "links": {
            "source": {"href": f"https://user:secret@{cdn}/a.mp4"},
            "web": {"href": "https://www.espn.com/video/clip?id=1"},
        }},
        {"id": 2, "headline": "odd port", "duration": 10, "links": {"source": {"href": f"https://{cdn}:444/a.mp4"}}},
        {"id": 3, "headline": "lookalike", "duration": 10, "links": {
            "source": {"href": f"https://{cdn}.evil.example/a.mp4"},
            "web": {"href": "https://notespn.com/video"},
        }},
        {"id": 4, "headline": "page only", "duration": 10, "links": {"web": {"href": "https://espn.com/video/clip?id=4"}}},
    ]}
    with patch("routes.var_clips.requests.get", return_value=response(data)):
        clips = client.get("/var/clips?league=PD&event=42").json["clips"]
    assert [(c["id"], c["source_url"], c["page_url"]) for c in clips] == [
        ("1", None, "https://www.espn.com/video/clip?id=1"),
        ("4", None, "https://espn.com/video/clip?id=4"),
    ]


def test_discover_keeps_a_confirmed_offside_goal_and_will_not_attach_a_recap(client):
    """A goal that stands after an offside check is still a review. A headline that
    names the player is not enough when the clip is a recap or longer than one incident.
    Added time (55'+2) shares the minute with the VAR line (55')."""
    commentary = [
        {"text": "VAR Decision: Goal Barcelona 1-0 Getafe.", "time": {"displayValue": "20'"}},
        {"text": "Offside, Barcelona. Robert Lewandowski is caught offside.", "time": {"displayValue": "20'"}},
        {"text": "Goal overturned by VAR: Ferran Torres (Barcelona) scores but the goal is ruled out after a VAR review.", "time": {"displayValue": "55'"}},
        {"text": "Offside, Barcelona. Ferran Torres is caught offside.", "time": {"displayValue": "55'+2"}},
    ]
    videos = [
        {"id": 1, "headline": "Robert Lewandowski highlights", "duration": 40, "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/1.mp4"}}},
        {"id": 2, "headline": "Getafe chance", "duration": 30, "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/2.mp4"}}},
        {"id": 3, "headline": "Ferran Torres goal ruled out", "duration": 200, "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/3.mp4"}}},
    ]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [{"id": "9", "name": "Getafe vs Barcelona", "competitions": [{"status": {"type": {"state": "post"}}}]}]})
        return response({"videos": videos, "commentary": commentary})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-09-04&to=2026-09-04")
    assert result.status_code == 200
    assert [(r["minute"], r["player"], r["outcome"], r["clip"]) for r in result.json["reviews"]] == [
        ("20'", "Robert Lewandowski", "goal confirmed", None),
        ("55'", "Ferran Torres", "goal ruled out", None),
    ]


def test_discover_counts_a_failed_event_and_foul_kind_skips_offside_reviews(client):
    def video(i, title, seconds):
        return {"id": i, "headline": title, "duration": seconds, "links": {"source": {"href": f"https://espnmedia-cdn.akamaized.net/{i}.mp4"}}}

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [
                {"id": "good", "name": "A vs B", "competitions": [{"status": {"type": {"state": "post"}}}]},
                {"id": "bad", "name": "C vs D", "competitions": [{"status": {"type": {"state": "post"}}}]},
                {"id": "live", "name": "Live", "competitions": [{"status": {"type": {"state": "in"}}}]},
            ]})
        if params.get("event") == "bad":
            raise requests.Timeout("slow")
        return response({"videos": [video(1, "Straight red card", 28), video(2, "Goal wiped off by VAR", 36), video(3, "Full match recap", 90)],
                         "commentary": [
                             {"text": "Offside, Home. Someone is caught offside.", "time": {"displayValue": "10'"}},
                             {"text": "VAR Decision: No Goal Home 0-0 Away.", "time": {"displayValue": "10'"}},
                         ]})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PL&from=2026-03-01&to=2026-03-01&kind=foul")
    assert result.status_code == 200
    assert result.json["events_failed"] == 1
    assert result.json["reviews"] == []
    assert [(c["id"], c["kind"]) for c in result.json["clips"]] == [("1", "foul")]


def test_discover_returns_502_when_the_scoreboard_fails(client):
    with patch("routes.var_clips.requests.get", side_effect=requests.Timeout):
        assert client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-01").status_code == 502


def test_discover_orders_clipped_reviews_first_and_treats_no_goal_as_ruled_out(client):
    def video(i, title, seconds):
        return {"id": i, "headline": title, "duration": seconds, "links": {"source": {"href": f"https://espnmedia-cdn.akamaized.net/{i}.mp4"}}}

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            day = params["dates"]
            return response({"events": [{"id": day, "name": f"Match {day}", "competitions": [{"status": {"type": {"state": "post"}}}]}]})
        event = str(params.get("event"))
        if event == "20260302":
            return response({"videos": [video(9, "Unrelated save", 20)], "commentary": [
                {"text": "Offside, Sevilla. Youssef En-Nesyri is caught offside.", "time": {"displayValue": "12'"}},
                {"text": "VAR Decision: No Goal Sevilla 0-0 Valencia.", "time": {"displayValue": "12'"}},
            ]})
        return response({"videos": [video(1, "Carlos Espi goal ruled out", 40), video(2, "Reckless challenge, straight red", 35)], "commentary": [
            {"text": "Offside, Real Madrid. Carlos Espi is caught offside.", "time": {"displayValue": "87'"}},
            {"text": "Goal overturned by VAR: Carlos Espi (Real Madrid) scores but the goal is ruled out after a VAR review.", "time": {"displayValue": "87'"}},
        ]})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-02&kind=all")
    assert result.status_code == 200
    reviews = result.json["reviews"]
    assert [(r["date"], r["player"], r["outcome"], r["clip"] and r["clip"]["id"]) for r in reviews] == [
        ("2026-03-01", "Carlos Espi", "goal ruled out", "1"),
        ("2026-03-02", "Youssef En-Nesyri", "goal ruled out", None),
    ]
    assert [(c["date"], c["id"], c["kind"]) for c in result.json["clips"]] == [
        ("2026-03-02", "9", "other"),
        ("2026-03-01", "1", "offside"),
        ("2026-03-01", "2", "foul"),
    ]


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

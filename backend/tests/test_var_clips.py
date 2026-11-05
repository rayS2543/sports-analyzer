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


def _finished(event_id, name="Match"):
    return {"id": event_id, "name": name, "competitions": [{"status": {"type": {"state": "post"}}}]}


def _video(i, title, seconds, href="auto", page=None):
    links = {}
    if href == "auto":
        href = f"https://espnmedia-cdn.akamaized.net/{i}.mp4"
    if href is not None:
        links["source"] = {"href": href}
    if page:
        links["web"] = {"href": page}
    return {"id": i, "headline": title, "duration": seconds, "links": links}


def test_classify_keeps_a_120_second_incident_and_lets_offside_win_over_a_later_foul_word():
    from routes.var_clips import classify

    assert classify("Goal ruled out for offside", 120) == "offside"
    assert classify("Goal ruled out for offside", 120.1) == "highlights"
    assert classify("Match preview", 30) == "highlights"
    assert classify("Straight red for a reckless challenge", 40) == "foul"
    assert classify("Sent off, but the goal was offside", 40) == "offside"


def test_discover_allows_fourteen_calendar_days_and_rejects_the_next_day(client):
    with patch("routes.var_clips.requests.get", return_value=response({"events": []})) as get:
        ok = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-14")
    assert ok.status_code == 200
    assert get.call_count == 14
    with patch("routes.var_clips.requests.get") as get:
        assert client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-15").status_code == 400
    get.assert_not_called()


def test_discover_clip_choice_follows_the_surname_and_the_length_boundary(client):
    """Added time shares the minute. A recap, a first name, or a clip past 120 s does not get attached."""
    commentary = [
        {"text": "Offside, Real Madrid. Carlos Esp\u00ed is caught offside.", "time": {"displayValue": "87'"}},
        {"text": "GOAL OVERTURNED BY VAR: Carlos Esp\u00ed (Real Madrid) scores but the goal is ruled out after a VAR review.", "time": {"displayValue": "87'+2"}},
    ]
    videos = [
        _video(1, "Carlos Espi's full match recap", 80),
        _video(2, "Fran scores from the spot", 40),
        _video(3, "Espi bicycle kick", 120),
        _video(4, "Espi scores the second", 121),
        _video(5, "Espi with no file", 30, href=None, page="https://www.espn.com/video/clip?id=5"),
    ]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [_finished("9", "Real Betis vs Real Madrid")]})
        return response({"videos": videos, "commentary": commentary})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-09-04&to=2026-09-04")
    reviews = result.json["reviews"]
    assert result.status_code == 200
    assert len(reviews) == 1
    assert reviews[0]["minute"] == "87'"
    assert reviews[0]["outcome"] == "goal ruled out"
    assert reviews[0]["player"] == "Carlos Esp\u00ed"
    assert reviews[0]["clip"]["id"] == "3"
    assert result.json["events_failed"] == 0


def test_no_goal_stays_ruled_out_and_a_confirmed_goal_needs_the_offside_call(client):
    commentary = [
        {"text": "VAR Decision: Goal Barcelona 1-0 Getafe.", "time": {"displayValue": "20'"}},
        {"text": "Offside, Barcelona. Lamine Yamal is caught offside.", "time": {"displayValue": "20'"}},
        {"text": "Offside, Real Betis. Ayoze Perez is caught offside.", "time": {"displayValue": "89'"}},
        {"text": "VAR Decision: No Goal Real Betis 1-0 Real Madrid.", "time": {"displayValue": "89'"}},
        {"text": "Offside, Getafe. David Soria is caught offside.", "time": {"displayValue": "55'"}},
    ]
    videos = [_video(7, "Yamal goal stands", 45)]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            return response({"events": [_finished("9")]})
        return response({"videos": videos, "commentary": commentary})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        result = client.get("/var/discover?league=PD&from=2026-09-04&to=2026-09-04")
    reviews = result.json["reviews"]
    assert [(r["minute"], r["player"], r["outcome"], r["clip"] and r["clip"]["id"]) for r in reviews] == [
        ("20'", "Lamine Yamal", "goal confirmed", "7"),
        ("89'", "Ayoze Perez", "goal ruled out", None),
    ]


def test_discover_kind_filters_clips_and_puts_a_clipped_review_ahead_of_a_newer_one(client):
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            day = params["dates"]
            event = "newer" if day == "20260302" else "older"
            return response({"events": [_finished(event, f"Match {day}")]})
        if params.get("event") == "newer":
            return response({
                "commentary": [
                    {"text": "Offside, Osasuna. Ante Budimir is caught offside.", "time": {"displayValue": "3'"}},
                    {"text": "GOAL OVERTURNED BY VAR: Ante Budimir (Osasuna) scores.", "time": {"displayValue": "3'"}},
                ],
                "videos": [_video(1, "Match highlights", 200), _video(2, "Great save by the keeper", 30)],
            })
        return response({
            "commentary": [
                {"text": "Offside, Barcelona. Lamine Yamal is caught offside.", "time": {"displayValue": "8'"}},
                {"text": "VAR Decision: Goal Barcelona 1-0 Getafe.", "time": {"displayValue": "8'"}},
            ],
            "videos": [
                _video(3, "Yamal goal ruled out", 40),
                _video(4, "Player sent off for a reckless challenge", 50),
            ],
        })

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        offside = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-02")
        foul = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-02&kind=foul")
        everything = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-02&kind=all")

    assert [(r["date"], r["player"], r["clip"] and r["clip"]["id"]) for r in offside.json["reviews"]] == [
        ("2026-03-01", "Lamine Yamal", "3"),
        ("2026-03-02", "Ante Budimir", None),
    ]
    assert [(c["date"], c["id"], c["kind"]) for c in offside.json["clips"]] == [("2026-03-01", "3", "offside")]
    assert foul.json["reviews"] == []
    assert [(c["id"], c["kind"]) for c in foul.json["clips"]] == [("4", "foul")]
    assert [(c["date"], c["id"], c["kind"]) for c in everything.json["clips"]] == [
        ("2026-03-02", "2", "other"),
        ("2026-03-01", "4", "foul"),
        ("2026-03-01", "3", "offside"),
    ]
    assert [r["player"] for r in everything.json["reviews"]] == ["Lamine Yamal", "Ante Budimir"]


def test_one_event_summary_failure_is_counted_and_a_scoreboard_failure_is_502(client):
    commentary = [
        {"text": "Offside, Barcelona. Lamine Yamal is caught offside.", "time": {"displayValue": "8'"}},
        {"text": "VAR Decision: Goal Barcelona 1-0 Getafe.", "time": {"displayValue": "8'"}},
    ]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/scoreboard"):
            if params["dates"] == "20260302":
                raise requests.ConnectionError("down")
            return response({"events": [_finished("bad"), _finished("good", "Kept")]})
        if params.get("event") == "bad":
            raise requests.Timeout("slow")
        return response({"commentary": commentary, "videos": []})

    with patch("routes.var_clips.requests.get", side_effect=fake_get):
        kept = client.get("/var/discover?league=PD&from=2026-03-01&to=2026-03-01")
        failed = client.get("/var/discover?league=PD&from=2026-03-02&to=2026-03-02")
    assert kept.status_code == 200
    assert kept.json["events_failed"] == 1
    assert [r["match"] for r in kept.json["reviews"]] == ["Kept"]
    assert failed.status_code == 502


def test_clip_urls_stay_on_https_espn_hosts_without_credentials_or_another_port(client):
    videos = [
        _video(1, "creds", 10, href="https://user:pw@espnmedia-cdn.akamaized.net/a.mp4", page="https://www.espn.com/video/clip?id=1"),
        _video(2, "port", 10, href="https://espnmedia-cdn.akamaized.net:8443/a.mp4"),
        _video(3, "lookalike", 10, href="https://espnmedia-cdn.akamaized.net.evil.example/a.mp4"),
        _video(4, "page", 10, href=None, page="https://espn.com/soccer/video"),
        _video(5, "explicit-443", 10, href="https://espnmedia-cdn.akamaized.net:443/ok.mp4"),
        _video(6, "ok", 10),
    ]
    with patch("routes.var_clips.requests.get", return_value=response({"videos": videos})):
        result = client.get("/var/clips?league=PD&event=748191")
    clips = result.json["clips"]
    assert [(c["id"], c["source_url"] is not None, c["page_url"] is not None) for c in clips] == [
        ("1", False, True),
        ("4", False, True),
        ("5", True, False),
        ("6", True, False),
    ]

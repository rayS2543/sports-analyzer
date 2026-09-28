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

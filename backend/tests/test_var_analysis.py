import json
from unittest.mock import Mock, patch

import pytest
import requests

from routes import var_analysis

SOURCE = "https://espnmedia-cdn.akamaized.net/espn/media/clip.mp4"
SUMMARY = {
    "videos": [{"id": 46338651, "headline": "Highlights", "links": {"source": {"href": SOURCE}}}],
    # Trimmed from the real ESPN summary for event 748191 (plus shapes seen in other events).
    "keyEvents": [
        {"id": "1", "type": {"id": "94", "type": "yellow-card"}, "text": "Mario Martín (Getafe) is shown the yellow card for a bad foul.",
         "period": {"number": 1}, "clock": {"value": 176.0, "displayValue": "3'"}, "team": {"displayName": "Getafe"}},
        {"id": "3", "type": {"id": "70", "type": "goal"}, "text": "Goal! Barcelona 1, Getafe 0.",
         "period": {"number": 1}, "clock": {"value": 853.0, "displayValue": "15'"}, "team": {"displayName": "Barcelona"}},
        {"id": "9", "type": {"id": "93", "type": "red-card"}, "text": "Robert Sánchez (Chelsea) is shown the red card.",
         "period": {"number": 2}, "clock": {"value": 3000.0, "displayValue": "50'"}, "team": {"displayName": "Chelsea"}},
    ],
    "commentary": [
        {"text": "Lineups are announced and players are warming up."},
        {"text": "x", "play": {"id": "1", "type": {"type": "yellow-card"}, "text": "Mario Martín (Getafe) is shown the yellow card for a bad foul.",
                               "period": {"number": 1}, "clock": {"value": 176.0, "displayValue": "3'"}, "team": {"displayName": "Getafe"}}},
        {"text": "x", "play": {"id": "2", "type": {"id": "68", "type": "offside"}, "text": "Offside, Getafe. Borja Mayoral is caught offside.",
                               "period": {"number": 1}, "clock": {"value": 360.0, "displayValue": "6'"}, "team": {"displayName": "Getafe"}}},
        {"text": "x", "play": {"id": "4", "type": {"id": "66", "type": "foul"}, "text": "Foul by Pedri (Barcelona).",
                               "period": {"number": 1}, "clock": {"value": 400.0, "displayValue": "7'"}, "team": {"displayName": "Barcelona"}}},
        {"text": "x", "play": {"id": "5", "type": {"id": "172", "type": "var---referee-decision-cancelled"}, "text": "VAR Decision: No Penalty Como.",
                               "period": {"number": 1}, "clock": {"value": 2700.0, "displayValue": "45'+6'"}, "team": {"displayName": "Como"}}},
        {"text": "x", "play": {"id": "6", "type": {"id": "98", "type": "penalty---scored"}, "text": "Goal! Alaves 1, Sevilla 1. Carlos Vicente converts the penalty.",
                               "period": {"number": 2}, "clock": {"value": 2900.0, "displayValue": "48'"}, "team": {"displayName": "Alaves"}}},
    ],
}


def response(data):
    return Mock(json=lambda: data, raise_for_status=lambda: None)


class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("VAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VAR_CV_PYTHON", str(python))
    monkeypatch.setattr(var_analysis, "_job", None)
    return tmp_path / "data"


WINDOW = "?start=12&end=17"


def start(client, clip="46338651", process=None, window=(12, 17)):
    with patch("routes.var_clips.requests.get", return_value=response(SUMMARY)) as get, \
            patch("routes.var_analysis.subprocess.Popen", return_value=process or FakeProcess()) as popen:
        result = client.post("/var/analyze", json={"league": "PD", "event": "748191", "clip": clip, "start": window[0], "end": window[1]})
    return result, get, popen


def test_analyze_uses_discovered_url_and_reports_progress(client, env):
    result, _, popen = start(client)
    assert result.status_code == 202 and result.json == {"clip": "46338651", "window": "12.0-17.0", "status": "queued"}
    args = popen.call_args.args[0]
    flag = lambda name: args[args.index(name) + 1]
    assert flag("--source-url") == SOURCE
    assert (flag("--video"), flag("--start"), flag("--end")) == (str(env.resolve() / "46338651" / "video.mp4"), "12.0", "17.0")
    assert flag("--out") == str(env.resolve() / "46338651" / "12.0-17.0")
    assert popen.call_args.kwargs["cwd"].name == "cv"
    assert client.get("/var/analysis/46338651" + WINDOW).json["status"] == "running"
    (env / "46338651" / "12.0-17.0" / "progress.json").write_text(json.dumps({"stage": "detect", "progress": 0.5, "message": "m"}))
    assert client.get("/var/analysis/46338651" + WINDOW).json["progress"]["stage"] == "detect"
    assert start(client, window=(12.04, 16.96))[0].json["status"] == "running"  # same rounded window
    assert start(client, window=(20, 25))[0].status_code == 409
    assert start(client, clip="1")[0].status_code == 409
    assert client.get("/var/analysis/46338651?start=20&end=25").json["status"] == "none"


def test_done_and_failed_from_files(client, env):
    out = env / "46338651" / "12.0-17.0"
    out.mkdir(parents=True)
    assert client.get("/var/analysis/46338651" + WINDOW).json == {
        "clip": "46338651", "window": "12.0-17.0", "status": "none", "progress": None, "error": None, "result": None}
    (out / "error.json").write_text(json.dumps({"error": "no calibration"}))
    assert client.get("/var/analysis/46338651" + WINDOW).json["error"] == "no calibration"
    (out / "analysis.json").write_text(json.dumps({"version": 1}))
    body = client.get("/var/analysis/46338651" + WINDOW).json
    assert body["status"] == "done" and body["result"] == {"version": 1}
    assert start(client)[0].status_code == 200


def test_windows_lists_prior_analyses(client, env):
    assert client.get("/var/windows/46338651").json["windows"] == []
    clip = env / "46338651"
    for key, name in [("30.5-33.0", "error.json"), ("12.0-17.0", "analysis.json")]:
        (clip / key).mkdir(parents=True)
        (clip / key / name).write_text("{}")
    (clip / "5.0-6.0").mkdir()  # empty: never started
    (clip / "12-17").mkdir()  # not a canonical key
    (clip / "video.mp4").write_bytes(b"")
    assert client.get("/var/windows/46338651").json["windows"] == [
        {"start": 12.0, "end": 17.0, "key": "12.0-17.0", "status": "done"},
        {"start": 30.5, "end": 33.0, "key": "30.5-33.0", "status": "failed"}]


@pytest.mark.parametrize("window", [(5, 5), (6, 5), (-1, 3), (0, 10.1), (0, "../x"), ("nan", 3), (0, "inf"), (True, 3), (None, 3)])
def test_invalid_windows_rejected(client, window):
    result, get, popen = start(client, window=window)
    assert result.status_code == 400
    get.assert_not_called()
    popen.assert_not_called()


def test_window_rounding():
    from routes.var_analysis import _window
    assert _window(0, 10) == "0.0-10.0"
    assert _window("12.04", "16.96") == "12.0-17.0"
    assert _window(-0.04, 3) == "0.0-3.0"
    assert _window(0.3, 10.3) == "0.3-10.3"


def test_crashed_process_is_failed(client):
    process = FakeProcess()
    start(client, process=process)
    process.code = -9
    body = client.get("/var/analysis/46338651" + WINDOW).json
    assert body["status"] == "failed" and "code -9" in body["error"]


def test_clip_not_in_event_is_rejected(client):
    result, _, popen = start(client, clip="999")
    assert result.status_code == 404
    popen.assert_not_called()


def test_missing_cv_env_is_503(client, monkeypatch, tmp_path):
    monkeypatch.setenv("VAR_CV_PYTHON", str(tmp_path / "nope"))
    result, get, _ = start(client)
    assert result.status_code == 503 and "cv/setup.sh" in result.json["error"]
    get.assert_not_called()


@pytest.mark.parametrize("url", ["/var/analysis/..%2Fetc" + WINDOW, "/var/analysis/1", "/var/analysis/1?start=0&end=../../x",
                                 "/var/windows/abc", "/var/video/abc", "/var/official?event=../x"])
def test_invalid_ids(client, url):
    assert client.get(url).status_code in (400, 404)


def test_invalid_analyze_body(client):
    assert client.post("/var/analyze", json={"league": "PD", "event": "1", "clip": "../x", "url": SOURCE}).status_code == 400


def test_video_404_then_range(client, env):
    assert client.get("/var/video/46338651").status_code == 404
    (env / "46338651").mkdir(parents=True)
    (env / "46338651" / "video.mp4").write_bytes(b"0123456789")
    result = client.get("/var/video/46338651", headers={"Range": "bytes=2-5"})
    assert result.status_code == 206 and result.data == b"2345"
    assert result.headers["Content-Type"] == "video/mp4"


def test_official_events(client):
    with patch("routes.var_clips.requests.get", return_value=response(SUMMARY)):
        events = client.get("/var/official?league=PD&event=748191").json["events"]
    assert [e["type"] for e in events] == ["yellow_card", "offside", "goal", "var", "penalty", "red_card"]
    assert events[1] == {"type": "offside", "clock": "6'", "team": "Getafe", "text": "Offside, Getafe. Borja Mayoral is caught offside."}
    with patch("routes.var_clips.requests.get", side_effect=requests.Timeout):
        assert client.get("/var/official?event=1").status_code == 502


def test_assess_uses_nearest_frame_in_shot(client, env):
    players = [{"track_id": 7, "team": "A", "role": "player", "x": 83.0, "y": 30.0},
               {"track_id": 3, "team": "B", "role": "player", "x": 80.0, "y": 30.0},
               {"track_id": 1, "team": "B", "role": "goalkeeper", "x": 100.0, "y": 34.0}]
    calibrated = {"ok": True, "reprojection_error_m": 0.4, "keypoints": 9}
    analysis = {"version": 1, "pitch": {"length_m": 105.0, "width_m": 68.0}, "video": {"sampled_fps": 5},
                "shots": [{"id": 0, "start": 0, "end": 2.0}, {"id": 1, "start": 2.1, "end": 5}],
                "frames": [{"t": 1.8, "shot": 0, "calibration": calibrated, "ball": {"x": 60.0, "y": 30.0}, "players": players},
                           {"t": 2.2, "shot": 1, "calibration": {"ok": False}, "ball": None, "players": []}]}
    (env / "46338651" / "0.0-5.0").mkdir(parents=True)
    (env / "46338651" / "0.0-5.0" / "analysis.json").write_text(json.dumps(analysis))
    body = {"clip": "46338651", "start": 0, "end": 5, "t": 2.0, "attacker_track_id": 7, "attacking_team": "A"}
    result = client.post("/var/assess", json=body).json
    assert result["frame_t"] == 1.8 and result["verdict"] == "offside" and result["attack_direction"] == "right"
    assert "not detected automatically" in result["reasons"][0]
    assert any("velocities unavailable" in r for r in result["reasons"])  # v1: no vx
    assert client.post("/var/assess", json={**body, "t": 2.15}).json["verdict"] == "inconclusive"
    assert client.post("/var/assess", json={**body, "attacking_team": "C"}).status_code == 400
    assert client.post("/var/assess", json={**body, "clip": "1"}).status_code == 404
    assert client.post("/var/assess", json={**body, "end": 6}).status_code == 404
    assert client.post("/var/assess", json={**body, "end": None}).status_code == 400


def v2_analysis(events):
    players = [{"track_id": 5, "team": "A", "role": "player", "x": 60.0, "y": 30.0, "vx": 2.0},
               {"track_id": 7, "team": "A", "role": "player", "x": 83.0, "y": 30.0, "vx": 6.0},
               {"track_id": 8, "team": "A", "role": "player", "x": 70.0, "y": 20.0, "vx": None},
               {"track_id": 3, "team": "B", "role": "player", "x": 80.0, "y": 30.0, "vx": -2.0},
               {"track_id": 4, "team": "B", "role": "player", "x": 75.0, "y": 40.0, "vx": 0.0},
               {"track_id": 20, "team": None, "role": "referee", "x": 90.0, "y": 10.0}]
    calibrated = {"ok": True, "reprojection_error_m": 0.4, "keypoints": 9, "source": "detected", "homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    frames = [{"t": 12.0, "shot": 0, "calibration": calibrated, "ball": {"x": 60.0, "y": 30.0}, "players": players},
              {"t": 12.1, "shot": 0, "calibration": {"ok": False, "homography": None}, "ball": None, "players": []}]
    return {"version": 2, "window": {"start": 12.0, "end": 17.0}, "pitch": {"length_m": 105.0, "width_m": 68.0},
            "video": {"sampled_fps": 10}, "shots": [{"id": 0, "start": 12.0, "end": 17.0}], "frames": frames, "events": events}


def write(env, analysis, key="12.0-17.0"):
    (env / "46338651" / key).mkdir(parents=True, exist_ok=True)
    (env / "46338651" / key / "analysis.json").write_text(json.dumps(analysis))


REVIEW = {"clip": "46338651", "start": 12, "end": 17}
PASS = {"type": "pass", "t": 12.0, "passer_track_id": 5, "team": "A", "confidence": 0.72, "reason": "ball left #5 at 14 m/s"}


def test_review_assesses_every_pass(client, env):
    write(env, v2_analysis([PASS, {"type": "shot", "t": 12.1}, {**PASS, "t": 12.1, "passer_track_id": 7}]))
    body = client.post("/var/review", json=REVIEW).json
    assert body["message"] is None and len(body["reviews"]) == 2
    first = body["reviews"][0]
    assert first["event"] == PASS
    key = first["key"]
    assert key["attacker_track_id"] == 7 and key["verdict"] == "offside" and key["frame_t"] == 12.0
    assert key["attack_direction"] == "right" and key["second_last_defender_track_id"] == 3  # keeper unseen → deepest outfielder
    assert "confidence 0.72" in key["reasons"][0] and "ball left #5" in key["reasons"][0]
    assert any("Timing" in r for r in key["reasons"])
    assert first["candidates"] == [{"track_id": 7, "verdict": "offside", "margin_m": 3.0},
                                   {"track_id": 8, "verdict": "onside", "margin_m": -10.0}]
    assert body["reviews"][1]["key"]["verdict"] == "inconclusive"  # uncalibrated frame


def test_review_falls_back_to_passers_team(client, env):
    write(env, v2_analysis([{**PASS, "team": None}]))
    assert client.post("/var/review", json=REVIEW).json["reviews"][0]["key"]["attacker_track_id"] == 7


@pytest.mark.parametrize("events, text", [([], "No pass was detected"), (None, "No pass was detected"),
                                          ("missing", "predates automatic pass detection")])
def test_review_without_passes_explains(client, env, events, text):
    analysis = v2_analysis(events)
    if events == "missing":
        del analysis["events"]
        analysis["version"] = 1
    write(env, analysis)
    body = client.post("/var/review", json=REVIEW).json
    assert body["reviews"] == [] and text in body["message"]


def test_review_errors(client, env):
    assert client.post("/var/review", json=REVIEW).status_code == 404
    write(env, {"version": 2, "frames": []})
    assert client.post("/var/review", json=REVIEW).status_code == 404
    for bad in ({**REVIEW, "clip": "../x"}, {**REVIEW, "end": 30}, {"clip": "46338651"}):
        assert client.post("/var/review", json=bad).status_code == 400

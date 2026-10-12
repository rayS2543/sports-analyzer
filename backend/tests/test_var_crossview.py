"""Cross-view calibration job (Amendment 4), the shared heavy-job slot, and ESPN angle discovery."""
import json
import os
import threading
from unittest.mock import Mock, patch

import pytest
import requests

from routes import var_analysis, var_fouls

CLIP = "44656413"
REPLAY, LIVE = "23.0-28.0", "1.0-7.0"
URL = f"/var/analysis/{CLIP}/crossview"
Q = f"{URL}?start=23&end=28"
BODY = {"start": 23, "end": 28, "live": {"start": 1, "end": 7}, "anchor": [3.27, 23.223]}


class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class Step:
    """One CLI run: optionally waits for the test to release it, writes its output files, exits with code."""

    def __init__(self, code=0, writes=None, gate=None):
        self.code, self.writes, self.gate = code, writes or {}, gate

    def wait(self):
        if self.gate:
            self.gate.wait(5)
        for path, data in self.writes.items():
            path.write_text(json.dumps(data))
        return self.code


@pytest.fixture
def env(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("VAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VAR_CV_PYTHON", str(python))
    clip = tmp_path / "data" / CLIP
    for key in (REPLAY, LIVE):
        (clip / key).mkdir(parents=True)
        (clip / key / "analysis.json").write_text("{}")
    (clip / "video.mp4").write_bytes(b"x")
    return clip


@pytest.fixture
def cli(monkeypatch):
    """Popen replaced by a queue of Steps; records every command."""
    calls, steps = [], []

    def popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return steps.pop(0)
    monkeypatch.setattr(var_analysis.subprocess, "Popen", popen)
    yield calls, steps
    if var_analysis._crossview:
        var_analysis._crossview[2].thread.join(5)


def finish():
    var_analysis._crossview[2].thread.join(5)
    assert var_analysis._crossview[2].poll() is not None


def launched(calls, n):
    """Wait until the job thread has started its n-th CLI process."""
    for _ in range(500):
        if len(calls) >= n:
            return calls[n - 1][0]
        threading.Event().wait(0.01)
    raise AssertionError(f"CLI process {n} never started")


def flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_runs_crossview_then_fouls_holding_the_heavy_slot(client, env, cli):
    calls, steps = cli
    replay = env / REPLAY
    gate_xv, gate_fouls = threading.Event(), threading.Event()
    report = {"status": "done", "failure": None, "replay_shot": 0, "speed": 0.4, "calibrated_frames": 30, "frames": 42}
    steps += [Step(writes={replay / "crossview.json": report}, gate=gate_xv),
              Step(writes={replay / "fouls.progress.json": {"stage": "fouls", "progress": 0.5, "message": "pose 1/2"}}, gate=gate_fouls)]
    r = client.post(URL, json=BODY)
    assert r.status_code == 202
    assert r.json == {"clip": CLIP, "window": REPLAY, "live": {"clip": CLIP, "window": LIVE}, "status": "queued"}

    got = client.get(Q).json
    assert got["status"] == "running" and got["report"] is None and "Starting cross-view" in got["progress"]["message"]
    cmd, kwargs = launched(calls, 1), calls[0][1]
    assert cmd[1:3] == ["-m", "var_cv.crossview"] and kwargs["cwd"].name == "cv"
    assert flag(cmd, "--replay") == str(replay.resolve()) and flag(cmd, "--live") == str((env / LIVE).resolve())
    assert flag(cmd, "--video") == str((env / "video.mp4").resolve()) and flag(cmd, "--anchor") == "3.270:23.223"

    # One heavy CV job machine-wide: analysis, foul reviews and other cross-views all wait.
    assert client.post(URL, json=BODY).json["status"] == "running"
    assert client.post(URL, json={"start": 1, "end": 7, "live": {"start": 23, "end": 28}}).status_code == 409
    assert client.post("/var/fouls", json={"clip": CLIP, "start": 1, "end": 7}).status_code == 409
    with patch("routes.var_clips.requests.get") as espn:
        busy = client.post("/var/analyze", json={"league": "PD", "event": "704966", "clip": CLIP, "start": 40, "end": 45})
    assert busy.status_code == 409 and "calibrated from the live camera" in busy.json["error"]
    espn.assert_not_called()

    gate_xv.set()
    fouls_cmd = launched(calls, 2)  # the thread moves on to the foul re-run
    assert fouls_cmd[1:3] == ["-m", "var_cv.fouls"] and flag(fouls_cmd, "--out") == str((replay / "fouls.json").resolve())
    assert flag(fouls_cmd, "--analysis") == str((replay / "analysis.json").resolve())
    got = client.get(Q).json
    assert got["status"] == "running" and got["progress"]["stage"] == "fouls"
    assert got["progress"]["message"].startswith("Re-running the foul review")

    gate_fouls.set()
    finish()
    got = client.get(Q).json
    assert got["status"] == "done" and got["report"] == report and got["error"] is None and got["progress"] is None
    assert client.get(f"/var/windows/{CLIP}").json["windows"][1]["cross_view"] == "done"
    assert client.post(URL, json=BODY).status_code == 200  # done is not re-run
    assert len(calls) == 2


def test_honest_failure_skips_the_foul_rerun_and_can_be_retried(client, env, cli):
    calls, steps = cli
    report = {"status": "failed", "failure": "sync ambiguous", "notes": ["speeds 0.4 and 0.5 fit equally"]}
    steps.append(Step(writes={env / REPLAY / "crossview.json": report}))
    client.post(URL, json={k: v for k, v in BODY.items() if k != "anchor"})
    finish()
    assert len(calls) == 1 and "--anchor" not in calls[0][0]
    got = client.get(Q).json
    assert got["status"] == "failed" and got["error"] == "sync ambiguous" and got["report"] == report
    steps.append(Step(writes={env / REPLAY / "crossview.json": {"status": "done"}}))
    steps.append(Step())
    assert client.post(URL, json=BODY).status_code == 202


def test_crash_and_foul_rerun_failure_are_reported(client, env, cli):
    calls, steps = cli
    steps.append(Step(code=2))
    client.post(URL, json=BODY)
    finish()
    got = client.get(Q).json
    assert got["status"] == "failed" and "exited with code 2" in got["error"] and len(calls) == 1

    replay = env / REPLAY
    steps += [Step(writes={replay / "crossview.json": {"status": "done"}}),
              Step(code=1, writes={replay / "fouls.error.json": {"error": "RuntimeError: pose model missing"}})]
    assert client.post(URL, json=BODY).status_code == 202
    finish()
    got = client.get(Q).json
    assert got["status"] == "failed" and "re-running its foul review failed: RuntimeError: pose model missing" in got["error"]


def test_other_heavy_jobs_block_crossview_and_each_other(client, env, monkeypatch):
    monkeypatch.setattr(var_fouls, "_job", (CLIP, LIVE, FakeProcess()))
    r = client.post(URL, json=BODY)
    assert r.status_code == 409 and "having its challenges reviewed" in r.json["error"]
    with patch("routes.var_clips.requests.get") as espn:
        assert client.post("/var/analyze", json={"league": "PD", "event": "704966", "clip": CLIP, "start": 40, "end": 45}).status_code == 409
    espn.assert_not_called()
    monkeypatch.setattr(var_fouls, "_job", None)
    monkeypatch.setattr(var_analysis, "_job", (CLIP, "40.0-45.0", FakeProcess()))
    assert client.post(URL, json=BODY).status_code == 409
    assert client.post("/var/fouls", json={"clip": CLIP, "start": 23, "end": 28}).status_code == 409
    monkeypatch.setattr(var_analysis, "_job", (CLIP, "40.0-45.0", FakeProcess(code=0)))  # finished: slot free
    with patch("routes.var_fouls.subprocess.Popen", return_value=FakeProcess()):
        assert client.post("/var/fouls", json={"clip": CLIP, "start": 23, "end": 28}).status_code == 202


@pytest.mark.parametrize("body", [
    {**BODY, "start": 28, "end": 23},
    {**BODY, "end": 40},
    {**BODY, "live": None},
    {**BODY, "live": {"start": 1}},
    {**BODY, "live": {"clip": "../x", "start": 1, "end": 7}},
    {**BODY, "live": {"clip": 44656413, "start": 1, "end": 7}},
    {**BODY, "live": {"start": 23, "end": 28}},  # the replay itself
    {**BODY, "anchor": [3.27]},
    {**BODY, "anchor": [True, 23.2]},
    {**BODY, "anchor": [3.27, "23.2"]},
    {**BODY, "anchor": [30.0, 23.2]},  # live anchor outside the live window
    {**BODY, "anchor": [3.27, float("nan")]},
    {**BODY, "anchor": "3.27:23.2"},
])
def test_invalid_bodies_never_start_a_job(client, env, cli, body):
    assert client.post(URL, json=body).status_code == 400
    assert cli[0] == []


def test_preconditions(client, env, cli, monkeypatch, tmp_path):
    assert client.post("/var/analysis/abc/crossview", json=BODY).status_code == 400
    assert client.get(f"{URL}?start=0&end=../x").status_code == 400
    assert client.get(Q).json == {"clip": CLIP, "window": REPLAY, "status": "none", "progress": None, "error": None, "report": None}
    (env / LIVE / "analysis.json").unlink()
    assert "live window first" in client.post(URL, json=BODY).json["error"]
    (env / LIVE / "analysis.json").write_text("{}")
    (env / REPLAY / "analysis.json").unlink()
    assert "replay window first" in client.post(URL, json=BODY).json["error"]
    (env / REPLAY / "analysis.json").write_text("{}")
    (env / "video.mp4").unlink()
    assert client.post(URL, json=BODY).status_code == 409
    (env / "video.mp4").write_bytes(b"x")
    monkeypatch.setenv("VAR_CV_PYTHON", str(tmp_path / "nope"))
    assert client.post(URL, json=BODY).status_code == 503
    assert cli[0] == []


def test_untracked_job_is_judged_by_progress_age(client, env):
    progress = env / REPLAY / "crossview.progress.json"
    progress.write_text("{}")
    assert client.get(Q).json["status"] == "running"
    os.utime(progress, (0, 0))
    got = client.get(Q).json
    assert got["status"] == "failed" and "stopped updating" in got["error"]


# ---------- a live part from another clip of the same ESPN event ----------

def response(data):
    return Mock(json=lambda: data, raise_for_status=lambda: None)


SOURCE = "https://espnmedia-cdn.akamaized.net/espn/clip.mp4"
EVENT = {
    "videos": [{"id": 44656413, "headline": "Kylian Mbappé is sent off for reckless challenge", "duration": 65, "links": {"source": {"href": SOURCE}}},
               {"id": 44656500, "headline": "Mbappe red card: the referee's angle", "duration": 30, "links": {"source": {"href": SOURCE}}},
               {"id": 44656943, "headline": "Alavés also go down to 10 men after Sánchez's red", "duration": 49, "links": {"source": {"href": SOURCE}}},
               {"id": 44656317, "headline": "Eduardo Camavinga's brilliant strike puts Real Madrid ahead", "duration": 51, "links": {"source": {"href": SOURCE}}}],
    "keyEvents": [
        {"id": "1", "type": {"type": "goal"}, "text": "Goal! Alaves 0, Real Madrid 1. Eduardo Camavinga (Real Madrid) ...", "period": {"number": 1},
         "clock": {"value": 1983.0, "displayValue": "34'"}, "participants": [{"athlete": {"displayName": "Eduardo Camavinga"}}]},
        {"id": "2", "type": {"type": "red-card"}, "text": "Kylian Mbappé (Real Madrid) is shown the red card.", "period": {"number": 1},
         "clock": {"value": 2280.0, "displayValue": "38'"}, "participants": [{"athlete": {"displayName": "Kylian Mbappé"}}]},
        {"id": "3", "type": {"type": "substitution"}, "text": "Substitution, Real Madrid. Arda Güler replaces Kylian Mbappé.", "period": {"number": 2},
         "clock": {"value": 3700.0, "displayValue": "62'"}, "participants": [{"athlete": {"displayName": "Arda Güler"}}, {"athlete": {"displayName": "Kylian Mbappé"}}]},
        {"id": "4", "type": {"type": "red-card"}, "text": "Manu Sánchez (Alaves) is shown the red card.", "period": {"number": 2},
         "clock": {"value": 4162.0, "displayValue": "70'"}, "participants": [{"athlete": {"displayName": "Manu Sánchez"}}, "junk"]},
    ],
}


def test_live_part_from_another_clip_is_checked_against_espn(client, env, cli):
    other = env.parent / "44656500" / LIVE
    other.mkdir(parents=True)
    (other / "analysis.json").write_text("{}")
    body = {**BODY, "live": {"clip": "44656500", "start": 1, "end": 7}}
    assert client.post(URL, json=body).status_code == 400  # league and event required across clips
    with patch("routes.var_clips.requests.get", return_value=response(EVENT)):
        assert client.post(URL, json={**body, "league": "PD", "event": "704966", "live": {"clip": "999", "start": 1, "end": 7}}).status_code == 404
        cli[1].append(Step(code=3))
        r = client.post(URL, json={**body, "league": "PD", "event": "704966"})
    assert r.status_code == 202 and r.json["live"] == {"clip": "44656500", "window": LIVE}
    assert flag(launched(cli[0], 1), "--live") == str(other.resolve())
    finish()
    with patch("routes.var_clips.requests.get", side_effect=requests.Timeout):
        assert client.post(URL, json={**body, "league": "PD", "event": "704967"}).status_code == 502


# ---------- other ESPN angles of the incident ----------

def test_angles_lists_clips_naming_the_incident_players(client):
    with patch("routes.var_clips.requests.get", return_value=response(EVENT)):
        got = client.get(f"/var/angles?league=PD&event=704966&clip={CLIP}").json
        sanchez = client.get("/var/angles?league=PD&event=704966&clip=44656943").json
    # The substitution names Mbappé too, but it is not an incident; accents and surname-only headlines still match.
    assert got["players"] == ["Kylian Mbappé"] and got["message"] is None
    assert got["clips"] == [{"id": "44656500", "title": "Mbappe red card: the referee's angle", "duration_seconds": 30,
                             "reason": "Title names Kylian Mbappé (red card 38')"}]
    assert sanchez["players"] == ["Manu Sánchez"] and sanchez["clips"] == []  # surname matched; no other clip names him


def test_angles_explains_unknown_players_and_rejects_bad_input(client):
    data = {**EVENT, "videos": EVENT["videos"] + [{"id": 1, "headline": "Highlights", "links": {"source": {"href": SOURCE}}}]}
    with patch("routes.var_clips.requests.get", return_value=response(data)):
        got = client.get("/var/angles?league=PD&event=704966&clip=1").json
        assert client.get("/var/angles?league=PD&event=704966&clip=2").status_code == 404
    assert got["clips"] == [] and "names no player" in got["message"]
    with patch("routes.var_clips.requests.get") as espn:
        for bad in ("league=XX&event=1&clip=1", "league=PD&event=../x&clip=1", "league=PD&event=1&clip=abc", "league=PD&event=1"):
            assert client.get(f"/var/angles?{bad}").status_code == 400
    espn.assert_not_called()
    with patch("routes.var_clips.requests.get", side_effect=requests.Timeout):
        assert client.get("/var/angles?league=PD&event=704967&clip=1").status_code == 502


def test_official_still_parses_after_refactor(client):
    with patch("routes.var_clips.requests.get", return_value=response(EVENT)):
        events = client.get("/var/official?league=PD&event=704966").json["events"]
    assert [e["type"] for e in events] == ["goal", "red_card", "red_card"]

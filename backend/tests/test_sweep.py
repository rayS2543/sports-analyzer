import json
from unittest.mock import Mock, patch

import pytest

import sweep
from routes import var_analysis

FPS = 10
KICK = 1.09


def analysis(attacker_x=81.3, calibrated=True, shot_end=2.0):
    """An analysed window: passer 1 (A) kicks at 1.09 s, attacker 7 (A) runs beyond second-last opponent 3 (B) at x=80."""
    frames = []
    for i in range(20):
        t = round(i / FPS, 3)
        players = [{"track_id": 1, "team": "A", "role": "player", "x": 50.0, "y": 30.0, "vx": 0.0},
                   {"track_id": 7, "team": "A", "role": "player", "x": attacker_x + 8.0 * (t - KICK), "y": 20.0, "vx": 8.0},
                   {"track_id": 3, "team": "B", "role": "player", "x": 80.0, "y": 25.0, "vx": 0.0},
                   {"track_id": 4, "team": "B", "role": "player", "x": 70.0, "y": 25.0, "vx": 0.0},
                   {"track_id": 2, "team": "A", "role": "player", "x": 55.0, "y": 40.0, "vx": 0.0},
                   {"track_id": 5, "team": "B", "role": "player", "x": 75.0, "y": 40.0, "vx": 0.0},
                   {"track_id": 9, "team": "B", "role": "goalkeeper", "x": 104.0, "y": 34.0, "vx": 0.0}]
        ball = {"x": 50.3 + max(0.0, t - KICK) * 20.0, "y": 30.0, "z": 0.0, "airborne": False, "height_model": "rolling", "position_uncertainty_m": 0.2}
        frames.append({"t": t, "shot": 0, "calibration": {"ok": calibrated, "reprojection_error_m": 0.4, "source": "detected"}, "ball": ball, "players": players})
    return {"frames": frames, "events": [{"type": "pass", "t": 1.0, "shot": 0, "passer_track_id": 1, "team": "A", "receiver_track_id": 7, "receiver_team": "A"}],
            "pitch": {"length_m": 105.0}, "video": {"sampled_fps": FPS}, "shots": [{"id": 0, "start": 0.0, "end": shot_end}]}


CLIP = {"id": "50220747", "title": "Álvaro García scores in the 11'", "match": "Rayo Vallecano at Getafe", "date": "2026-10-19", "event": "1",
        "duration_seconds": 60, "page_url": None, "source_url": "https://espnmedia-cdn.akamaized.net/x.mp4"}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("VAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(var_analysis, "_sweep", None)
    return tmp_path / "data"


def test_a_window_summary_says_what_the_pipeline_had_and_reads_each_pass():
    w = sweep.summarise_window("1", "0.0-10.0", analysis())
    assert w["calibrated_frames"] == [20, 20] and w["players_per_frame"] == 7 and w["flags"] == []
    assert [(p["verdict"], p["attacker_track_id"]) for p in w["passes"]] == [("offside", 7)]


def test_a_window_with_few_calibrated_frames_is_flagged_unusable():
    w = sweep.summarise_window("1", "0.0-10.0", analysis(calibrated=False))
    assert any("could not be fitted" in f for f in w["flags"]) and sweep.clip_status([w]) == "uncalibrated"


def test_an_unusually_large_decisive_margin_is_flagged_for_a_human_look():
    w = sweep.summarise_window("1", "0.0-10.0", analysis(attacker_x=88.0))  # 8 m beyond the line
    assert w["passes"][0]["verdict"] == "offside" and any("unusually large" in f for f in w["passes"][0]["flags"])
    assert sweep.summarise_window("1", "0.0-10.0", analysis())["passes"][0]["flags"] == []  # 1.3 m: ordinary
    onside = sweep.summarise_window("1", "0.0-10.0", analysis(attacker_x=55.0))["passes"][0]  # far behind the line: clearly onside, not worth a look
    assert onside["verdict"] == "onside" and onside["flags"] == []


@pytest.mark.parametrize("windows,expected", [
    ([], "failed"),
    ([{"error": "x", "passes": [], "flags": []}], "failed"),
    ([{"passes": [], "flags": []}], "no_passes"),
    ([{"passes": [{"verdict": "inconclusive"}], "flags": []}], "inconclusive"),
    ([{"passes": [{"verdict": "onside"}], "flags": []}], "read"),
])
def test_clip_status(windows, expected):
    assert sweep.clip_status(windows) == expected


def test_a_second_window_follows_only_a_build_up_that_runs_on_past_the_first():
    assert sweep.windows_after(60, {"shots": [{"end": 10.0}], "window": {"end": 10.0}}) == (10.0, 20.0)
    assert sweep.windows_after(14, {"shots": [{"end": 10.0}], "window": {"end": 10.0}}) == (10.0, 14)
    assert sweep.windows_after(60, {"shots": [{"end": 6.0}], "window": {"end": 10.0}}) is None  # cut to a close-up at 6 s
    assert sweep.windows_after(9, {"shots": [{"end": 9.0}], "window": {"end": 9.0}}) is None


def test_sweeping_a_clip_saves_its_result_and_follows_a_long_build_up(env):
    seen = []

    def fake_analyse(clip, start, end, python):
        seen.append((start, end))
        return f"{start}-{end}", analysis(shot_end=end), None
    with patch("sweep.analyse", side_effect=fake_analyse):
        record = sweep.sweep_clip(dict(CLIP, league="PD"), "python")
    assert seen == [(0.0, 10.0), (10.0, 20.0)] and record["status"] == "read"
    assert json.loads(sweep.result_path("50220747").read_text())["clip"]["match"] == "Rayo Vallecano at Getafe"


def test_an_analysis_error_is_recorded_not_raised(env):
    with patch("sweep.analyse", return_value=("0.0-10.0", None, "the analysis timed out")):
        record = sweep.sweep_clip(dict(CLIP, league="PD"), "python")
    assert record["status"] == "failed" and record["windows"][0]["error"] == "the analysis timed out"


def test_a_run_skips_clips_already_swept_and_one_failure_does_not_stop_the_rest(env):
    clips = [dict(CLIP, id="1"), dict(CLIP, id="2"), dict(CLIP, id="3")]
    sweep.write_json(sweep.result_path("1"), {"clip": {"id": "1"}})
    calls = []

    def fake_sweep_clip(clip, python):
        calls.append(clip["id"])
        if clip["id"] == "2":
            raise RuntimeError("boom")
    with patch("sweep.find_clips", return_value=(clips, [], 0)), patch("sweep.sweep_clip", side_effect=fake_sweep_clip):
        state = sweep.run("PD", 14, 20, "python")
    assert calls == ["2", "3"] and state["total"] == 2 and state["done"] == 2 and state["running"] is False
    assert json.loads(sweep.result_path("2").read_text())["status"] == "failed"


def test_the_limit_caps_how_many_new_clips_one_run_analyses(env):
    clips = [dict(CLIP, id=str(i)) for i in range(5)]
    with patch("sweep.find_clips", return_value=(clips, [], 0)), patch("sweep.sweep_clip") as one:
        state = sweep.run("PD", 14, 2, "python")
    assert one.call_count == 2 and state["total"] == 2 and state["found"] == 5


# --- the Checks endpoints -----------------------------------------------------------------------------------

def test_checks_lists_results_newest_first_and_marks_the_flagged_ones(client, env):
    sweep.write_json(sweep.result_path("1"), {"clip": {"id": "1", "date": "2026-10-01"}, "status": "read", "windows": [{"flags": [], "passes": [{"flags": []}]}]})
    sweep.write_json(sweep.result_path("2"), {"clip": {"id": "2", "date": "2026-10-05"}, "status": "read", "windows": [{"flags": [], "passes": [{"flags": ["large"]}]}]})
    body = client.get("/var/checks").json
    assert [c["clip"]["id"] for c in body["checks"]] == ["2", "1"] and [c["flagged"] for c in body["checks"]] == [True, False]
    assert body["sweep"]["running"] is False


def test_starting_a_sweep_runs_it_in_the_background_and_refuses_while_busy(client, env, tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("VAR_CV_PYTHON", str(python))
    with patch("routes.var_checks.subprocess.Popen") as popen:
        popen.return_value.poll.return_value = None
        first = client.post("/var/sweep", json={"league": "PD", "days": 7, "limit": 5})
        second = client.post("/var/sweep", json={})
    assert first.status_code == 202 and popen.call_count == 1
    args = popen.call_args.args[0]
    assert args[1:3] == ["-m", "sweep"] and args[args.index("--days") + 1] == "7" and args[args.index("--limit") + 1] == "5"
    assert second.status_code == 409 and "swept" in second.json["error"]
    assert client.get("/var/sweep").json["running"] is True


@pytest.mark.parametrize("body", [{"league": "XX"}, {"days": 0}, {"days": 99}, {"limit": 0}, {"limit": 100}, {"days": "7"}, {"days": True}])
def test_a_bad_sweep_request_starts_nothing(client, body):
    with patch("routes.var_checks.subprocess.Popen") as popen:
        assert client.post("/var/sweep", json=body).status_code == 400
    popen.assert_not_called()


def test_a_pass_whose_attack_direction_cannot_be_established_is_inconclusive_not_guessed():
    result = analysis()
    for f in result["frames"]:
        f["players"] = [p for p in f["players"] if p["role"] != "goalkeeper"]
    window = sweep.summarise_window("1", "0.0-10.0", result)
    assert [p["verdict"] for p in window["passes"]] == ["inconclusive"] and sweep.clip_status([window]) == "inconclusive"

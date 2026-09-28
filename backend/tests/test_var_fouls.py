import json
from unittest.mock import patch

import pytest

import var_fouls
from routes import var_fouls as routes


def I(value, conf=0.9, observable=True, **extra):
    return dict({"label": "x", "value": value if observable else None, "confidence": conf if observable else 0.0,
                 "observable": observable, "detail": "d"}, **extra)


HIDDEN = I(None, observable=False)


def sfp_ind(**over):
    """A clean, fully observed challenge for the ball with contact and no danger signs."""
    base = {"contact": I(True), "contact_above_ankle": I(False), "studs_showing": I(False), "both_feet_off_ground": I(False),
            "straight_leg_high_foot": I(False), "challenger_speed": I(3.0), "challenging_for_ball": I(True),
            "off_ball_strike": I(False)}
    base.update(over)
    return base


SFP_CASES = [
    ("clean contact", {}, "not_red"),
    ("studs above ankle", {"studs_showing": I(True), "contact_above_ankle": I(True)}, "red"),
    ("studs at the ankle at speed", {"studs_showing": I(True), "challenger_speed": I(6.5)}, "red"),
    ("studs at the ankle, slow", {"studs_showing": I(True), "challenger_speed": I(2.0)}, "inconclusive"),
    ("two-footed lunge", {"both_feet_off_ground": I(True)}, "red"),
    ("straight leg, high, above ankle", {"straight_leg_high_foot": I(True), "contact_above_ankle": I(True)}, "red"),
    ("straight leg high but at the ankle", {"straight_leg_high_foot": I(True)}, "inconclusive"),
    ("studs indicator low confidence", {"studs_showing": I(True, conf=0.4), "contact_above_ankle": I(True)}, "inconclusive"),
    ("studs occluded", {"studs_showing": HIDDEN}, "inconclusive"),
    ("contact occluded", {"contact": HIDDEN}, "inconclusive"),
    ("contact low confidence", {"contact": I(True, conf=0.3)}, "inconclusive"),
    ("no contact", {"contact": I(False)}, "not_red"),
    ("no contact but lunge", {"contact": I(False), "both_feet_off_ground": I(True)}, "inconclusive"),
    ("ball not playable", {"challenging_for_ball": I(False), "studs_showing": I(True)}, "not_red"),
]


@pytest.mark.parametrize("name,over,verdict", SFP_CASES, ids=[c[0] for c in SFP_CASES])
def test_serious_foul_play(name, over, verdict):
    g = var_fouls.serious_foul_play(sfp_ind(**over))
    assert g["verdict"] == verdict, g["reasons"]
    assert g["ground"] == "serious_foul_play" and g["reasons"]
    assert {i["key"] for i in g["indicators"]} >= {"contact", "studs_showing", "both_feet_off_ground"}


VC_CASES = [
    ("no arm to head", {}, "not_red"),
    ("fast elbow off the ball", {"off_ball_strike": I(True, arm_speed_mps=6.0), "challenging_for_ball": I(False)}, "red"),
    ("slow arm off the ball: force may be negligible", {"off_ball_strike": I(True, arm_speed_mps=1.0), "challenging_for_ball": I(False)}, "inconclusive"),
    ("arm speed unknown", {"off_ball_strike": I(True, arm_speed_mps=None), "challenging_for_ball": I(False)}, "inconclusive"),
    ("arm to head while challenging", {"off_ball_strike": I(True, arm_speed_mps=6.0)}, "inconclusive"),
    ("ball unknown", {"off_ball_strike": I(True, arm_speed_mps=6.0), "challenging_for_ball": HIDDEN}, "inconclusive"),
    ("arms occluded", {"off_ball_strike": HIDDEN}, "inconclusive"),
]


@pytest.mark.parametrize("name,over,verdict", VC_CASES, ids=[c[0] for c in VC_CASES])
def test_violent_conduct(name, over, verdict):
    assert var_fouls.violent_conduct(sfp_ind(**over))["verdict"] == verdict


def factors(**over):
    """A textbook DOGSO outside the box: 20 m out, running at goal, ball at feet, nobody between."""
    base = {"distance_to_goal": I(20.0), "direction_of_play": I("towards_goal"), "control": I(1.0),
            "defenders_between": I(0, outfield=0, goalkeepers=0, corridor_in_view=1.0), "attackers": I(0),
            "in_penalty_area": I(False), "attempt_to_play_ball": I(True)}
    base.update(over)
    return base


DOGSO_CASES = [
    ("textbook, outside the box", {}, {}, "red", None),
    ("in the box with an attempt to play the ball -> caution", {}, {"in_penalty_area": I(True), "distance_to_goal": I(12.0)}, "not_red", "yellow"),
    ("in the box, holding (no attempt)", {}, {"in_penalty_area": I(True), "distance_to_goal": I(12.0), "attempt_to_play_ball": I(False)}, "red", None),
    ("in the box, attempt unknown", {}, {"in_penalty_area": I(True), "distance_to_goal": I(12.0), "attempt_to_play_ball": HIDDEN}, "inconclusive", None),
    ("on the box line", {}, {"in_penalty_area": I(True, conf=0.45), "distance_to_goal": I(16.0)}, "inconclusive", None),
    ("keeper only, close to goal", {}, {"distance_to_goal": I(14.0), "defenders_between": I(1, outfield=0, goalkeepers=1, corridor_in_view=1.0)}, "red", None),
    ("keeper can intervene from 25 m", {}, {"distance_to_goal": I(25.0), "defenders_between": I(1, outfield=0, goalkeepers=1, corridor_in_view=1.0)}, "inconclusive", None),
    ("covering defender", {}, {"defenders_between": I(1, outfield=1, goalkeepers=0, corridor_in_view=1.0)}, "inconclusive", None),
    ("two defenders", {}, {"defenders_between": I(2, outfield=1, goalkeepers=1, corridor_in_view=1.0)}, "not_red", None),
    ("too far from goal", {}, {"distance_to_goal": I(55.0)}, "not_red", None),
    ("35 m: judgement zone", {}, {"distance_to_goal": I(35.0)}, "inconclusive", None),
    ("moving away", {}, {"direction_of_play": I("away_from_goal")}, "not_red", None),
    ("ball far from attacker", {}, {"control": I(8.0)}, "not_red", None),
    ("corridor partly off-camera", {}, {"defenders_between": I(0, outfield=0, goalkeepers=0, corridor_in_view=0.6)}, "inconclusive", None),
    ("uncalibrated", {}, {k: HIDDEN for k in ("distance_to_goal", "direction_of_play", "control", "defenders_between")}, "inconclusive", None),
    ("goal inferred by heuristic only", {}, {"distance_to_goal": I(20.0, conf=0.4)}, "inconclusive", None),
    ("no contact", {"contact": I(False)}, {}, "not_red", None),
    ("contact occluded", {"contact": HIDDEN}, {}, "inconclusive", None),
]


@pytest.mark.parametrize("name,ind_over,fac_over,verdict,downgrade", DOGSO_CASES, ids=[c[0] for c in DOGSO_CASES])
def test_dogso(name, ind_over, fac_over, verdict, downgrade):
    g = var_fouls.dogso(sfp_ind(**ind_over), factors(**fac_over))
    assert g["verdict"] == verdict, g["reasons"]
    assert g.get("downgraded_to") == downgrade


@pytest.mark.parametrize("verdicts,downgraded,expected", [
    (["not_red", "not_red", "not_red"], False, "none"),
    (["red", "inconclusive", "not_red"], False, "red"),
    (["not_red", "inconclusive", "not_red"], False, "inconclusive"),
    (["not_red", "not_red", "not_red"], True, "yellow"),
    (["not_red", "inconclusive", "not_red"], True, "inconclusive"),
])
def test_sanction(verdicts, downgraded, expected):
    grounds = [{"verdict": v} for v in verdicts]
    if downgraded:
        grounds[2]["downgraded_to"] = "yellow"
    assert var_fouls.sanction(grounds) == expected


def test_incident_without_pose_is_inconclusive_everywhere():
    out = var_fouls.assess_incident({"id": 0, "t": 16.4, "indicators": {}, "dogso": {}})
    assert out["sanction"] == "inconclusive"
    assert [g["verdict"] for g in out["grounds"]] == ["inconclusive"] * 3
    assert any("policy" in n for n in out["notes"])


def test_review_explains_empty_window():
    out = var_fouls.review({"incidents": [], "candidates_found": 0})
    assert out["incidents"] == [] and "No opposing players" in out["message"]


# ---------- routes ----------

class FakeProcess:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


@pytest.fixture
def data(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setenv("VAR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VAR_CV_PYTHON", str(python))
    monkeypatch.setattr(routes, "_job", None)
    window = tmp_path / "data" / "44656413" / "12.0-18.0"
    window.mkdir(parents=True)
    (window.parent / "video.mp4").write_bytes(b"x")
    return window


BODY = {"clip": "44656413", "start": 12, "end": 18}
Q = "/var/fouls/44656413?start=12&end=18"


def test_start_requires_analysis_and_valid_window(client, data):
    assert client.post("/var/fouls", json={**BODY, "end": 40}).status_code == 400
    assert client.post("/var/fouls", json={**BODY, "clip": "../x"}).status_code == 400
    r = client.post("/var/fouls", json=BODY)
    assert r.status_code == 409 and "Analyse this window first" in r.json["error"]
    assert client.get(Q).json["status"] == "none"


def test_start_runs_cv_then_serves_assessment(client, data):
    (data / "analysis.json").write_text("{}")
    with patch("routes.var_fouls.subprocess.Popen", return_value=FakeProcess()) as popen:
        r = client.post("/var/fouls", json=BODY)
    assert r.status_code == 202 and r.json == {"clip": "44656413", "window": "12.0-18.0", "status": "queued"}
    args = popen.call_args.args[0]
    flag = lambda n: args[args.index(n) + 1]
    assert args[1:3] == ["-m", "var_cv.fouls"]
    assert flag("--analysis") == str((data / "analysis.json").resolve())
    assert flag("--video") == str((data.parent / "video.mp4").resolve())
    assert flag("--out") == str((data / "fouls.json").resolve())
    assert popen.call_args.kwargs["cwd"].name == "cv"
    (data / "fouls.progress.json").write_text(json.dumps({"stage": "fouls", "progress": 0.4, "message": "m"}))
    got = client.get(Q).json
    assert got["status"] == "running" and got["progress"]["progress"] == 0.4 and got["incidents"] is None
    # a second window is refused while one runs
    other = data.parent / "1.0-7.0"
    other.mkdir()
    (other / "analysis.json").write_text("{}")
    assert client.post("/var/fouls", json={**BODY, "start": 1, "end": 7}).status_code == 409

    (data / "fouls.json").write_text(json.dumps({"candidates_found": 1, "incidents": [
        {"id": 0, "t": 16.4, "players": {}, "indicators": sfp_ind(both_feet_off_ground=I(True)), "dogso": factors(distance_to_goal=I(60.0))}]}))
    got = client.get(Q).json
    assert got["status"] == "done"
    inc = got["incidents"][0]
    assert inc["sanction"] == "red" and inc["t"] == 16.4
    assert {g["ground"]: g["verdict"] for g in inc["grounds"]} == {"serious_foul_play": "red", "violent_conduct": "not_red", "dogso": "not_red"}
    assert client.post("/var/fouls", json=BODY).json["status"] == "done"


def test_crashed_job_is_reported_failed(client, data):
    (data / "analysis.json").write_text("{}")
    with patch("routes.var_fouls.subprocess.Popen", return_value=FakeProcess(code=1)):
        client.post("/var/fouls", json=BODY)
    got = client.get(Q).json
    assert got["status"] == "failed" and "exited with code 1" in got["error"]

import json
from unittest.mock import Mock, patch

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


# ---------- several angles of one incident ----------

def angle(team="A", **ind):
    return {"id": 0, "t": 3.3, "players": {"challenger": {"team": team}}, "indicators": ind, "dogso": {}}


def test_combine_takes_each_indicator_from_the_angle_that_saw_it_best():
    live = angle(contact=I(True, conf=0.57), challenger_speed=I(8.2, conf=0.7), studs_showing=HIDDEN)
    replay = angle(contact=I(True, conf=0.8), challenger_speed=HIDDEN, studs_showing=I(True, conf=0.75),
                   contact_above_ankle=I(True, conf=0.7), challenging_for_ball=I(True))
    out = var_fouls.combine([("live", live), ("replay", replay)])
    sfp = next(g for g in out["grounds"] if g["ground"] == "serious_foul_play")
    used = {i["key"]: i for i in sfp["indicators"]}
    assert used["contact"]["angle"] == "replay" and used["challenger_speed"]["angle"] == "live"
    assert used["studs_showing"]["detail"].startswith("[replay]")
    assert sfp["verdict"] == "red" and out["sanction"] == "red"
    assert [a["angle"] for a in out["angles"]] == ["live", "replay"]


def test_combine_does_not_rely_on_contradicting_angles():
    a = angle(contact=I(True, conf=0.9))
    b = angle(contact=I(False, conf=0.7))
    got = var_fouls.combine([("a", a), ("b", b)])
    contact = next(i for i in got["grounds"][0]["indicators"] if i["key"] == "contact")
    assert not contact["observable"] and "contradict" in contact["detail"]
    assert got["grounds"][0]["verdict"] == "inconclusive"
    weak = var_fouls.combine([("a", angle(studs_showing=I(False, conf=0.34))), ("b", angle(studs_showing=I(True, conf=0.28)))])
    studs = next(i for g in weak["grounds"] for i in g["indicators"] if i["key"] == "studs_showing")
    assert "Other angles disagree (b: yes (28%))" in studs["detail"]


def test_combine_refuses_challengers_from_different_teams():
    with pytest.raises(ValueError):
        var_fouls.combine([("a", angle("A")), ("b", angle("B"))])


def test_combine_route(client, data):
    other = data.parent / "23.0-28.0"
    other.mkdir()
    (data / "fouls.json").write_text(json.dumps({"incidents": [angle(challenger_speed=I(8.0))]}))
    (other / "fouls.json").write_text(json.dumps({"incidents": [angle(contact=I(True))]}))
    url = "/var/fouls/44656413/combine"
    r = client.post(url, json={"parts": [{"start": 12, "end": 18, "id": 0}, {"start": 23, "end": 28, "id": 0}]})
    assert r.status_code == 200 and len(r.json["angles"]) == 2
    assert client.post(url, json={"parts": [{"start": 12, "end": 18, "id": 0}]}).status_code == 400
    assert client.post(url, json={"parts": [{"start": 12, "end": 18, "id": 0}, {"start": 12, "end": 18, "id": 0}]}).status_code == 400
    assert client.post(url, json={"parts": [{"start": 12, "end": 18, "id": 0}, {"start": 23, "end": 28, "id": 9}]}).status_code == 404


# ---------- cross-view: which angle to calibrate, and which contacts are the same incident ----------

LIVE, REPLAY = "1.0-7.0", "23.0-28.0"


def contact(id_, t, team, shot=0):
    return {**angle(team), "id": id_, "t": t, "shot": shot}


def write_window(clip_dir, key, analysis, incidents):
    (clip_dir / key).mkdir(parents=True, exist_ok=True)
    (clip_dir / key / "analysis.json").write_text(json.dumps(analysis))
    (clip_dir / key / "fouls.json").write_text(json.dumps({"incidents": incidents}))


def frames(ts, **calibration):
    return [{"t": t, "shot": 0, "calibration": dict(calibration)} for t in ts]


def to_live(t):  # what the cross-view sync found: replay x0.4, contact 23.223 <-> live 3.27
    return round(3.27 + 0.4 * (t - 23.223), 4)


@pytest.fixture
def angles(data):
    clip = data.parent
    write_window(clip, LIVE, {"shots": [{"id": 0}], "frames": frames([3.1, 3.2, 3.3], ok=True, source="detected")},
                 [contact(2, 3.136, "B"), contact(3, 3.27, "A"), contact(4, 4.438, "B")])
    write_window(clip, REPLAY, {"shots": [{"id": 0}], "frames": frames([23.2, 23.3, 23.4], ok=False)},
                 [contact(0, 23.223, "A"), contact(1, 23.357, "B")])
    return clip


def synced(clip, window=LIVE):
    """The replay window as crossview.py leaves it: cross-view frames with live_t and the shot's replay_of."""
    analysis = {"shots": [{"id": 0, "playback_speed": 0.4, "replay_of": {"clip": "44656413", "window": window, "t_live_anchor": 3.27,
                                                                          "t_replay_anchor": 23.223, "speed": 0.4}}],
                "frames": [dict(f, live_t=to_live(f["t"])) for f in frames([23.2, 23.3, 23.4], ok=True, source="cross_view")]}
    (clip / REPLAY / "analysis.json").write_text(json.dumps(analysis))


COMBINE = "/var/fouls/44656413/combine"
PAIR = {"parts": [{"start": 1, "end": 7, "id": 3}, {"start": 23, "end": 28, "id": 0}]}


def test_combine_offers_crossview_for_an_uncalibrated_replay_with_a_calibrated_live_angle(client, angles):
    for parts in (PAIR["parts"], PAIR["parts"][::-1]):
        got = client.post(COMBINE, json={"parts": parts}).json
        assert got["crossview_available"] is True and got["suggested_pairs"] == []
        assert got["crossview_request"] == {"clip": "44656413", "start": 23.0, "end": 28.0,
                                            "live": {"clip": "44656413", "start": 1.0, "end": 7.0}, "anchor": [3.27, 23.223]}
    # A refused pairing (opposite kits) can still calibrate the replay, but not anchored on that pair.
    refused = client.post(COMBINE, json={"parts": [{"start": 1, "end": 7, "id": 2}, {"start": 23, "end": 28, "id": 0}]})
    assert refused.status_code == 409 and refused.json["crossview_available"] is True
    assert "anchor" not in refused.json["crossview_request"] and refused.json["crossview_request"]["start"] == 23.0
    write_window(angles, "12.0-18.0", {"shots": [{"id": 0}], "frames": frames([12.1], ok=True, source="propagated")}, [contact(0, 12.3, "A")])
    got = client.post(COMBINE, json={"parts": [{"start": 1, "end": 7, "id": 3}, {"start": 12, "end": 18, "id": 0}]}).json
    assert got["crossview_available"] is False and got["crossview_request"] is None


@pytest.mark.parametrize("window", [LIVE, {"start": 1.0, "end": 7.0}])
def test_suggested_pairs_follow_the_crossview_time_map(client, angles, window):
    synced(angles, window)
    expected = [
        {"live": {"clip": "44656413", "start": 1.0, "end": 7.0, "id": 3, "t": 3.27},
         "replay": {"clip": "44656413", "start": 23.0, "end": 28.0, "id": 0, "t": 23.223}, "dt_s": 0.0},
        # 23.357 syncs to 3.324: the A challenger at 3.27 is nearer but the wrong kit, so the B one at 3.136.
        {"live": {"clip": "44656413", "start": 1.0, "end": 7.0, "id": 2, "t": 3.136},
         "replay": {"clip": "44656413", "start": 23.0, "end": 28.0, "id": 1, "t": 23.357}, "dt_s": round(3.136 - to_live(23.357), 3)},
    ]
    got = client.post(COMBINE, json=PAIR).json
    assert got["suggested_pairs"] == expected
    assert got["crossview_available"] is False  # the replay is calibrated now
    assert client.get("/var/fouls/44656413?start=23&end=28").json["suggested_pairs"] == expected
    assert client.get("/var/fouls/44656413?start=1&end=7").json["suggested_pairs"] == []
    # A wrong pairing is refused, but the suggestions still point at the right one.
    wrong = client.post(COMBINE, json={"parts": [{"start": 1, "end": 7, "id": 2}, {"start": 23, "end": 28, "id": 0}]})
    assert wrong.status_code == 409 and wrong.json["suggested_pairs"] == expected


def test_suggested_pairs_ignore_contacts_outside_the_tolerance_and_bad_maps(client, angles):
    synced(angles)
    analysis = json.loads((angles / REPLAY / "analysis.json").read_text())
    analysis["frames"] = [dict(f, live_t=f["live_t"] + 2.0) for f in analysis["frames"]]  # sync 2 s off: nothing within tolerance
    (angles / REPLAY / "analysis.json").write_text(json.dumps(analysis))
    assert client.post(COMBINE, json=PAIR).json["suggested_pairs"] == []
    synced(angles)
    analysis = json.loads((angles / REPLAY / "analysis.json").read_text())
    for window in ("../1.0-7.0", "1-7", {"start": 1, "end": 70}, None):
        analysis["shots"][0]["replay_of"]["window"] = window
        (angles / REPLAY / "analysis.json").write_text(json.dumps(analysis))
        assert client.post(COMBINE, json=PAIR).json["suggested_pairs"] == []


def test_combine_survives_a_contact_without_a_challenger(client, angles):
    fouls = json.loads((angles / REPLAY / "fouls.json").read_text())
    fouls["incidents"].append({"id": 7, "t": 24.4, "shot": 0, "players": {"challenger": None, "victim": None}, "indicators": {}, "dogso": {}})
    (angles / REPLAY / "fouls.json").write_text(json.dumps(fouls))
    assert client.post(COMBINE, json={"parts": [{"start": 1, "end": 7, "id": 3}, {"start": 23, "end": 28, "id": 7}]}).status_code == 200


def test_combine_parts_from_another_clip_of_the_event(client, angles):
    other = angles.parent / "44656500"
    write_window(other, LIVE, {"shots": [{"id": 0}], "frames": frames([3.2], ok=True, source="detected")}, [contact(5, 3.3, "B")])
    parts = [{"start": 23, "end": 28, "id": 0}, {"clip": "44656500", "start": 1, "end": 7, "id": 5}]
    assert client.post(COMBINE, json={"parts": parts}).status_code == 400  # league + event needed across clips
    assert client.post(COMBINE, json={"parts": [parts[0], {**parts[1], "clip": "../x"}]}).status_code == 400
    summary = {"videos": [{"id": int(c), "headline": "x", "links": {"source": {"href": "https://espnmedia-cdn.akamaized.net/a.mp4"}}}
                          for c in ("44656413", "44656500")]}
    with patch("routes.var_clips.requests.get", return_value=Mock(json=lambda: summary, raise_for_status=lambda: None)):
        got = client.post(COMBINE, json={"parts": parts, "league": "PD", "event": "704966"})
        missing = client.post(COMBINE, json={"parts": [parts[0], {**parts[1], "clip": "999"}], "league": "PD", "event": "704966"})
    # Team letters are per-clip kit clusters: A here and B there may be the same club, so no refusal across clips.
    assert got.status_code == 200 and any("only compared within a clip" in n for n in got.json["notes"])
    assert [a["angle"] for a in got.json["angles"]] == [REPLAY, "clip 44656500 1.0-7.0"]
    assert got.json["crossview_request"]["live"] == {"clip": "44656500", "start": 1.0, "end": 7.0}
    assert missing.status_code == 404

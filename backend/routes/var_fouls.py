"""Foul / red-card review of an analysed window: run the CV foul pass and serve Law 12 assessments."""
import json
import os
import subprocess
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from routes import var_analysis
from routes.var_analysis import ID, KEY, MAX_WINDOW_SECONDS, ROOT, _out, _read, _same_event, _window
from var_fouls import combine, review

var_fouls_bp = Blueprint("var_fouls", __name__)
STALE_SECONDS = 600
_job = None  # (clip_id, window_key, Popen); var_analysis._lock guards it (one heavy CV job machine-wide)
WINDOW_ERROR = f"clip and start/end seconds are required, 0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart"
PAIR_TOLERANCE_S = 0.3  # live seconds between a synced replay contact and the live contact it is paired with


def _files(clip_id, key):
    out = _out(clip_id, key)
    return out / "fouls.json", out / "fouls.progress.json", out / "fouls.error.json"


def _status(clip_id, key):
    result, progress, error = _files(clip_id, key)
    if result.exists():
        return "done"
    if error.exists():
        return "failed"
    if _job and _job[:2] == (clip_id, key):
        code = _job[2].poll()
        if code is None:
            return "running"
        crash = f"Foul review exited with code {code} without a result; see var_data/{clip_id}/{key}/fouls.log"
    else:
        if not progress.exists():
            return "none"
        if time.time() - progress.stat().st_mtime < STALE_SECONDS:
            return "running"
        crash = "Foul review stopped updating without a result"
    error.write_text(json.dumps({"error": crash}))
    return "failed"


def _dict(path):
    data = _read(path)
    return data if isinstance(data, dict) else {}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _team(inc):
    return ((inc.get("players") or {}).get("challenger") or {}).get("team")


def _key_of(window):
    """Window key from a replay_of.window given as "1.0-7.0" or {start, end}; None unless canonical."""
    if isinstance(window, str):
        start, _, end = window.partition("-")
        return window if KEY.fullmatch(window) and _window(start, end) == window else None
    return _window(window.get("start"), window.get("end")) if isinstance(window, dict) else None


def _to_live(frames):
    """replay t -> synced live t, interpolated between the two nearest frames with a cross-view live_t; None if unsynced."""
    synced = [(f["t"], f["live_t"]) for f in frames if _num(f.get("t")) and _num(f.get("live_t"))]
    if len({t for t, _ in synced}) < 2:
        return None

    def to_live(t):
        (t0, l0), (t1, l1) = sorted(synced, key=lambda p: abs(p[0] - t))[:2]
        return l0 + (l1 - l0) * (t - t0) / (t1 - t0) if t1 != t0 else l0
    return to_live


def suggested_pairs(clip_id, key):
    """(replay incident, live incident) pairs of one replay window, matched through its cross-view time map:
    each replay contact's synced live time against the nearest live contact within PAIR_TOLERANCE_S, one-to-one."""
    analysis, replay = _dict(_out(clip_id, key) / "analysis.json"), _dict(_files(clip_id, key)[0])
    found = []
    for shot in analysis.get("shots") or []:
        of = shot.get("replay_of") if isinstance(shot, dict) else None
        if not isinstance(of, dict):
            continue
        live_clip, live_key = str(of.get("clip") or clip_id), _key_of(of.get("window"))
        to_live = _to_live([f for f in analysis.get("frames") or [] if f.get("shot") == shot.get("id")])
        if not ID.fullmatch(live_clip) or not live_key or not to_live:
            continue
        live = _dict(_files(live_clip, live_key)[0])
        for r in replay.get("incidents") or []:
            if r.get("shot") != shot.get("id") or not _num(r.get("t")) or r.get("id") is None:
                continue
            t_live = to_live(r["t"])
            for li in live.get("incidents") or []:
                if not _num(li.get("t")) or li.get("id") is None or abs(li["t"] - t_live) > PAIR_TOLERANCE_S:
                    continue
                if live_clip == clip_id and None not in (_team(r), _team(li)) and _team(r) != _team(li):
                    continue  # team letters only compare within a clip
                found.append((abs(li["t"] - t_live), li["t"] - t_live, r, li, live_clip, live_key))
    pairs, used = [], set()
    for _, dt, r, li, live_clip, live_key in sorted(found, key=lambda f: f[0]):
        ends = (("replay", r["id"]), ("live", live_clip, live_key, li["id"]))
        if used & set(ends):
            continue
        used |= set(ends)
        part = lambda c, k, inc: {"clip": c, "start": float(k.split("-")[0]), "end": float(k.split("-")[1]), "id": inc["id"], "t": inc["t"]}
        pairs.append({"live": part(live_clip, live_key, li), "replay": part(clip_id, key, r), "dt_s": round(dt, 3) + 0.0})  # + 0.0: no "-0.0"
    return sorted(pairs, key=lambda p: p["replay"]["t"])


def _shot_state(clip_id, key, inc):
    """"live" when the incident's shot is calibrated from its own pitch lines, "uncalibrated" when no frame of it
    is calibrated, else None (calibrated by cross-view, or unknown)."""
    analysis = _dict(_out(clip_id, key) / "analysis.json")
    frames = [f for f in analysis.get("frames") or [] if isinstance(f, dict) and f.get("shot") == inc.get("shot")]
    if not frames:
        return None
    sources = {(f.get("calibration") or {}).get("source") for f in frames if (f.get("calibration") or {}).get("ok")}
    return "uncalibrated" if not sources else "live" if sources - {"cross_view"} else None


def _crossview_request(found, anchor=True):
    """The cross-view job body when an uncalibrated part and a calibrated live part are combined, else None.
    The anchor is the two contacts the user paired as the same incident (left out when the pairing was refused:
    the CLI then pairs contacts itself)."""
    state = {(c, k): _shot_state(c, k, inc) for c, k, inc in found}
    replay = next(((c, k, inc) for c, k, inc in found if state[c, k] == "uncalibrated"), None)
    live = next(((c, k, inc) for c, k, inc in found if state[c, k] == "live"), None)
    if not replay or not live:
        return None
    window = lambda c, k: {"clip": c, "start": float(k.split("-")[0]), "end": float(k.split("-")[1])}
    body = dict(window(replay[0], replay[1]), live=window(live[0], live[1]))
    if anchor and _num(live[2].get("t")) and _num(replay[2].get("t")):
        body["anchor"] = [live[2]["t"], replay[2]["t"]]
    return body


@var_fouls_bp.post("/var/fouls")
def start():
    global _job
    body = request.get_json(silent=True) or {}
    clip_id, key = body.get("clip"), _window(body.get("start"), body.get("end"))
    if not isinstance(clip_id, str) or not ID.fullmatch(clip_id) or not key:
        return jsonify(error=WINDOW_ERROR), 400
    with var_analysis._lock:
        status = _status(clip_id, key)
        if status in ("done", "running"):
            return jsonify(clip=clip_id, window=key, status=status), 200 if status == "done" else 202
        busy = var_analysis._running()
        if busy:
            return jsonify(error=busy), 409
        out = _out(clip_id, key)
        if not (out / "analysis.json").exists():
            return jsonify(error="Analyse this window first; the foul review builds on its tracked players."), 409
        video = _out(clip_id) / "video.mp4"
        if not video.exists():
            return jsonify(error="Source video for this clip is missing; re-run the analysis."), 409
        python = Path(os.environ.get("VAR_CV_PYTHON") or ROOT / "cv/.venv/bin/python")
        if not python.exists():
            return jsonify(error=f"CV environment not found at {python}. Run cv/setup.sh or set VAR_CV_PYTHON."), 503
        result, progress, error = _files(clip_id, key)
        for path in (progress, error):
            path.unlink(missing_ok=True)
        with open(out / "fouls.log", "w") as log:
            process = subprocess.Popen(
                [str(python), "-m", "var_cv.fouls", "--analysis", str(out / "analysis.json"), "--video", str(video),
                 "--out", str(result)], cwd=ROOT / "cv", stdout=log, stderr=subprocess.STDOUT)
        _job = (clip_id, key, process)
        return jsonify(clip=clip_id, window=key, status="queued"), 202


@var_fouls_bp.get("/var/fouls/<clip_id>")
def get(clip_id):
    key = _window(request.args.get("start"), request.args.get("end"))
    if not ID.fullmatch(clip_id) or not key:
        return jsonify(error="Numeric clip ID and a valid start/end window are required"), 400
    status = _status(clip_id, key)
    result, progress, error = _files(clip_id, key)
    body = {"clip": clip_id, "window": key, "status": status, "progress": _read(progress) if status == "running" else None,
            "error": (_read(error) or {}).get("error", "Foul review failed") if status == "failed" else None,
            "incidents": None, "message": None, "assumptions": [], "policy": None, "suggested_pairs": []}
    if status == "done":
        data = _read(result)
        if not isinstance(data, dict):
            body.update(status="failed", error="The foul review result could not be read")
        else:
            body.update(review(data), suggested_pairs=suggested_pairs(clip_id, key))
    return jsonify(body)


@var_fouls_bp.post("/var/fouls/<clip_id>/combine")
def combine_angles(clip_id):
    """One incident from several reviewed windows (camera angles): body {"parts": [{clip?, start, end, id}],
    "league"?, "event"?}. A part from another clip needs league and event, and both clips listed for that event."""
    body = request.get_json(silent=True) or {}
    parts = body.get("parts")
    if (not ID.fullmatch(clip_id) or not isinstance(parts, list) or not 2 <= len(parts) <= 4
            or not all(isinstance(p, dict) and isinstance(p.get("clip", clip_id), str) and ID.fullmatch(p.get("clip", clip_id)) for p in parts)):
        return jsonify(error="A numeric clip ID and 2-4 parts ({clip?, start, end, id}) are required"), 400
    refused = _same_event(body, [clip_id] + [p.get("clip", clip_id) for p in parts])
    if refused:
        return refused
    found = []
    for p in parts:
        c, key = p.get("clip", clip_id), _window(p.get("start"), p.get("end"))
        data = _dict(_files(c, key)[0]) if key else {}
        inc = next((i for i in data.get("incidents") or [] if i.get("id") == p.get("id")), None)
        if inc is None:
            return jsonify(error=f"No reviewed challenge {p.get('id')} in window {key}" + (f" of clip {c}" if c != clip_id else "")), 404
        found.append((c, key, inc))
    if len({(c, k) for c, k, _ in found}) != len(found):
        return jsonify(error="Pick challenges from different windows (angles)"), 400
    pairs = []
    for c, k in dict.fromkeys((c, k) for c, k, _ in found):
        pairs += [p for p in suggested_pairs(c, k) if p not in pairs]
    try:
        out = combine([(k if c == clip_id else f"clip {c} {k}", inc) for c, k, inc in found], clips=[c for c, _, _ in found])
    except ValueError as e:  # not the same incident, but the windows can still be calibrated (unanchored)
        xv = _crossview_request(found, anchor=False)
        return jsonify(error=str(e), suggested_pairs=pairs, crossview_available=xv is not None, crossview_request=xv), 409
    xv = _crossview_request(found)
    return jsonify({**out, "crossview_available": xv is not None, "crossview_request": xv, "suggested_pairs": pairs})

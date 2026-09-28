"""Run the CV pipeline on ESPN-listed clips and serve its results; official calls stay separate."""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import requests
from flask import Blueprint, jsonify, request, send_file

from routes.var_clips import ESPN_LEAGUES, _get, clip_list
from var_offside import assess as assess_offside, review as review_offside

var_analysis_bp = Blueprint("var_analysis", __name__)
ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r"\d{1,12}")
KEY = re.compile(r"\d+\.\d-\d+\.\d")
MAX_WINDOW_SECONDS = 10
STALE_SECONDS = 600
# ponytail: one module-level job per process, busy → 409; add a queue if people analyse in parallel.
_lock = threading.Lock()
_job = None  # (clip_id, window_key, Popen)
OFFICIAL_TYPES = {"offside": "offside", "red-card": "red_card", "yellow-card": "yellow_card", "own-goal": "goal"}


def _out(clip_id, key=None):
    clip_dir = Path(os.environ.get("VAR_DATA_DIR") or ROOT / "var_data").resolve() / clip_id
    return clip_dir / key if key else clip_dir


def _window(start, end):
    """Window key "12.0-17.0" built only from validated floats rounded to 0.1 s, or None."""
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    try:
        start, end = round(float(start), 1) + 0.0, round(float(end), 1) + 0.0  # + 0.0 turns -0.0 into 0.0
    except (TypeError, ValueError, OverflowError):
        return None
    if not (0 <= start < end and round(end - start, 1) <= MAX_WINDOW_SECONDS):  # NaN/inf fail here
        return None
    return f"{start:.1f}-{end:.1f}"


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _status(clip_id, key):
    out = _out(clip_id, key)
    if (out / "analysis.json").exists():
        return "done"
    if (out / "error.json").exists():
        return "failed"
    if _job and _job[:2] == (clip_id, key):
        code = _job[2].poll()
        if code is None:
            return "running"
        crash = f"CV process exited with code {code} without a result; see var_data/{clip_id}/{key}/cv.log"
    else:
        progress = out / "progress.json"
        if not progress.exists():
            return "none"
        # ponytail: an untracked process (e.g. after a server reload) is judged by progress age alone.
        if time.time() - progress.stat().st_mtime < STALE_SECONDS:
            return "running"
        crash = "Analysis stopped updating without a result"
    (out / "error.json").write_text(json.dumps({"error": crash}))
    return "failed"


@var_analysis_bp.post("/var/analyze")
def analyze():
    global _job
    body = request.get_json(silent=True) or {}
    league, event_id, clip_id = body.get("league"), body.get("event"), body.get("clip")
    key = _window(body.get("start"), body.get("end"))
    if league not in ESPN_LEAGUES or not all(isinstance(v, str) and ID.fullmatch(v) for v in (event_id, clip_id)):
        return jsonify(error="A supported league and numeric ESPN event and clip IDs are required"), 400
    if not key:
        return jsonify(error=f"start and end seconds are required, 0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart"), 400
    with _lock:
        status = _status(clip_id, key)
        if status in ("done", "running"):
            return jsonify(clip=clip_id, window=key, status=status), 200 if status == "done" else 202
        if _job and _job[2].poll() is None:
            return jsonify(error=f"Clip {_job[0]} window {_job[1]} is already being analysed; try again when it finishes"), 409
        python = Path(os.environ.get("VAR_CV_PYTHON") or ROOT / "cv/.venv/bin/python")
        if not python.exists():
            return jsonify(error=f"CV environment not found at {python}. Run cv/setup.sh or set VAR_CV_PYTHON."), 503
        try:
            clip = next((c for c in clip_list(league, event_id) if c["id"] == clip_id), None)
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
            return jsonify(error="Could not load ESPN clips"), 502
        if not clip:
            return jsonify(error="Clip is not listed for this ESPN event"), 404
        if not clip["source_url"]:
            return jsonify(error="ESPN lists no downloadable source for this clip"), 422
        out = _out(clip_id, key)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("error.json", "progress.json"):
            (out / name).unlink(missing_ok=True)
        start, end = key.split("-")
        with open(out / "cv.log", "w") as log:
            process = subprocess.Popen(
                [str(python), "-m", "var_cv.analyze", "--clip-id", clip_id, "--source-url", clip["source_url"],
                 "--video", str(_out(clip_id) / "video.mp4"), "--start", start, "--end", end, "--out", str(out)],
                cwd=ROOT / "cv", stdout=log, stderr=subprocess.STDOUT)
        _job = (clip_id, key, process)
        return jsonify(clip=clip_id, window=key, status="queued"), 202


@var_analysis_bp.get("/var/analysis/<clip_id>")
def analysis(clip_id):
    key = _window(request.args.get("start"), request.args.get("end"))
    if not ID.fullmatch(clip_id) or not key:
        return jsonify(error="Numeric clip ID and a valid start/end window are required"), 400
    status, out = _status(clip_id, key), _out(clip_id, key)
    error = (_read(out / "error.json") or {}).get("error", "Analysis failed") if status == "failed" else None
    return jsonify(clip=clip_id, window=key, status=status, progress=_read(out / "progress.json") if status != "none" else None,
                   error=error, result=_read(out / "analysis.json") if status == "done" else None)


@var_analysis_bp.get("/var/windows/<clip_id>")
def windows(clip_id):
    if not ID.fullmatch(clip_id):
        return jsonify(error="Numeric clip ID required"), 400
    clip_dir, result = _out(clip_id), []
    for path in clip_dir.iterdir() if clip_dir.is_dir() else []:
        start, _, end = path.name.partition("-")
        if path.is_dir() and KEY.fullmatch(path.name) and _window(start, end) == path.name:
            status = _status(clip_id, path.name)
            if status != "none":
                result.append({"start": float(start), "end": float(end), "key": path.name, "status": status})
    return jsonify(clip=clip_id, windows=sorted(result, key=lambda w: (w["start"], w["end"])))


@var_analysis_bp.get("/var/video/<clip_id>")
def video(clip_id):
    path = _out(clip_id) / "video.mp4" if ID.fullmatch(clip_id) else None
    if not path or not path.is_file():
        return jsonify(error="Video not available"), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@var_analysis_bp.get("/var/official")
def official():
    """Decisions as ESPN reports them. Never used to tune or grade the system's assessment."""
    league, event_id = request.args.get("league", "PD"), request.args.get("event", "")
    if league not in ESPN_LEAGUES or not ID.fullmatch(event_id):
        return jsonify(error="A supported league and numeric ESPN event ID are required"), 400
    try:
        data = _get(league, "summary", event=event_id)
        plays = [c["play"] for c in data.get("commentary") or [] if c.get("play")]
        seen = {p.get("id") for p in plays}
        plays += [k for k in data.get("keyEvents") or [] if k.get("id") not in seen]
        events = []
        for play in sorted(plays, key=lambda p: ((p.get("period") or {}).get("number") or 0, (p.get("clock") or {}).get("value") or 0)):
            slug, text = (play.get("type") or {}).get("type") or "", play.get("text") or ""
            kind = ("var" if slug.startswith("var") or slug == "deleted-after-review" or re.search(r"\bVAR\b", text)
                    else "penalty" if slug.startswith("penalty") else "goal" if slug == "goal" or slug.startswith("goal---") else OFFICIAL_TYPES.get(slug))
            if kind:
                events.append({"type": kind, "clock": (play.get("clock") or {}).get("displayValue") or None,
                               "team": (play.get("team") or {}).get("displayName"), "text": text})
        return jsonify(provider="ESPN", event=event_id, events=events)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN match events"), 502


@var_analysis_bp.post("/var/assess")
def assess():
    body = request.get_json(silent=True) or {}
    clip_id, t, track, team, direction = (body.get(k) for k in ("clip", "t", "attacker_track_id", "attacking_team", "attack_direction"))
    if (not isinstance(clip_id, str) or not ID.fullmatch(clip_id) or isinstance(t, bool) or not isinstance(t, (int, float))
            or isinstance(track, bool) or not isinstance(track, int) or team not in ("A", "B") or direction not in (None, "left", "right")):
        return jsonify(error="clip, numeric t, integer attacker_track_id, attacking_team A|B and optional attack_direction left|right are required"), 400
    key = _window(body.get("start"), body.get("end"))
    if not key:
        return jsonify(error=f"start and end seconds are required, 0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart"), 400
    result = _analysis(clip_id, key)
    if not result:
        return jsonify(error="No analysed frames for this clip window"), 404
    frame = _frame_at(result, t)
    verdict = assess_offside(frame, track, team, direction, *_scale(result))
    verdict["reasons"].insert(0, "The frame judged is the one you selected as the moment the ball was played; it was not detected automatically.")
    verdict["frame_t"] = frame["t"]
    return jsonify(verdict)


@var_analysis_bp.post("/var/review")
def review():
    """One-click review of every automatically detected pass in the window."""
    body = request.get_json(silent=True) or {}
    clip_id, key = body.get("clip"), _window(body.get("start"), body.get("end"))
    if not isinstance(clip_id, str) or not ID.fullmatch(clip_id) or not key:
        return jsonify(error=f"clip and a start/end window (0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart) are required"), 400
    result = _analysis(clip_id, key)
    if not result:
        return jsonify(error="No analysed frames for this clip window"), 404
    if "events" not in result:
        return jsonify(reviews=[], message="This analysis predates automatic pass detection; re-analyse the window or pick the moment manually.")
    reviews = []
    for event in (e for e in result["events"] or [] if e.get("type") == "pass" and isinstance(e.get("t"), (int, float))):
        frame = _frame_at(result, event["t"])
        team = event.get("team") or next((p.get("team") for p in frame.get("players") or [] if p.get("track_id") == event.get("passer_track_id")), None)
        key_result, candidates = review_offside(frame, event.get("passer_track_id"), team, *_scale(result))
        confidence = event.get("confidence")
        detail = "; ".join(filter(None, [f"confidence {confidence:.2f}" if isinstance(confidence, (int, float)) else None, event.get("reason")]))
        key_result["reasons"].insert(0, f"Frame chosen automatically as the pass moment ({detail or 'no detail'}); check it against the video.")
        key_result["frame_t"] = frame["t"]
        reviews.append({"event": event, "key": key_result, "candidates": candidates})
    return jsonify(reviews=reviews, message=None if reviews else "No pass was detected automatically in this window; pick the moment manually.")


def _analysis(clip_id, key):
    result = _read(_out(clip_id, key) / "analysis.json")
    return result if isinstance(result, dict) and result.get("frames") else None


def _scale(result):
    return (result.get("pitch") or {}).get("length_m", 105.0), (result.get("video") or {}).get("sampled_fps")


def _frame_at(result, t):
    """Nearest analysed frame to t, within the shot containing t when one does."""
    shot = next((s["id"] for s in result.get("shots") or [] if s["start"] <= t <= s["end"]), None)
    frames = [f for f in result["frames"] if f.get("shot") == shot] or result["frames"]
    return min(frames, key=lambda f: abs(f["t"] - t))

"""Foul / red-card review of an analysed window: run the CV foul pass and serve Law 12 assessments."""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from routes.var_analysis import ID, MAX_WINDOW_SECONDS, ROOT, _out, _read, _window
from var_fouls import combine, review

var_fouls_bp = Blueprint("var_fouls", __name__)
STALE_SECONDS = 600
# ponytail: one foul job per process (separate from the analysis job), busy -> 409; queue if needed.
_lock = threading.Lock()
_job = None  # (clip_id, window_key, Popen)
WINDOW_ERROR = f"clip and start/end seconds are required, 0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart"


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


@var_fouls_bp.post("/var/fouls")
def start():
    global _job
    body = request.get_json(silent=True) or {}
    clip_id, key = body.get("clip"), _window(body.get("start"), body.get("end"))
    if not isinstance(clip_id, str) or not ID.fullmatch(clip_id) or not key:
        return jsonify(error=WINDOW_ERROR), 400
    with _lock:
        status = _status(clip_id, key)
        if status in ("done", "running"):
            return jsonify(clip=clip_id, window=key, status=status), 200 if status == "done" else 202
        if _job and _job[2].poll() is None:
            return jsonify(error=f"A foul review of clip {_job[0]} window {_job[1]} is running; try again when it finishes"), 409
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
            "incidents": None, "message": None, "assumptions": [], "policy": None}
    if status == "done":
        data = _read(result)
        if not isinstance(data, dict):
            body.update(status="failed", error="The foul review result could not be read")
        else:
            body.update(review(data))
    return jsonify(body)


@var_fouls_bp.post("/var/fouls/<clip_id>/combine")
def combine_angles(clip_id):
    """One incident from several reviewed windows (camera angles) of the clip: body {"parts": [{start, end, id}]}."""
    parts = (request.get_json(silent=True) or {}).get("parts")
    if not ID.fullmatch(clip_id) or not isinstance(parts, list) or not 2 <= len(parts) <= 4:
        return jsonify(error="A numeric clip ID and 2-4 parts ({start, end, id}) are required"), 400
    found = []
    for p in parts:
        key = _window(p.get("start"), p.get("end")) if isinstance(p, dict) else None
        data = _read(_files(clip_id, key)[0]) if key else None
        inc = next((i for i in (data or {}).get("incidents") or [] if i.get("id") == p.get("id")), None)
        if inc is None:
            return jsonify(error=f"No reviewed challenge {p.get('id') if isinstance(p, dict) else p} in window {key}"), 404
        found.append((key, inc))
    if len({k for k, _ in found}) != len(found):
        return jsonify(error="Pick challenges from different windows (angles)"), 400
    try:
        return jsonify(combine(found))
    except ValueError as e:
        return jsonify(error=str(e)), 409

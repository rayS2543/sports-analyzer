"""Results of the recent-goals sweep (backend/sweep.py) and a way to start one."""
import os
import subprocess
import sys
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from routes import var_analysis
from routes.var_clips import ESPN_LEAGUES, MAX_DISCOVER_DAYS

var_checks_bp = Blueprint("var_checks", __name__)
BACKEND = Path(__file__).resolve().parents[1]


def _progress():
    path = var_analysis._out("sweeps") / "_progress.json"
    state = var_analysis._read(path) or {}
    job = var_analysis._sweep
    if job:
        running = job[2].poll() is None
    else:  # a sweep started before a server reload: judged by how recently it wrote progress
        running = bool(state.get("running")) and time.time() - path.stat().st_mtime < var_analysis.STALE_SECONDS
    return dict(state, running=running)


@var_checks_bp.get("/var/checks")
def checks():
    """Every swept clip, newest match first, with its status and flags; flagged ones are the ones to look at."""
    base = var_analysis._out("sweeps")
    found = []
    for path in (sorted(base.glob("*.json")) if base.is_dir() else []):
        record = var_analysis._read(path) if not path.name.startswith("_") else None
        if isinstance(record, dict) and record.get("clip"):
            record["flagged"] = any(w.get("flags") or any(p.get("flags") for p in w.get("passes", [])) for w in record.get("windows", []))
            found.append(record)
    found.sort(key=lambda r: (r["clip"].get("date") or "", r["clip"].get("id") or ""), reverse=True)
    return jsonify(checks=found, sweep=_progress())


@var_checks_bp.get("/var/sweep")
def sweep_status():
    return jsonify(_progress())


@var_checks_bp.post("/var/sweep")
def start_sweep():
    body = request.get_json(silent=True) or {}
    league, days, limit = body.get("league", "PD"), body.get("days", 14), body.get("limit", 20)
    if league not in ESPN_LEAGUES or not all(isinstance(v, int) and not isinstance(v, bool) for v in (days, limit)) \
            or not 1 <= days <= MAX_DISCOVER_DAYS or not 1 <= limit <= 40:
        return jsonify(error=f"A supported league, days 1-{MAX_DISCOVER_DAYS} and limit 1-40 are required"), 400
    with var_analysis._lock:
        busy = var_analysis._running()
        if busy:
            return jsonify(error=busy), 409
        python = Path(os.environ.get("VAR_CV_PYTHON") or var_analysis.ROOT / "cv/.venv/bin/python")
        if not python.exists():
            return jsonify(error=f"CV environment not found at {python}. Run cv/setup.sh or set VAR_CV_PYTHON."), 503
        (var_analysis._out("sweeps")).mkdir(parents=True, exist_ok=True)
        log = open(var_analysis._out("sweeps") / "sweep.log", "w")
        process = subprocess.Popen([sys.executable, "-m", "sweep", "--league", league, "--days", str(days), "--limit", str(limit)],
                                   cwd=BACKEND, stdout=log, stderr=subprocess.STDOUT)
        var_analysis._sweep = ("sweep", f"{league}, last {days} days", process)
    return jsonify(status="started", league=league, days=days, limit=limit), 202

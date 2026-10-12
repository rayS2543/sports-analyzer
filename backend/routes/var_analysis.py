"""Run the CV pipeline on ESPN-listed clips and serve its results; official calls stay separate."""
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
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
# ponytail: one heavy CV job machine-wide (window analysis, foul review or cross-view; the fanless Air overheats
# running two), busy -> 409; add a queue if people analyse in parallel.
_lock = threading.Lock()  # guards _job and _crossview here and var_fouls._job
_job = None  # (clip_id, window_key, Popen): window analysis
_crossview = None  # (clip_id, window_key, _CrossviewJob): cross-view calibration, then the replay's foul re-run
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


def _running():
    """Why a new heavy CV job has to wait (one runs at a time, whatever its kind), or None. Call with _lock held."""
    from routes import var_fouls  # deferred: var_fouls imports this module
    for job, doing in ((_job, "being analysed"), (var_fouls._job, "having its challenges reviewed"),
                       (_crossview, "being calibrated from the live camera")):
        if job and job[2].poll() is None:
            return f"Clip {job[0]} window {job[1]} is {doing}; try again when it finishes"
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
        busy = _running()
        if busy:
            return jsonify(error=busy), 409
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
                result.append({"start": float(start), "end": float(end), "key": path.name, "status": status,
                               "cross_view": _xv_status(clip_id, path.name)})
    return jsonify(clip=clip_id, windows=sorted(result, key=lambda w: (w["start"], w["end"])))


# ---------- cross-view: calibrate a replay window from a calibrated live window of the same play ----------

def _xv_files(clip_id, key):
    out = _out(clip_id, key)
    return out / "crossview.json", out / "crossview.progress.json", out / "crossview.error.json"


def _xv_status(clip_id, key):
    """none|running|done|failed of a window's cross-view job. A calibration that honestly failed is "failed"."""
    report, progress, error = _xv_files(clip_id, key)
    if _crossview and _crossview[:2] == (clip_id, key) and _crossview[2].poll() is None:
        return "running"
    if error.exists():
        return "failed"
    if report.exists():
        return "done" if (_read(report) or {}).get("status") == "done" else "failed"
    if not progress.exists():
        return "none"
    if time.time() - progress.stat().st_mtime < STALE_SECONDS:  # untracked, e.g. after a server reload
        return "running"
    error.write_text(json.dumps({"error": "Cross-view calibration stopped updating without a result"}))
    return "failed"


def _wait(cmd, log):
    with open(log, "w") as f:
        return subprocess.Popen(cmd, cwd=ROOT / "cv", stdout=f, stderr=subprocess.STDOUT).wait()


class _CrossviewJob:
    """Cross-view calibration, then (only if it calibrated) the replay window's foul review: one process at a
    time on a thread. poll() answers like Popen's, so the pair counts as one heavy job."""

    def __init__(self, clip_id, key, crossview_cmd, fouls_cmd):
        self.code, self.stage = None, "crossview"
        self.thread = threading.Thread(target=self._run, args=(clip_id, key, crossview_cmd, fouls_cmd), daemon=True)
        self.thread.start()

    def poll(self):
        return self.code

    def _run(self, clip_id, key, crossview_cmd, fouls_cmd):
        out = _out(clip_id, key)
        report, _, error = _xv_files(clip_id, key)

        def fail(message):
            if not error.exists():  # keep the CLI's own error when it wrote one
                error.write_text(json.dumps({"error": message}))

        code = 1
        try:
            code = _wait(crossview_cmd, out / "crossview.log")
            result = _read(report)
            if code:
                fail(f"Cross-view calibration exited with code {code}; see var_data/{clip_id}/{key}/crossview.log")
            elif not isinstance(result, dict):
                fail("Cross-view calibration finished without a readable report")
            elif result.get("status") == "done":  # an honest failure keeps the old foul review: nothing changed
                self.stage = "fouls"
                for name in ("fouls.progress.json", "fouls.error.json"):
                    (out / name).unlink(missing_ok=True)
                code = _wait(fouls_cmd, out / "fouls.log")
                if code:
                    reason = (_read(out / "fouls.error.json") or {}).get("error") or f"exit code {code}; see var_data/{clip_id}/{key}/fouls.log"
                    fail(f"The replay was calibrated, but re-running its foul review failed: {reason}")
        except Exception as e:  # never leave the heavy-job slot looking busy
            fail(f"Could not run the cross-view job: {e}")
        finally:
            self.code = code


def _same_event(body, clips):
    """Error response unless every clip is listed for the body's ESPN event; only checked across clips."""
    if len(set(clips)) < 2:
        return None
    league, event_id = body.get("league"), body.get("event")
    if league not in ESPN_LEAGUES or not isinstance(event_id, str) or not ID.fullmatch(event_id):
        return jsonify(error="Parts from another clip need the league and numeric ESPN event they belong to"), 400
    try:
        listed = {c["id"] for c in clip_list(league, event_id)}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN clips"), 502
    if not set(clips) <= listed:
        return jsonify(error="Every clip must be listed for this ESPN event"), 404
    return None


def _anchor(value, live_key, key):
    """[live_t, replay_t], each inside its window (1 s slack for shot edges), as the CLI's LIVE_T:REPLAY_T, else None."""
    if not isinstance(value, list) or len(value) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    for t, k in zip(value, (live_key, key)):
        start, end = map(float, k.split("-"))
        if not start - 1 <= t <= end + 1:  # NaN/inf fail here
            return None
    return f"{value[0]:.3f}:{value[1]:.3f}"


@var_analysis_bp.post("/var/analysis/<clip_id>/crossview")
def crossview(clip_id):
    """Body {start, end, live: {clip?, start, end}, anchor?: [live_t, replay_t], league?, event?}; league and
    event are required only when the live part is another clip, which must be listed for the same ESPN event."""
    global _crossview
    body = request.get_json(silent=True) or {}
    live = body.get("live") if isinstance(body.get("live"), dict) else {}
    key, live_key, live_clip = _window(body.get("start"), body.get("end")), _window(live.get("start"), live.get("end")), live.get("clip", clip_id)
    if not ID.fullmatch(clip_id) or not isinstance(live_clip, str) or not ID.fullmatch(live_clip) or not key or not live_key:
        return jsonify(error=f"A numeric clip ID, the replay's start/end and live {{clip?, start, end}} are required "
                             f"(0 <= start < end, at most {MAX_WINDOW_SECONDS} s apart)"), 400
    if (live_clip, live_key) == (clip_id, key):
        return jsonify(error="The live part must be a different window from the replay"), 400
    anchor = None
    if body.get("anchor") is not None:
        anchor = _anchor(body["anchor"], live_key, key)
        if not anchor:
            return jsonify(error="anchor must be [live_t, replay_t] in seconds, each inside its window"), 400
    refused = _same_event(body, (clip_id, live_clip))
    if refused:
        return refused
    with _lock:
        status = _xv_status(clip_id, key)
        if status in ("done", "running"):
            return jsonify(clip=clip_id, window=key, status=status), 200 if status == "done" else 202
        busy = _running()
        if busy:
            return jsonify(error=busy), 409
        out, live_out, video = _out(clip_id, key), _out(live_clip, live_key), _out(clip_id) / "video.mp4"
        if not (out / "analysis.json").exists():
            return jsonify(error="Analyse the replay window first."), 409
        if not (live_out / "analysis.json").exists():
            return jsonify(error="Analyse the live window first; the replay is calibrated from its tracked players."), 409
        if not video.exists():
            return jsonify(error="Source video for this clip is missing; re-run the analysis."), 409
        python = Path(os.environ.get("VAR_CV_PYTHON") or ROOT / "cv/.venv/bin/python")
        if not python.exists():
            return jsonify(error=f"CV environment not found at {python}. Run cv/setup.sh or set VAR_CV_PYTHON."), 503
        report, progress, error = _xv_files(clip_id, key)
        for path in (report, progress, error):
            path.unlink(missing_ok=True)
        progress.write_text(json.dumps({"stage": "crossview", "progress": 0.0, "message": "Starting cross-view calibration"}))
        cmd = [str(python), "-m", "var_cv.crossview", "--replay", str(out), "--live", str(live_out), "--video", str(video)]
        fouls = [str(python), "-m", "var_cv.fouls", "--analysis", str(out / "analysis.json"), "--video", str(video), "--out", str(out / "fouls.json")]
        _crossview = (clip_id, key, _CrossviewJob(clip_id, key, cmd + (["--anchor", anchor] if anchor else []), fouls))
        return jsonify(clip=clip_id, window=key, live={"clip": live_clip, "window": live_key}, status="queued"), 202


@var_analysis_bp.get("/var/analysis/<clip_id>/crossview")
def crossview_status(clip_id):
    key = _window(request.args.get("start"), request.args.get("end"))
    if not ID.fullmatch(clip_id) or not key:
        return jsonify(error="Numeric clip ID and a valid start/end window are required"), 400
    status = _xv_status(clip_id, key)
    report_path, progress_path, error_path = _xv_files(clip_id, key)
    report = _read(report_path) if status in ("done", "failed") else None
    report = report if isinstance(report, dict) else None
    error = progress = None
    if status == "failed":
        error = (_read(error_path) or {}).get("error") or (report or {}).get("failure") or "Cross-view calibration failed"
    if status == "running":
        job = _crossview[2] if _crossview and _crossview[:2] == (clip_id, key) else None
        if job and job.stage == "fouls":
            p = _read(_out(clip_id, key) / "fouls.progress.json")
            p = p if isinstance(p, dict) else {}
            progress = {"stage": "fouls", "progress": p.get("progress"),
                        "message": "Re-running the foul review on the calibrated replay" + (f": {p['message']}" if p.get("message") else "")}
        else:
            progress = _read(progress_path)
    return jsonify(clip=clip_id, window=key, status=status, progress=progress, error=error, report=report)


@var_analysis_bp.get("/var/video/<clip_id>")
def video(clip_id):
    path = _out(clip_id) / "video.mp4" if ID.fullmatch(clip_id) else None
    if not path or not path.is_file():
        return jsonify(error="Video not available"), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


def _official_plays(league, event_id):
    """[(kind, play)] for every decision ESPN reports for the event, in match order."""
    data = _get(league, "summary", event=event_id)
    plays = [c["play"] for c in data.get("commentary") or [] if c.get("play")]
    seen = {p.get("id") for p in plays}
    plays += [k for k in data.get("keyEvents") or [] if k.get("id") not in seen]
    result = []
    for play in sorted(plays, key=lambda p: ((p.get("period") or {}).get("number") or 0, (p.get("clock") or {}).get("value") or 0)):
        slug, text = (play.get("type") or {}).get("type") or "", play.get("text") or ""
        kind = ("var" if slug.startswith("var") or slug == "deleted-after-review" or re.search(r"\bVAR\b", text)
                else "penalty" if slug.startswith("penalty") else "goal" if slug == "goal" or slug.startswith("goal---") else OFFICIAL_TYPES.get(slug))
        if kind:
            result.append((kind, play))
    return result


@var_analysis_bp.get("/var/official")
def official():
    """Decisions as ESPN reports them. Never used to tune or grade the system's assessment."""
    league, event_id = request.args.get("league", "PD"), request.args.get("event", "")
    if league not in ESPN_LEAGUES or not ID.fullmatch(event_id):
        return jsonify(error="A supported league and numeric ESPN event ID are required"), 400
    try:
        events = [{"type": kind, "clock": (play.get("clock") or {}).get("displayValue") or None,
                   "team": (play.get("team") or {}).get("displayName"), "text": play.get("text") or ""}
                  for kind, play in _official_plays(league, event_id)]
        return jsonify(provider="ESPN", event=event_id, events=events)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN match events"), 502


def _fold(text):
    """Lower-case and accent-free, so "Mbappé" in a key event matches "Mbappe" in a headline."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()


def _names(title, name):
    """True if the title names the player in full or by surname (ESPN headlines often use only the surname)."""
    name, title = _fold(name).split(), _fold(title)
    return bool(name) and any(re.search(rf"\b{re.escape(n)}\b", title) for n in (" ".join(name), name[-1]))


@var_analysis_bp.get("/var/angles")
def angles():
    """Other ESPN clips of the event whose titles name the players of this clip's incident (from the official
    key events): candidate extra camera angles. Discovery only; nothing here is evidence."""
    league, event_id, clip_id = (request.args.get(k, "") for k in ("league", "event", "clip"))
    if league not in ESPN_LEAGUES or not ID.fullmatch(event_id) or not ID.fullmatch(clip_id):
        return jsonify(error="A supported league and numeric ESPN event and clip IDs are required"), 400
    try:
        clips, plays = clip_list(league, event_id), _official_plays(league, event_id)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN clips or match events"), 502
    this = next((c for c in clips if c["id"] == clip_id), None)
    if not this:
        return jsonify(error="Clip is not listed for this ESPN event"), 404
    players = {}  # name -> ["red card 38'", ...] for players this clip's title names
    for kind, play in plays:
        for part in play.get("participants") or []:
            name = (part.get("athlete") or {}).get("displayName") if isinstance(part, dict) else None
            if isinstance(name, str) and _names(this["title"], name):
                label = " ".join(filter(None, [kind.replace("_", " "), (play.get("clock") or {}).get("displayValue")]))
                players.setdefault(name, []).append(label)
    result = []
    for c in clips:
        named = [n for n in players if c["id"] != clip_id and _names(c["title"], n)]
        if named:
            result.append({"id": c["id"], "title": c["title"], "duration_seconds": c["duration_seconds"],
                           "reason": "Title names " + "; ".join(f"{n} ({', '.join(players[n])})" for n in named)})
    message = None if players else "This clip's title names no player from the official key events, so its incident's players are unknown."
    return jsonify(provider="ESPN", event=event_id, clip=clip_id, players=list(players), clips=result, message=message)


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

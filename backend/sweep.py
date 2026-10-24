"""Batch: a league's recent goal clips -> analysis of each clip's live build-up -> offside readings, saved for the Checks page.

    python -m sweep --league PD --days 14 --limit 20

Footage comes from ESPN's CDN only (the analysis step downloads it and refuses any other host). One heavy CV job at a
time, at low priority. A clip already swept is skipped, so running it again only does the new ones. Each result says what
the pipeline had (calibrated frames, players, passes) and flags readings that need a human look; nothing here is a verdict
on a call: an offside *position* at a pass is not an offence, and official decisions are never consulted."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from routes import var_analysis
from routes.var_clips import ESPN_LEAGUES, MAX_DISCOVER_DAYS, find_clips

WINDOW_S = 10.0           # the analysis takes at most this many seconds at a time
MAX_WINDOWS = 2           # a long live build-up gets a second window straight after the first
LARGE_MARGIN_M = 3.0      # an offside position this far beyond the line in ordinary play deserves a human look
MIN_CALIBRATED = 0.5      # below this share of calibrated frames the window's positions are not usable
ANALYSIS_TIMEOUT_S = 900


def sweeps_dir():
    return var_analysis._out("sweeps")


def result_path(clip_id):
    return sweeps_dir() / f"{clip_id}.json"


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def windows_after(duration, first_result):
    """The next window to analyse after the first, or None: only when the clip is longer and the first window ended
    inside a shot that goes on (a long wide build-up), not at a cut."""
    shots = (first_result or {}).get("shots") or []
    window_end = (first_result or {}).get("window", {}).get("end", WINDOW_S)
    if duration and duration > WINDOW_S + 0.5 and shots and shots[-1].get("end", 0) >= window_end - 0.2:
        return (WINDOW_S, min(2 * WINDOW_S, duration))
    return None


def summarise_window(clip_id, key, result):
    """What the pipeline had for one analysed window and what it read at each pass."""
    frames = result["frames"]
    calibrated = [f for f in frames if (f.get("calibration") or {}).get("ok")]
    placed = sorted(len([p for p in f.get("players") or [] if p.get("x") is not None]) for f in calibrated)
    passes = []
    for rv in var_analysis.review_window(result) or []:
        k = rv["key"]
        flags = []
        if k["verdict"] == "offside" and (k.get("margin_m") or 0) > LARGE_MARGIN_M:  # a clear onside, however large, needs no second look
            flags.append(f"an offside position by {k['margin_m']:.1f} m is unusually large: check the attacker and the defender line by eye")
        passes.append({"t": rv["event"]["t"], "verdict": k["verdict"], "margin_m": k.get("margin_m"), "uncertainty_m": k.get("uncertainty_m"),
                       "attacker_track_id": k.get("attacker_track_id"), "second_last_defender_track_id": k.get("second_last_defender_track_id"),
                       "attack_direction": k.get("attack_direction"), "restart": k.get("restart"),
                       "reasons": [r for r in k.get("reasons", [])][:3], "flags": flags})
    window = {"key": key, "calibrated_frames": [len(calibrated), len(frames)], "players_per_frame": placed[len(placed) // 2] if placed else 0, "passes": passes, "flags": []}
    if frames and len(calibrated) < MIN_CALIBRATED * len(frames):
        window["flags"].append("the pitch could not be fitted in most frames, so positions here are not usable")
    return window


def clip_status(windows):
    if not windows or all(w.get("error") for w in windows):
        return "failed"
    good = [w for w in windows if not w.get("error") and not w["flags"]]
    if not good:
        return "uncalibrated"
    passes = [p for w in good for p in w["passes"]]
    if not passes:
        return "no_passes"
    return "read" if any(p["verdict"] in ("onside", "offside") for p in passes) else "inconclusive"


def analyse(clip, start, end, python):
    """Run the CV pipeline on one window of an ESPN clip: its analysis dict, or (None, why)."""
    key = var_analysis._window(start, end)
    out = var_analysis._out(clip["id"], key)
    result = var_analysis._analysis(clip["id"], key)
    if result:
        return key, result, None
    out.mkdir(parents=True, exist_ok=True)
    for name in ("error.json", "progress.json"):
        (out / name).unlink(missing_ok=True)
    s, e = key.split("-")
    cmd = ["nice", "-n", "10", str(python), "-m", "var_cv.analyze", "--clip-id", clip["id"], "--source-url", clip["source_url"],
           "--video", str(var_analysis._out(clip["id"]) / "video.mp4"), "--start", s, "--end", e, "--out", str(out)]
    try:
        with open(out / "cv.log", "w") as log:
            subprocess.run(cmd, cwd=var_analysis.ROOT / "cv", stdout=log, stderr=subprocess.STDOUT, timeout=ANALYSIS_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return key, None, "the analysis timed out"
    result = var_analysis._analysis(clip["id"], key)
    if result:
        return key, result, None
    error = var_analysis._read(out / "error.json")
    return key, None, (error or {}).get("error") or "the analysis produced no result"


def sweep_clip(clip, python):
    duration = clip.get("duration_seconds") or WINDOW_S
    windows, result = [], None
    spans = [(0.0, min(WINDOW_S, duration))]
    while spans and len(windows) < MAX_WINDOWS:
        start, end = spans.pop(0)
        key, result, error = analyse(clip, start, end, python)
        if error:
            windows.append({"key": key, "error": error, "passes": [], "flags": [], "calibrated_frames": [0, 0], "players_per_frame": 0})
            break
        windows.append(summarise_window(clip["id"], key, result))
        follow = windows_after(duration, dict(result, window={"end": end}))
        if follow:
            spans.append(follow)
    record = {"clip": {k: clip.get(k) for k in ("id", "title", "match", "date", "event", "duration_seconds", "page_url")},
              "league": clip.get("league"), "status": clip_status(windows), "windows": windows, "swept_at": int(time.time())}
    write_json(result_path(clip["id"]), record)
    return record


def run(league, days, limit, python):
    progress = sweeps_dir() / "_progress.json"
    last = date.today()
    clips, _, failed = find_clips(league, last - timedelta(days=days - 1), last, "goal")
    todo = [c for c in clips if not result_path(c["id"]).exists()][:limit]
    state = {"running": True, "league": league, "days": days, "found": len(clips), "total": len(todo), "done": 0, "current": None,
             "started": int(time.time()), "events_failed": failed}
    write_json(progress, state)
    for clip in todo:
        state["current"] = f"{clip.get('match')}: {clip.get('title')}"
        write_json(progress, state)
        try:
            sweep_clip(dict(clip, league=league), python)
        except Exception as exc:  # one bad clip must not stop the rest
            write_json(result_path(clip["id"]), {"clip": {k: clip.get(k) for k in ("id", "title", "match", "date", "event", "duration_seconds", "page_url")},
                                                  "league": league, "status": "failed", "windows": [], "error": f"{type(exc).__name__}: {exc}", "swept_at": int(time.time())})
        state["done"] += 1
    state.update(running=False, current=None, finished=int(time.time()))
    write_json(progress, state)
    return state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", default="PD", choices=sorted(ESPN_LEAGUES))
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=20, help="most new clips to analyse in this run")
    args = ap.parse_args(argv)
    if not 1 <= args.days <= MAX_DISCOVER_DAYS or not 1 <= args.limit <= 40:
        ap.error(f"--days must be 1-{MAX_DISCOVER_DAYS} and --limit 1-40")
    python = Path(os.environ.get("VAR_CV_PYTHON") or var_analysis.ROOT / "cv/.venv/bin/python")
    if not python.exists():
        print(f"CV environment not found at {python}", file=sys.stderr)
        return 1
    state = run(args.league, args.days, args.limit, python)
    print(json.dumps(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())

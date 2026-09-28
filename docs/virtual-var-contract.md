# Virtual VAR — data & API contract

The single source of truth for the analysis.json schema, the CV CLI and the backend HTTP API.
Amendments are cumulative: read top to bottom; later sections override earlier ones where they conflict.

Read `handoff.md` at the repo root first: it states the product intent, current state and honesty rules.

## Honesty rules (non-negotiable)
- Positions come from computer vision on real footage, never manual placement.
- Frames with bad/no calibration are marked and excluded from judgments, never faked.
- No interpolation across shot cuts.
- Official call (from ESPN play-by-play) is shown SEPARATELY from the system's assessment.
  Never tune the assessment to match it.
- "inconclusive" is a first-class verdict. Uncertainty is always reported.
- Player bodies in 3D are ASSUMED geometry (ground-plane position only); UI must say so.

## Layout
```
cv/                          # separate Python env for CV (torch/ultralytics/opencv). NOT imported by Flask.
  requirements.txt
  var_cv/ ...                # pipeline package
  weights/                   # gitignored; downloaded roboflow/sports YOLOv8 weights
var_data/<clip_id>/          # gitignored runtime output (repo root)
  video.mp4                  # downloaded source clip
  progress.json              # {"stage": str, "progress": 0..1, "message": str}
  analysis.json              # final result (schema below)
  error.json                 # {"error": str} on failure
backend/routes/var_clips.py  # existing discovery endpoints
backend/routes/var_analysis.py  # new job/analysis endpoints
backend/var_offside.py       # pure-python offside assessment (no numpy)
frontend/src/components/var/ # VAR UI
```

## CV CLI (the backend calls exactly this)
```
<cv python> -m var_cv.analyze --clip-id 46338651 --source-url <https mp4> --out var_data/46338651
```
- run with cwd = `cv/`. The backend finds the interpreter via env `VAR_CV_PYTHON`, default `cv/.venv/bin/python`.
- Writes progress.json repeatedly, then analysis.json atomically (write tmp + os.replace). Exit 0 on success.
- On failure writes error.json and exits non-zero.

## analysis.json schema (version 1)
Coordinates are metres on a pitch whose origin is the top-left corner flag as seen in the
standard broadcast orientation: x along the length (0..length_m), y across the width (0..width_m).
```json
{
  "version": 1,
  "clip_id": "46338651",
  "pitch": {"length_m": 105.0, "width_m": 68.0},
  "video": {"fps": 29.97, "duration_seconds": 74.0, "width": 1280, "height": 720, "sampled_fps": 5},
  "pipeline": {"device": "mps", "models": {"players": "...", "pitch": "...", "ball": "..."}, "elapsed_seconds": 123.4},
  "teams": {"A": {"color": "#c8102e"}, "B": {"color": "#1d3c8f"}},
  "shots": [
    {"id": 0, "start": 0.0, "end": 4.2, "calibrated_ratio": 0.9, "usable": true}
  ],
  "frames": [
    {
      "t": 1.2,
      "shot": 0,
      "calibration": {"ok": true, "reprojection_error_m": 0.42, "keypoints": 9},
      "ball": {"x": 52.1, "y": 30.2, "confidence": 0.61, "image": [640, 360]},
      "players": [
        {"track_id": 7, "role": "player", "team": "A", "x": 60.3, "y": 22.1,
         "confidence": 0.88, "bbox": [x1, y1, x2, y2], "foot": [u, v]}
      ]
    }
  ]
}
```
- `role` ∈ `player | goalkeeper | referee`. `team` ∈ `A | B | null` (referees null; goalkeepers assigned to a team when possible).
- When `calibration.ok` is false, player/ball `x`,`y` are `null` (image fields still present).
- `ball` may be `null`. `track_id` is stable within a shot only (reset per shot).
- `t` is seconds in source-video time (so the UI can sync a <video> element exactly).

## Backend HTTP API
Existing: `GET /var/fixtures?league&date`, `GET /var/clips?league&event`.
New:
- `POST /var/analyze` JSON `{"league":"PD","event":"748191","clip":"46338651"}` →
  validates the clip exists in that event's clip list (source URL comes from ESPN via our own
  discovery, NEVER from the request body), starts the CV subprocess (one at a time), returns 202
  `{"clip":"...","status":"queued|running"}`; returns 200 with status `done` if already analysed.
- `GET /var/analysis/<clip_id>` → `{"clip", "status": "none|running|done|failed", "progress": {...}|null, "error": str|null, "result": <analysis.json>|null}`
- `GET /var/video/<clip_id>` → serves `var_data/<clip_id>/video.mp4` (Range requests supported; `send_file(conditional=True)`).
- `GET /var/official?league&event` → official decisions from ESPN summary play-by-play/keyEvents:
  `{"events":[{"type":"offside|red_card|yellow_card|penalty|goal|var","clock":"23'","team":"Barcelona","text":"..."}]}`
- `POST /var/assess` JSON `{"clip":"...","t":12.4,"attacker_track_id":7,"attacking_team":"A","attack_direction":"left|right"}`
  → runs `var_offside.assess(frame, ...)` on the stored analysis frame nearest t (within same shot) →
  ```json
  {"verdict":"offside|onside|inconclusive","margin_m":0.8,"uncertainty_m":0.5,
   "offside_line_x":71.2,"second_last_defender_track_id":3,"attacker_track_id":7,
   "frame_t":12.4,"reasons":["..."],"attack_direction":"right"}
  ```
  `attack_direction` optional: if omitted, infer (e.g. defending goalkeeper position / defenders' mean) and
  say so in reasons; if it can't be inferred → inconclusive.
  Margin positive = attacker beyond line (offside). Inconclusive when |margin| <= uncertainty,
  calibration not ok, fewer than 2 defenders visible (the goalkeeper usually counts as one; if the
  keeper is off-screen we cannot know the second-last defender → inconclusive unless attacker is behind
  the ball or in own half), or attacker not tracked. Also: onside if attacker in own half, or level/behind ball.
  Uncertainty = reprojection_error_m combined with ground-anchor error (~0.3 m body-part margin since
  we only have foot position, not limbs) — document the formula.

## AMENDMENT 1 — analyse a short window, not the whole clip (user request; supersedes above where it conflicts)
Users only need a few seconds around an incident. Analysis is per (clip, window).
- Window: `start`, `end` in seconds of source-video time, rounded to 0.1 s, `0 <= start < end`, `end - start <= 10`.
  Window key string: `f"{start:.1f}-{end:.1f}"` e.g. `"12.0-17.0"`.
- Layout: `var_data/<clip_id>/video.mp4` (shared per clip) and `var_data/<clip_id>/<window_key>/{progress,analysis,error}.json` + `cv.log`.
- CV CLI: `python -m var_cv.analyze --clip-id ID --source-url URL --video var_data/<clip>/video.mp4 --start 12.0 --end 17.0 --out var_data/<clip>/12.0-17.0`
  Downloads to `--video` if missing. Only decodes/processes frames in [start, end] (seek with CAP_PROP_POS_MSEC or skip-read).
  Shot-cut detection runs inside the window only. Frame `t` remains ABSOLUTE source-video time.
  analysis.json gains `"window": {"start": 12.0, "end": 17.0}`; `video.duration_seconds` is still the full clip duration.
- Backend: `POST /var/analyze` body adds `start`, `end` (numbers, validated as above, 400 otherwise). Response adds `window` key string.
  `GET /var/analysis/<clip_id>?start=12.0&end=17.0` (both required). `POST /var/assess` body adds `start`, `end` to locate the analysis.
  New `GET /var/windows/<clip_id>` → `{"windows":[{"start":12.0,"end":17.0,"key":"12.0-17.0","status":"done|running|failed"}]}` so the UI can list prior analyses.
  `/var/video/<clip_id>` unchanged.
- Frontend: after picking a clip, show a PREVIEW player first using the clip's ESPN `source_url` directly (from /var/clips) — no analysis needed to watch.
  User scrubs/pauses at the incident → "Analyze these seconds" analyses `[t-3, t+2]` clamped to [0, duration] (adjustable window, e.g. two small nudge controls or a range on the timeline, max 10 s).
  Previously analysed windows for the clip are listed (from /var/windows) as chips to jump into instantly.
  Viewer timeline focuses on the window (shots/frames only exist there); the video element can still play the whole clip but 3D shows "Outside analysed window" beyond it.
  Deep link: `/var?league=PD&event=748191&clip=46338651&start=12.0&end=17.0`.

## AMENDMENT 2 — v2 upgrade (user: "make it better, it sucks"; all four areas). Additive to v1 + Amendment 1.
analysis.json `"version": 2`. All v1 fields keep their meaning.

### CV output additions
- `video.sampled_fps` default becomes 10 (CLI `--sample-fps` default 10). Windows are short, so precision beats speed.
- `frames[].calibration.homography`: 3x3 row-major list mapping pitch metres `[x, y, 1]` → image pixels `[u, v, w]`
  (divide by w) in FULL video resolution (`video.width` × `video.height`). `null` when `ok` is false.
- `frames[].calibration.source`: `"detected"` (keypoints+lines this frame) | `"propagated"` (carried from a neighbouring
  calibrated frame in the SAME shot via camera-motion estimation, then re-verified against painted lines). Never across cuts.
- `players[].x, y`: temporally smoothed within (shot, track). `players[].raw_x, raw_y`: the unsmoothed per-frame values.
  `players[].vx, vy`: smoothed ground velocity m/s (null if the track is too short).
- `players[].team` is a per-track majority vote over the shot (no flicker). Referees never get a team.
- `events`: auto-detected candidate moments, sorted by t:
  `[{"type": "pass", "t": 12.4, "passer_track_id": 7, "team": "A", "confidence": 0.72, "reason": "ball left #7 at 14 m/s"}]`
  `t` MUST equal a `frames[].t` (the sampled frame nearest the moment the ball was played). `events` may be `[]`.

### Backend
- Keeper rule: if the defending goalkeeper is NOT visible, assume the unseen keeper is the last defender and use the
  deepest visible outfield defender as the second-last opponent. Say so in `reasons`. Still inconclusive when |margin| <= U.
- Timing uncertainty: add `(0.5 / sampled_fps) * |vx_attacker - vx_defender|` (x = along attack) in quadrature to U
  when velocities exist; document in the formula.
- `POST /var/review {"clip","start","end"}` → one-click review of every `pass` event:
  attacking team = passer's team; direction inferred; assess every attacking player except the passer at that frame;
  key attacker = the one with the largest margin (most advanced).
  `{"reviews": [{"event": {...}, "key": <assess result>, "candidates": [{"track_id", "verdict", "margin_m"}]}], "message": str|null}`
  (message explains when there are no pass events).

### Frontend ↔ PitchScene prop contract 
`PitchScene` keeps its v1 props and adds:
- `homography` (current frame's 3x3 or null), `imageSize` `[w, h]` — used by new preset `"match"` (camera matched to the broadcast).
- `shotFrames` (calibrated frames of the current shot, sorted by t) and `time` (current video time, s) — used ONLY for
  smooth display interpolation by track_id between the two bracketing sampled frames when both exist and are ≤ 1.5 sample
  intervals apart; otherwise snap to `frame`. Never interpolate across shots. Paused exactly on a sampled frame = that frame exactly.
VarViewer passes these; PitchScene consumes them.

## AMENDMENT 3 — every "limitation" is a bug to fix (user directive). Additive.
Backend default port is now 5001 (macOS AirPlay owns 5000); frontend API_BASE default http://127.0.0.1:5001.

### Ball in 3D (cv/var_cv/ball3d.py — `apply(analysis) -> None`, pure numpy, called by analyze.py before writing)
- Recover per-frame camera (K, R, t) from `calibration.homography` (square pixels, zero skew, principal point at centre).
- Fit ballistic segments (gravity 9.81, optional drag ignored) to ball image observations within a shot, split at
  kicks/bounces/deflections; solve 3D position per frame.
- `ball.z` (metres above ground, 0 when rolling), `ball.airborne` (bool), `ball.x/y` = 3D ground-plane position of the
  ball's centre (corrected), `ball.ground_x/ground_y` = the old naive ground projection, `ball.height_uncertainty_m`.

### Identity (cv/var_cv/reid.py — `apply(analysis, video_path) -> None`, called by analyze.py before writing)
- `players[].global_id`: stable across shots within the window when the same person is matched (live-action cuts:
  pitch-position continuity + appearance; replays: appearance + team + role), else a fresh id. `track_id` stays per shot.
- Fix intra-shot identity swaps (appearance consistency); relabel the affected frames rather than leaving swaps.
- `players[].jersey_number` optional (only if read with confidence).

### Fouls / red cards (new) — IFAB Law 12
- CV: `cv/var_cv/fouls.py` CLI `python -m var_cv.fouls --analysis <window>/analysis.json --video <clip>/video.mp4 --out <window>/fouls.json`
  (pose model via ultralytics, local weights). Detect contact candidates between opponents; around each, run pose at full
  frame rate; compute: contact frame t, challenger track/global id, speed at contact, point of contact (body part, height
  above ground, above/below ankle), studs/sole-facing indicator, both-feet-off-ground lunge, off-ball strike indicator,
  plus DOGSO factors (distance to goal, direction of play, likelihood of control, number/location of defenders),
  each with confidence. Backend runs it automatically after analysis (or on demand).
- Backend: `backend/var_fouls.py` (pure law logic) + `backend/routes/var_fouls.py`:
  `POST /var/fouls {clip,start,end}` (starts/returns job) and `GET /var/fouls/<clip>?start&end` →
  `{"status", "incidents": [{"t", "players", "grounds": [{"ground": "serious_foul_play|violent_conduct|dogso",
   "verdict": "red|not_red|inconclusive", "indicators": [...], "reasons": [...]}], "sanction": "red|yellow|none|inconclusive"}]}`
  Penalty-area DOGSO with a genuine attempt to play the ball → yellow (Law 12 downgrade). Honest inconclusive.
- Frontend: self-contained `frontend/src/components/var/FoulReview.jsx` (props: clip, start, end, time, onSeek), mounted in the viewer's "Foul / red card" tab next to the offside tool.

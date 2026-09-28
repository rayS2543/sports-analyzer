# Virtual VAR — handoff

Branch `feature/virtual-var` (rebased on `main` 53ec72b). Not merged, no PR yet. Data/API contract: [`docs/virtual-var-contract.md`](docs/virtual-var-contract.md) — read it before changing any JSON shape or endpoint.

## What it is (user intent — do not narrow it)

A mini VAR built from real ESPN broadcast clips: pick a match and clip, pause on an incident, analyse a few seconds, and get an evidence-based **offside** or **foul / red-card** assessment, with lines drawn on the actual broadcast and an orbitable 3D reconstruction. Positions come from computer vision, never manual placement.

Non-negotiable honesty rules:
- The official ESPN decision is shown **separately** and never used to tune or grade the system.
- `inconclusive` is a first-class verdict; every verdict reports its uncertainty.
- Uncalibrated frames are marked, never faked. No interpolation across shot cuts.
- 3D bodies are assumed geometry (ground-plane positions only) and the UI says so.

The user's bar is "flawless": anything reported as a *limitation* is treated as a bug to fix.

## Hard constraints

- **Hardware:** fanless M2 MacBook Air (16 GB). Parallel ML jobs overheated it (kernel_task at 99%) and crashed it on 2026-09-28. Run **one** heavy CV process at a time (`var_cv.analyze` / `var_cv.fouls`), wait for `uptime` load < 20, use `nice -n 10`; thread caps (4) are already set in code.
- **Never use `/tmp`** for worktrees, venvs, weights or scratch: macOS deletes files there after 3 days unaccessed (it destroyed part of this branch once).
- **No paid APIs.** All models run locally (MPS). Roboflow hosted inference was rejected; its open `roboflow/sports` weights are used instead.
- **Ports:** backend defaults to 5001 (macOS AirPlay owns 5000). Frontend reads `VITE_API_URL`.
- Git: branch per feature, ask before committing/pushing, PR for review, never merge automatically (see `CLAUDE.md`).

## Layout

| Path | What |
|---|---|
| `cv/` | CV pipeline, **separate venv** (`cv/setup.sh` builds `.venv`, installs deps incl. `rtmlib --no-deps`, downloads ~650 MB of weights to `cv/weights/`). Not imported by Flask; the backend shells out to it. |
| `cv/var_cv/analyze.py` | CLI: download clip (ESPN CDN only) → shot cuts → pitch calibration → detection/tracking → teams → smoothing → pass events → `ball3d` → `reid` → `analysis.json` |
| `cv/var_cv/pitch.py` | Keypoint homography + painted-line refinement, lens distortion, calibration QA (`line_support`) |
| `cv/var_cv/temporal.py` | Calibration propagation within a shot, track smoothing, velocities, pass events |
| `cv/var_cv/shots.py`, `track.py`, `teams.py` | Hard-cut/dissolve detection, camera-motion-compensated tracker, kit-colour team model (`var_data/<clip>/team_model.json`) |
| `cv/var_cv/ball3d.py`, `reid.py` | Ballistic 3D ball fit from the recovered camera; appearance/position re-identification across cuts |
| `cv/var_cv/fouls.py` | CLI: contact candidates → YOLO pose + RTMPose Halpe26 (toe/heel) → Law 12 indicators → `fouls.json` |
| `backend/routes/var_clips.py` | `/var/fixtures`, `/var/clips` (ESPN discovery) |
| `backend/routes/var_analysis.py` | `/var/analyze`, `/var/analysis/<clip>`, `/var/windows/<clip>`, `/var/video/<clip>`, `/var/official`, `/var/assess`, `/var/review` |
| `backend/var_offside.py` | Pure IFAB Law 11 logic with uncertainty `U = sqrt(r² + (2·0.3)² + T²)` |
| `backend/routes/var_fouls.py`, `backend/var_fouls.py` | `/var/fouls` job + pure Law 12 logic (SFP, violent conduct, DOGSO, penalty-area downgrade) |
| `frontend/src/components/var/` | `/var` page: `VarPage` (picker, jobs, deep links), `ClipPreview`, `VarViewer`, `VideoOverlay` (lines on the broadcast), `PitchScene` (three.js), `ReviewPanel`, `VerdictCard`, `FoulReview` |
| `var_data/<clip>/<start>-<end>/` | Runtime output (gitignored): `analysis.json`, `fouls.json`, progress/error files |

## Running it

```bash
cd cv && ./setup.sh                      # once: venv + weights + cv tests
cd .. && python -m flask --app backend.app run --port 5001   # from repo root, backend venv
cd frontend && npm ci && npm run dev     # open /var
```
Checks: `python -m pytest -q` (repo root, 151 backend), `cd cv && .venv/bin/python -m pytest -q` (39), `cd frontend && npm run lint && npx vitest run && npm run build` (68).

Deep links: `/var?league=PD&date=2025-09-21&event=748191&clip=46338651&start=1.0&end=6.0` (Barça–Getafe, offside); `/var?league=PD&date=2025-04-13&event=704966&clip=44656413&start=23.0&end=28.0` (Mbappé red card, Alavés–Real Madrid).

## State (2026-09-28)

Working end to end: ESPN discovery → preview → window analysis → one-click offside review with lines on the video and broadcast-matched 3D → manual check → foul/red-card panel → separate official record.

Per-window calibration (`var_data`, calibrated / sampled at 10 fps):

| Clip / window | Calibrated | Notes |
|---|---|---|
| 46338651 1.0-6.0 | 51/51 | 1 pass event; offside test case (#23 Barça, t≈2.4) |
| 46338651 38.5-44.5 | 60/60 | lofted pass: ball peaks 4.6 ± 0.45 m |
| 46338651 61.0-66.0 | 51/51 | 2 pass events |
| 46338651 62.0-70.0 | 67/81 | live cut at 66.4 s (ID carry-over test) |
| 44656413 1.0-7.0 | 48/61 | red card, far live camera (was 0) |
| 44656413 12.0-18.0 | 55/60 | aftermath (was 0) |
| 44656413 23.0-28.0 | **0/42** | close-up replay of Mbappé's contact (t≈23.22) |
| 44656413 27.0-31.0 | **0/30** | second replay |
| 46064061 1.0-7.0 | **0/61** | Gayà red card (Osasuna–Valencia, esp.1 748159) |

Latest CV work (in the handoff commit): wide-shot calibration for 44656413, robust team model (Madrid white now its own cluster `#dadae5`), and in `fouls.py` RTMPose toes/heels, ball detection at contact, measured localisation error and a working cv2 thread cap.

Foul review on Mbappé (t=23.223): correct contact found (right foot → Blanco's shin). All grounds **inconclusive**: studs not observable (boot points along the camera axis at contact), straight-leg/lunge below the 60% reliance line, ball playability 0.30, no calibration → no speed/DOGSO. No false reds on any negative window.

## Open work — priority order (each is a bug, not a caveat)

1. **Close-up/replay calibration** (44656413 23.0-28.0 and 27.0-31.0; 46064061 1.0-7.0). Metres, speed and DOGSO are unobservable exactly where fouls are best seen. Ideas: line-only calibration with priors on focal/camera height; pooling keypoints across the shot; fitting the goal frame (7.32 × 2.44 m) or box edges. Propagating from a live frame across a cut is *not* valid.
2. **Re-run fouls** on 44656413 1.0-7.0 / 12.0-18.0 (now calibrated) and on the replays once (1) lands; report per-ground verdicts vs the official red (kept separate).
3. **Studs/sole on Mbappé:** try frames just after contact (boot rotates into view) and any other replay angle in the 65 s clip.
4. **Identity across cuts:** only 2/~18 people kept their ID over the 66.4 s cut in 46338651 62.0-70.0. Suppress duplicate boxes (cross-class NMS + merge near-coincident tracks), then re-measure.
5. **ball3d:** bounces < ~1 m after a landing read as rolling; drag ignored for hard-hit balls.
6. **Final end-to-end browser pass** on both deep links (desktop + mobile), then open the PR.

Performance: a 5 s window takes ~40–90 s on the Air when it is the only job; foul review 20 s – 6 min per window.

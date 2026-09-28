# Virtual VAR: CV pipeline (analysis.json v2)

This takes a window of 10 s or less from an ESPN highlight clip and returns, per sampled frame (10 fps):
- a verified camera calibration (pitch↔image homography) with a per-point error estimate;
- players, referees and goalkeepers on the pitch in metres, with smoothed velocity;
- the ball;
- candidate pass events.

It runs locally (no hosted APIs, no keys). The Flask backend runs it as a subprocess and never imports it.

## Setup and run

```bash
cd cv && ./setup.sh     # venv (python3; PYTHON=... to override), deps, ~400 MB weights, tests
.venv/bin/python -m var_cv.analyze --clip-id 46338651 --source-url <https ESPN mp4> \
    --video ../var_data/46338651/video.mp4 --start 61.0 --end 66.0 \
    --out ../var_data/46338651/61.0-66.0 --venue "Estadi Johan Cruyff"
```

- **Download:** it downloads `--video` if missing, and only from `https://espnmedia-cdn.akamaized.net/...mp4`.
- **Decoding:** it decodes only the window. Models run at `--sample-fps` (default 10), and cut detection runs on every frame.
- **Pitch size:** `--venue` looks up the real pitch size in `VENUES` (analyze.py). `--pitch-length` and `--pitch-width` override it. An unknown venue falls back to 105 × 68 m, and `pitch.source` says it is unverified.
- **Output:** `progress.json` while running, then `analysis.json` (written atomically). On failure it writes `error.json` and exits 1.
- **Post-processors:** `ball3d.apply(analysis)` and then `reid.apply(analysis, video)` run just before the write, when those modules exist. Their status is in `pipeline.hooks`.
- **Timing:** per-stage times are in `pipeline.timings_s`, together with the 1-minute load average.
- **Tests:** `.venv/bin/python -m pytest` uses synthetic data only.

## How it works

1. **Shots.** Colour-histogram cuts, plus a 0.25 s window for dissolves. Frames inside a transition belong to no shot. Nothing is ever tracked, propagated or smoothed across a cut.
2. **Detected calibration**, per sampled frame:
   - Pitch keypoints are fitted with RANSAC.
   - The fit is then refined as a chamfer fit to the painted-line **centrelines** (the skeleton of bright, thin pixels on grass).
   - The grass/ad-board boundary cannot pull lines, and anything off-grass counts as "no line".
   - A frame is accepted only when the painted lines back it up:
     - at least 50% of in-view model lines lie within 3 px of a painted line;
     - every interior line spanning 150 px or more has at least 30% support;
     - the line residual is 1 m or less;
     - the camera is not mirrored.
3. **Calibration propagation.** This happens inside a shot only.
   - Camera motion between samples is one homography, since a broadcast camera pans, tilts and zooms about a fixed centre. It comes from sparse optical flow off the player boxes, forward-backward checked and RANSAC-fitted.
   - The homography of a calibrated neighbour is chained through the motion, then re-refined and re-verified on this frame's lines with the same checks. The frame is marked `source: "propagated"`. A chain may bridge up to 6 unverifiable frames.
   - Frames whose own keypoints are too few use keypoints pooled from up to 6 neighbouring frames, mapped through the camera motion. The fit is then verified the same way.
4. **Uncertainty.** The homography's parameter covariance comes from the line fit. It is inflated because residuals along one line are correlated (one observation per 40 px of line, not per sample). It is then propagated to any image point, plus the line-localisation noise there.
   - `players[].position_uncertainty_m` is the result at the foot point.
   - `calibration.reprojection_error_m` is the largest 1σ over all the visible grass in the frame. It is conservative and dominated by the frame edges and far side.
   - `calibration.line_fit_residual_m` is the RMS residual on the matched lines, the v1 meaning.
5. **Detection.**
   - The roboflow player model gives players, goalkeepers, referees and the ball. The dedicated ball model runs only when the player model finds no ball.
   - Duplicate boxes are removed per frame, by cross-class NMS at 0.45 and a containment rule.
6. **Tracking.** Boxes are matched by foot position after warping the previous positions through the camera motion (Hungarian algorithm, gated by box height).
   - Within a shot, duplicate tracks are merged: two tracks that overlap or stand less than 0.6 m apart in at least 60% of shared frames, with the same team.
   - A track fragment is relinked when it starts within 4 samples of another track ending and is less than 3 m away at a physically possible speed.
7. **Teams and roles.**
   - Jersey colour is clustered with 2-means in Lab, on this window only. `team` is a per-track majority vote over the shot.
   - A kit far from both team colours (more than 3 times the typical within-kit spread) is a goalkeeper if the track stays near a goal, otherwise a match official.
   - Goalkeepers join the team whose outfield block they sit behind. Referees never get a team.
   - Per frame, at most 11 per team: same-team boxes less than 0.5 m apart are merged, and the surplus with the weakest team evidence gets `team: null`.
8. **Smoothing.** A local weighted quadratic (tricube kernel, ±0.35 s) per (shot, track) gives `x`/`y`, keeps `raw_x`/`raw_y`, and gives `vx`/`vy` in m/s. Velocity needs 3 or more samples over at least 0.2 s. Speeds over 12 m/s are treated as tracking glitches and output as null.
9. **Pass events.**
   - Possession means the nearest team player is within 1.5 m of the ball on calibrated frames. Isolated ball jumps over 40 m/s are dropped.
   - A pass is when the passer loses the ball and it travels at least 5 m at 4–40 m/s to another player. With no receiver in view, the ball must keep moving away from the passer.
   - `t` is the last sampled frame on which the passer had the ball.
   - `confidence` combines possession clarity, ball detection confidence, calibration source and receiver (same team 1.0, interception 0.7, none 0.5), capped at 0.9.
   - An airborne ball (from ball3d) is not used for possession.

## Pitch size

Barcelona v Getafe (21 Sep 2025) was played at the Estadi Johan Cruyff (ESPN event 748191). Its field size is 105 m × 68 m ([Wikipedia infobox](https://en.wikipedia.org/wiki/Johan_Cruyff_Stadium)), and `pitch.source` records this. For other venues, add them to `VENUES` or pass `--pitch-length`/`--pitch-width`.

## Lens distortion

One radial term k1 was tested, fitted jointly with the homography on 51 real frames. It came out at a median of 0.006 and changed line support by about 0.02, so it is not modelled. Edge-of-frame error is handled by the per-point uncertainty instead: points far from the constraining lines report a larger `position_uncertainty_m`.

## What remains uncalibrated, and why

Calibration always needs painted-line evidence in the frame. Frames with genuinely no pitch geometry stay `ok: false`, and `calibration.failure` says why. The categories are:
- **Close-ups, crowd and bench shots:** no pitch lines in the frame.
- **Frames inside dissolves or wipes:** excluded from every shot.
- **Shots where no frame yields at least 4 landmarks,** even when pooled over neighbouring frames, so there is nothing to propagate from.
- **Goal-end or low angles where the keypoint model mislabels landmarks** and the painted lines contradict every fit. These are rejected, not faked.

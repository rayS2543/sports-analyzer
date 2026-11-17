PASS
PASS on the stated criteria (45/52 half samples verified, 98.1% seed+propagate coverage, one named gap). End identity is now consistent across the half by chain consistency; one global bit per match still needs an outside cue (below).

# LINEFIT REPORT
Artifacts: `footage-test/linefit/` (seeder.py, run_samples.py, coverage.py, grade.py, worklog.md, results_samples.json, results_molina.json, coverage_intervals.json, coverage_summary.json, grade.json, H/ per-seed homographies, overlays/). Nothing tracked was changed in any checkout, no commits or pushes.

## Method as built (seeder.py)
No learned model, no human input. Judge: the branch's unmodified `pitch.passes` on `pitch.refine`; every found seed is also run through `temporal._verify` (recorded, 1 seed of 635 failed it, see failures).
1. `pitch.line_mask` -> LSD segments (len >= 55 px) -> near-horizontal segments chained into clusters (v tol 25 px). Same as LINEFIT_POC.
2. **v1 (POC read, hardened):** enumerate (goal, six, box) triples ordered structurally; goal may be missing; corners from pooled steep side lines; DLT; `pitch.refine`; gate. All of as-is, y-flip, x-flip, 180 rotation run, lowest error_m among passers wins.
3. **v2 (added, runs only when v1 finds nothing):** generic discrete enumeration. Up to 7 clusters (len >= 150) are assigned monotonically (both directions) to pitch x-lines of either half {0, 5.5, 16.5, 52.5} or {52.5, 88.5, 99.5, 105}; full-width lines (goal, halfway) take corners from the two pooled touchlines, box/six fronts from pooled sides. Each candidate is DLT'd and ranked by a cheap chamfer to the line mask; only the top 10 go through `pitch.refine` + gate. This is what handles midfield framings and the far-end box. The chamfer is only a ranking, never a judge (continuous pose search was not used, per the brief's lesson).
Reimplemented propagation (coverage.py) follows relaunch/half1.py: LK at stride 2 on 960x540, refine+gate on the 4 prior anchors every 150 frames, retry of last verified H every 15 frames after loss, drift fallback. Run forward from each seed and backward from the next one; seeds count as verified checkpoints. Relaunch's coverage definition used (spans between verified checkpoints <= 30 s).

## Results
- **Half samples (every 60 s, 612-3672 s): 45 / 52 verified (86.5%).** v1 alone: 19/52. 26 of the 45 needed v2.
- **Molina window (2640-2650 s, every source frame): 590 / 601 verified (98.2%).** v1 alone: 536. Unverified: 2645.87-2645.92 s (4 frames) and 2648.47-2648.78 s (7 frames). The POC frame 158678 (2644.63 s) is seeded.
- **Coverage, machine seeds only, first half (612-3690 s): 3018 of 3078 s = 98.05%** between verified checkpoints <= 30 s apart; 1208 verified checkpoints (45 seeds). **One gap: 3287.5-3347.5 s (60 s).** No LK tracking losses in any interval. Relaunch with hand seeds: 98.2% and gap 3287.5-3342.5; same region.
- Denominator is the whole half, not live play, as in the relaunch.

## Per-frame table (half samples)
Verification stats are the branch's, verbatim from results_samples.json. Last column is the grader-side distance to the relaunch's hand-seeded verified homography, minimum over the symmetry group (best symmetry in brackets), computed after results were saved; never seeder input.

| video s | seed | candidate | support | worst | error_m | uncertainty_m | secs | grader dist m |
|---|---|---|---|---|---|---|---|---|
| 612 | yes | v2 y-flip | 0.951 | 0.716 | 0.136 | 0.177 | 6.24 | n/a |
| 672 | yes | v1 x-flip | 0.955 | 0.952 | 0.090 | 0.152 | 0.63 | 0.79 (rot180) |
| 732 | yes | v1 x-flip | 0.959 | 0.986 | 0.084 | 0.135 | 1.17 | 0.24 (rot180) |
| 792 | yes | v2 y-flip | 0.984 | 1.000 | 0.105 | 0.156 | 7.57 | 0.16 (id) |
| 852 | yes | v1 x-flip | 0.942 | 0.919 | 0.098 | 0.184 | 1.68 | 0.32 (rot180) |
| 912 | yes | v1 y-flip | 0.969 | 0.978 | 0.082 | 0.158 | 1.65 | 0.15 (id) |
| 972 | yes | v2 as-is | 0.977 | 1.000 | 0.116 | 0.176 | 4.57 | 0.38 (rot180) |
| 1032 | yes | v2 as-is | 0.959 | 0.824 | 0.133 | 0.175 | 5.87 | 0.17 (rot180) |
| 1092 | yes | v2 as-is | 0.908 | 0.429 | 0.141 | 0.212 | 7.81 | 0.38 (rot180) |
| 1152 | yes | v1 y-flip | 0.984 | 1.000 | 0.085 | 0.131 | 1.56 | 0.17 (id) |
| 1212 | yes | v1 x-flip | 0.988 | 1.000 | 0.091 | 0.163 | 1.05 | 0.17 (rot180) |
| 1272 | yes | v2 as-is | 0.986 | 0.970 | 0.103 | 0.172 | 10.61 | 0.08 (rot180) |
| 1332 | yes | v1 x-flip | 0.966 | 0.954 | 0.079 | 0.153 | 1.15 | 0.33 (rot180) |
| 1392 | yes | v2 as-is | 0.988 | 1.000 | 0.110 | 0.164 | 7.58 | 0.20 (rot180) |
| 1452 | NO | tried 10 | | | | | 6.62 | |
| 1512 | yes | v2 y-flip | 0.851 | 0.733 | 0.149 | 0.233 | 5.62 | 0.46 (id) |
| 1572 | yes | v1 y-flip | 0.970 | 0.979 | 0.080 | 0.153 | 1.03 | 0.21 (id) |
| 1632 | yes | v2 as-is | 0.956 | 0.952 | 0.093 | 0.158 | 5.26 | 0.40 (rot180) |
| 1692 | yes | v2 y-flip | 0.988 | 1.000 | 0.118 | 0.167 | 15.54 | 0.82 (id) |
| 1752 | yes | v2 as-is | 0.974 | 1.000 | 0.123 | 0.174 | 8.46 | 0.45 (rot180) |
| 1812 | yes | v2 as-is | 0.972 | 0.893 | 0.110 | 0.178 | 9.74 | 0.33 (rot180) |
| 1872 | yes | v2 as-is | 0.970 | 0.786 | 0.109 | 0.182 | 6.21 | 0.16 (rot180) |
| 1932 | yes | v1 x-flip | 0.966 | 0.908 | 0.102 | 0.176 | 1.06 | 0.29 (rot180) |
| 1992 | yes | v2 y-flip | 0.941 | 1.000 | 0.129 | 0.194 | 7.24 | 0.43 (id) |
| 2052 | yes | v2 y-flip | 0.942 | 0.910 | 0.127 | 0.194 | 4.55 | 0.30 (id) |
| 2112 | yes | v1 y-flip | 0.962 | 0.913 | 0.104 | 0.167 | 1.1 | 0.25 (id) |
| 2172 | yes | v1 y-flip | 0.925 | 0.974 | 0.095 | 0.161 | 0.78 | 0.02 (id) |
| 2232 | yes | v2 as-is | 0.982 | 1.000 | 0.109 | 0.162 | 5.65 | 0.32 (rot180) |
| 2292 | yes | v2 y-flip | 0.971 | 0.932 | 0.132 | 0.174 | 7.97 | 0.51 (id) |
| 2352 | NO | tried 0 | | | | | 0.43 | |
| 2412 | yes | v1 x-flip | 0.925 | 0.959 | 0.089 | 0.137 | 0.7 | 0.21 (rot180) |
| 2472 | yes | v2 y-flip | 0.984 | 0.973 | 0.114 | 0.159 | 12.72 | 0.47 (id) |
| 2532 | yes | v1 x-flip | 0.942 | 0.928 | 0.094 | 0.161 | 0.58 | 0.18 (rot180) |
| 2592 | yes | v1 x-flip | 0.924 | 0.926 | 0.089 | 0.165 | 0.84 | 0.13 (rot180) |
| 2652 | yes | v1 y-flip | 0.935 | 0.790 | 0.099 | 0.148 | 0.72 | 0.19 (id) |
| 2712 | yes | v1 x-flip | 0.962 | 1.000 | 0.083 | 0.134 | 0.72 | 0.10 (rot180) |
| 2772 | yes | v2 y-flip | 0.987 | 1.000 | 0.103 | 0.167 | 10.81 | 0.05 (id) |
| 2832 | yes | v2 as-is | 0.987 | 1.000 | 0.103 | 0.168 | 9.39 | 0.03 (rot180) |
| 2892 | yes | v2 as-is | 0.987 | 1.000 | 0.104 | 0.168 | 13.98 | 0.13 (rot180) |
| 2952 | NO | tried 22 | | | | | 8.99 | |
| 3012 | yes | v2 as-is | 0.780 | 0.607 | 0.187 | 0.247 | 5.54 | 0.18 (rot180) |
| 3072 | NO | tried 10 | | | | | 4.87 | |
| 3132 | yes | v1 y-flip | 0.980 | 0.990 | 0.089 | 0.158 | 0.73 | 0.11 (id) |
| 3192 | NO | tried 10 | | | | | 0.71 | |
| 3252 | NO | tried 10 | | | | | 1.86 | |
| 3312 | NO | tried 10 | | | | | 9.39 | |
| 3372 | yes | v1 x-flip | 0.951 | 0.975 | 0.082 | 0.150 | 0.89 | 0.30 (rot180) |
| 3432 | yes | v2 as-is | 0.951 | 0.980 | 0.090 | 0.165 | 4.4 | 0.17 (rot180) |
| 3492 | yes | v1 x-flip | 0.947 | 0.966 | 0.078 | 0.150 | 0.93 | 0.37 (rot180) |
| 3552 | yes | v2 y-flip | 0.939 | 0.393 | 0.140 | 0.184 | 5.09 | 1.45 (id) |
| 3612 | yes | v2 y-flip | 0.937 | 0.976 | 0.133 | 0.179 | 6.69 | 1.19 (id) |
| 3672 | yes | v2 as-is | 0.974 | 1.000 | 0.130 | 0.163 | 6.02 | 1.52 (rot180) |

Molina per-frame records: `results_molina.json` (same fields).

## Accuracy (grader-side, hand-verified reference, not seeder input)
- Half samples: 44 graded (reference verified within 75 frames), median 0.24 m, p90 0.70 m, max 1.52 m. Three above 1 m: 3552, 3612, 3672 s. Not determined whether the seed or the late-half reference is the less accurate there.
- Molina: 295 graded frames, median 0.09 m, max 0.42 m.
- Best symmetry was identity for 17/44 half samples and 180 rotation for 27/44; never a mirror.

## End identity (180 degree ambiguity): fixed except for one bit
The painted lines are symmetric, so the gate accepts a seed and its 180 degree rotation; raw seeds came out arbitrarily labelled (25 of 44 consecutive-seed links disagreed).
Fix as built (`orient.py`, `densify.py`, `orient_molina.py`; outputs `orient.json`, `H_resolved/`, `grade_resolved.json`):
1. Chain consistency: the propagated H from seed A, evaluated at seed B's frame, agrees with B either as-is or after a 180 rotation (median distance gap 270x); flip B accordingly, cumulatively along the half. Machine-only.
2. Weak links (neither labelling within 2 m, or margin ratio < 5; the camera-swing stretch 3012-3372 s) are densified: 34 extra seeds every 10 s there, 15 found, then re-propagated. Coverage with them: 60 seeds, 3030.5 of 3078 s = 98.46%, gap 3265.0-3312.5 s.
3. Molina window: anchored to the resolved 2652 s seed by a 2 s LK chain (anchor distance 0.19 m vs 95.9 m), then walked frame to frame.
Result, grader-side against the hand-verified reference: all 57 graded half samples and all 295 graded Molina frames have the SAME labelling (best symmetry = identity; before: 17 id / 27 rot180 of 44).
Remaining limits:
- **One bit per match** is not in the lines (which end is x=105). The identity labelling matching the reference is the anchor I passed (0); that it matched is a coin flip, not a detected cue. Needs one outside cue per match (scoreboard side, keeper kit, kickoff). Not built.
- Three links stay weak after densifying (3042-3092, 3182-3262, 3262-3352 s; both labellings far from the chain, 6-67 m, margin 1.8-5.4). They resolved to the right label here (checked grader-side) but the machine had no clear evidence; treat labels in 3042-3092 and 3182-3352 s as unverified by chain. Seeds are missing across 3052-3082, 3192-3252 and 3272-3342 s.

## Failure modes (counted)
- Half samples failed: 7 of 52: 1452, 2352, 2952, 3072, 3192, 3252, 3312 s. 3192-3312 sits in the same stretch where the relaunch's hand seed also failed (wide oblique framing at the free kick); I did not inspect 2352, 2952, 3072. At 1452 s (midfield framing) v2 refined 10 candidates and none passed; cause not diagnosed.
- Molina: 11 of 601 failed (causes not inspected).
- 1 found seed passes `pitch.passes` but not `temporal._verify`.
- Seeds accepted by the gate on line support only; a gate pass is not absolute accuracy (see grader numbers).

## Cost per match (wall, fanless Air, nice 10, other work running)
- Seeding: about 5 s per sampled frame (mean 4.9 s over the 52 samples; 0.6-15 s depending on whether v2 runs); 52 samples about 4 min. Molina window 601 frames about 30 min (3.0 s mean).
- Propagation between seeds, both directions: about 64 min for the half (45 intervals). Estimated full match 2 h or more.
- Hand labelling cost removed: no human landmark seeds at all. Remaining human input: the one global end-identity bit.

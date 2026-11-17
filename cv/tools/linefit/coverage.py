"""Seed-and-propagate coverage of H1 (612-3690 s) from MACHINE seeds only (results_samples.json).
Propagation = the relaunch's (relaunch/half1.py): LK on 960x540 gray at stride 2, refine+unmodified gate on 4 prior anchors every 150 frames,
recovery by retrying the last verified H every 15 frames after tracking loss, drift fallback to last verified H. Run both directions
between consecutive seeds (forward from A, backward from B) so each seed covers its side. Resumable per interval. usage: coverage.py"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder, cv2, numpy as np
pitch = seeder.pitch
L = os.path.dirname(os.path.abspath(__file__)); V = seeder.B + "/footage-test/argentina_netherlands_tactical.mp4"
FPS, STEP, CK, F0, F1 = 60, 2, 150, 612 * 60, 3690 * 60
A = np.array([[288, 378], [1632, 378], [1632, 972], [288, 972]], float)
gray = lambda f: cv2.cvtColor(cv2.resize(f, (960, 540)), cv2.COLOR_BGR2GRAY)


def step(a, b, H):
    mask = np.full(a.shape, 255, np.uint8)
    p = cv2.goodFeaturesToTrack(a, 500, .01, 10, mask=mask, blockSize=7)
    if p is None or len(p) < 8: return None
    q, s, _ = cv2.calcOpticalFlowPyrLK(a, b, p, None, winSize=(21, 21), maxLevel=3)
    z, t, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, winSize=(21, 21), maxLevel=3)
    g = (s[:, 0] > 0) & (t[:, 0] > 0) & (np.linalg.norm((p - z)[:, 0, :], axis=1) < 1)
    if g.sum() < 8: return None
    M, ins = cv2.findHomography(p[g] * 2, q[g] * 2, cv2.RANSAC, 2.5)
    if M is None or ins is None or ins.sum() < 8: return None
    return H @ np.linalg.inv(M)


def gate(H, f):
    r = pitch.refine(H, pitch.line_mask(f), A, pitch.project(H, A))
    return r["H"], dict({k: float(r[k]) for k in ("support", "worst", "error_m", "uncertainty_m")}, verified=bool(pitch.passes(r)))


def walk(frames, grays, H0, seedn):
    """frames: ordered processed frame numbers after the seed; returns checkpoint list + final propagated H"""
    H, vH, gap, cks, prev = H0.copy(), H0.copy(), None, [], grays[seedn]
    last = None
    for n in frames:
        cur = grays[n]
        if gap is None:
            Hn = step(prev, cur, H)
            if Hn is None: gap = n; cks.append(dict(frame=n, event="gap_start")); H = None
            else: H = Hn
        prev = cur
        if gap is not None:
            if n % 15 == 0 and n in fulls:
                Hr, v = gate(vH, fulls[n])
                if v["verified"]: H = vH = Hr; cks.append(dict(frame=n, event="gap_end", verification=v)); gap = None
            continue
        last = H
        if n % CK == 0:
            Hr, v = gate(H, fulls[n]); ck = dict(frame=n, event="checkpoint", verification=v)
            if v["verified"]: H = vH = Hr
            else:
                Hr2, v2 = gate(vH, fulls[n])
                if v2["verified"]: H = vH = Hr2; ck["recovered_from_last_verified"] = v2
            cks.append(ck)
    return cks, last


allres = json.load(open(L + "/results_samples.json"))
if os.path.exists(L + "/results_extra.json"): allres.update(json.load(open(L + "/results_extra.json")))  # densified seeds (densify.py)
seeds = {int(k): v for k, v in allres.items() if v["found"]}
sn = sorted(seeds)
Hs = {n: np.load(f"{L}/H/{n}.npy") for n in sn}
pts = [F0] + [n for n in sn if F0 < n < F1] + [F1]
out_p = L + "/coverage_intervals.json"
done = json.load(open(out_p)) if os.path.exists(out_p) else {}
cap = cv2.VideoCapture(V)
grid = np.array([[u, v] for u in np.linspace(0.1, 0.9, 5) * 1920 for v in np.linspace(0.4, 0.9, 3) * 1080])
R = lambda p: np.c_[105 - p[:, 0], 68 - p[:, 1]]
for a, b in zip(pts[:-1], pts[1:]):
    key = f"{a}-{b}"
    if key in done: continue
    lo, hi = max(a, F0), min(b, F1)
    # decode [lo, hi] once at stride 2 (gray always, full frame only at checkpoint/recovery frames)
    cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
    grays, fulls = {}, {}
    for n in range(lo, hi + 1):
        ok, f = cap.read()
        if not ok: break
        if (n - lo) % STEP == 0:
            grays[n] = gray(f)
            if n % 15 == 0: fulls[n] = f
    iv = {"a": a, "b": b, "fwd": None, "bwd": None}
    allf = sorted(grays)
    if a in Hs and a in grays:
        iv["fwd"], last = walk([n for n in allf if n > a], grays, Hs[a], a)
        if b in Hs and last is not None:  # orientation consistency of the chain with seed B (180 deg ambiguity of lines)
            pa, pb = pitch.project(last, grid), pitch.project(Hs[b], grid)
            iv["orient_dist_m"] = dict(same=float(np.nanmean(np.linalg.norm(pa - pb, axis=1))), rot180=float(np.nanmean(np.linalg.norm(pa - R(pb), axis=1))))
    if b in Hs and b in grays:
        iv["bwd"], _ = walk([n for n in allf[::-1] if n < b], grays, Hs[b], b)
    done[key] = iv; json.dump(done, open(out_p, "w")); print(key, flush=True)
    del grays, fulls
# coverage (only intervals of the current seed set)
done = {k: v for k, v in done.items() if k in {f"{a}-{b}" for a, b in zip(pts[:-1], pts[1:])}}
ver = {n: "seed" for n in sn}
for iv in done.values():
    for d in ("fwd", "bwd"):
        for c in (iv[d] or []):
            if c.get("verification", {}).get("verified") or c.get("recovered_from_last_verified"): ver[c["frame"]] = d
vt = sorted(set([n / FPS for n in ver]))
cov, gaps = 0.0, []
edges = [F0 / FPS] + [t for t in vt if F0 / FPS <= t <= F1 / FPS] + [F1 / FPS]
for x, y in zip(edges[:-1], edges[1:]):
    if y - x <= 30: cov += y - x
    else: gaps.append([x, y])
summary = dict(half_s=(F1 - F0) / FPS, covered_s=cov, covered_pct=100 * cov / ((F1 - F0) / FPS), verified_checkpoints=len(vt), seeds=len(sn), gaps_gt30s=gaps,
               orient_conflicts=[k for k, v in done.items() if "orient_dist_m" in v and v["orient_dist_m"]["rot180"] < v["orient_dist_m"]["same"]],
               orient_checked=sum("orient_dist_m" in v for v in done.values()))
json.dump(summary, open(L + "/coverage_summary.json", "w"), indent=1); print(json.dumps(summary, indent=1))

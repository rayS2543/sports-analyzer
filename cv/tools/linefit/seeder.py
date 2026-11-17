"""Line-fit auto-seeder: painted-line mask -> LSD -> structural cluster reads -> corners -> DLT -> branch refine -> branch gate.
No learned model, no human input. Judge = unmodified pitch.passes (+ temporal._verify). Hardened from LINEFIT_POC.py."""
import sys, itertools, time
import numpy as np, cv2
cv2.setNumThreads(2)
B = "/Users/raysiguen/Desktop/Personal Projects/virtual-var-revival"
sys.path.insert(0, B + "/sports-analyzer-test/cv")
from var_cv import pitch, temporal

# pitch x of the three structural lines at the end where goal line is x=105 (the "near" end)
GOAL_X, SIX_X, BOX_X, SIX_HW, BOX_HW = 105.0, 99.5, 88.5, 9.16, 20.16


def _fit(ss):
    return cv2.fitLine(np.vstack([ss[:, :2], ss[:, 2:]]).astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()


def _isect(l1, l2):
    A = np.array([[l1[0], -l2[0]], [l1[1], -l2[1]]], float)
    if abs(np.linalg.det(A)) < 1e-9:
        return None
    t = np.linalg.solve(A, np.array([l2[2] - l1[2], l2[3] - l1[3]], float))
    p = np.array([l1[2] + t[0] * l1[0], l1[3] + t[0] * l1[1]])
    return p if np.all(np.isfinite(p)) and np.abs(p).max() < 20000 else None


def segments(mask):
    segs, *_ = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(mask)
    if segs is None:
        return np.zeros((0, 4))
    s = segs.reshape(-1, 4).astype(np.float64)
    return s[np.hypot(s[:, 2] - s[:, 0], s[:, 3] - s[:, 1]) >= 55]


def hclusters(segs, vtol=25):
    ang = np.degrees(np.arctan2(np.abs(segs[:, 3] - segs[:, 1]), np.abs(segs[:, 2] - segs[:, 0])))
    hor = segs[ang < 7]
    merged = []
    for i in np.argsort((hor[:, 1] + hor[:, 3]) / 2):
        s = hor[i]; v = (s[1] + s[3]) / 2; ln = np.hypot(s[2] - s[0], s[3] - s[1])
        c = dict(v=v, len=ln, segs=[s], u0=min(s[0], s[2]), u1=max(s[0], s[2]))
        for m in merged:
            if abs(c["v"] - m["v"]) < vtol and c["u0"] < m["u1"] + 60 and m["u0"] < c["u1"] + 60:
                m["segs"] += c["segs"]; m["v"] = (m["v"] * m["len"] + v * ln) / (m["len"] + ln); m["len"] += ln
                m["u0"], m["u1"] = min(m["u0"], c["u0"]), max(m["u1"], c["u1"]); break
        else:
            merged.append(c)
    for m in merged:
        m["line"] = _fit(np.array(m["segs"])); m["w"] = m["u1"] - m["u0"]
    return merged


def pooled_side(segs, front, back_v, u_c, half_win=170):
    """steep fragments near u_c between the front line and back_v (goal line, or a lower bound), pooled to one line"""
    a = np.degrees(np.arctan2(np.abs(segs[:, 3] - segs[:, 1]), np.abs(segs[:, 2] - segs[:, 0])))
    mx, my = (segs[:, 0] + segs[:, 2]) / 2, (segs[:, 1] + segs[:, 3]) / 2
    k = (a >= 28) & (np.abs(mx - u_c) < half_win) & (my > front["v"] - 60) & (my < back_v + 10)
    return _fit(segs[k]) if k.any() else None


def triples(longs, max_n=8):
    """(goal, six, box) assignments, structural read first. goal may be None (near box's goal line out of view)."""
    out = []
    for g in sorted(longs, key=lambda c: -c["v"])[:3] + [None]:
        gv = g["v"] if g else 1e9
        above = [c for c in longs if c is not g and c["v"] < gv - 80]
        for six in sorted(above, key=lambda c: c["w"]):
            if g is None and six["v"] < 200:  # no goal: allow any, ranked later
                pass
            for box in sorted((c for c in above if c is not six and 60 < six["v"] - c["v"] < 400), key=lambda c: -c["len"]):
                if box["w"] > six["w"]:
                    out.append((g, six, box))
    # structural order: real goal first (bottom-most), narrowest six, longest box
    out.sort(key=lambda t: (t[0] is None, -(t[0]["v"] if t[0] else 0), t[1]["w"], -t[2]["len"]))
    return out[:max_n]


def correspondences(segs, g, six, box):
    ip, pp = [], []
    def add(p, q):
        if p is not None:
            ip.append(p); pp.append(q)
    for front, fx, hw, tag in ((box, BOX_X, BOX_HW, "box"), (six, SIX_X, SIX_HW, "six")):
        for sgn, u_c in ((-1, front["u0"]), (1, front["u1"])):
            side = pooled_side(segs, front, g["v"] if g else front["v"] + 260, u_c)
            if side is None:
                continue
            add(_isect(front["line"], side), (fx, 34 + sgn * hw))
            if tag == "box" and g:
                add(_isect(g["line"], side), (GOAL_X, 34 + sgn * hw))
    return np.array(ip, float), np.array(pp, float)


def variants(pp):
    """handedness (y-flip) and which end (x-flip = 180 deg), all run; gate decides"""
    for name, fx, fy in (("as-is", 0, 0), ("y-flip", 0, 1), ("other-end", 1, 1), ("x-flip", 1, 0)):
        q = pp.copy()
        if fx: q[:, 0] = 105.0 - q[:, 0]
        if fy: q[:, 1] = 68.0 - q[:, 1]
        yield name, q


XL = [0.0, 5.5, 16.5, 52.5, 88.5, 99.5, 105.0]
FULLX = (0.0, 52.5, 105.0)
HW = {5.5: SIX_HW, 99.5: SIX_HW, 16.5: BOX_HW, 88.5: BOX_HW}


def touchlines(segs, W):
    """longest steep line in each image half, pooled with collinear steep fragments"""
    a = np.degrees(np.arctan2(np.abs(segs[:, 3] - segs[:, 1]), np.abs(segs[:, 2] - segs[:, 0])))
    st = segs[a >= 28]
    out = []
    for half in (0, 1):
        mx = (st[:, 0] + st[:, 2]) / 2
        c = st[(mx < W / 2) if half == 0 else (mx >= W / 2)]
        if not len(c):
            out.append(None); continue
        L = np.hypot(c[:, 2] - c[:, 0], c[:, 3] - c[:, 1])
        s0 = c[np.argmax(L)]
        d = (s0[2:] - s0[:2]) / np.hypot(*(s0[2:] - s0[:2]))
        nrm = np.array([-d[1], d[0]])
        pool = [s for s in c if max(abs((s[:2] - s0[:2]) @ nrm), abs((s[2:] - s0[:2]) @ nrm)) < 12]
        ps = np.array(pool)
        out.append(_fit(ps) if np.hypot(*(ps[:, 2:] - ps[:, :2]).T).sum() >= 300 else None)
    return out


def v2_candidates(segs, cl, shape, masks):
    """generic discrete enumeration: monotone assignment of horizontal clusters to pitch x-lines (both ends, both directions)"""
    H_, W_ = shape[:2]
    cs = sorted(sorted([c for c in cl if c["len"] >= 150], key=lambda c: -c["len"])[:7], key=lambda c: c["v"])
    tl = touchlines(segs, W_)
    dt = cv2.distanceTransform(255 - masks[0], cv2.DIST_L2, 3)
    out = []
    for k in (2, 3, 4):
        for sub in itertools.combinations(cs, k):
            for grp in (XL[:4], XL[3:]):
                for xs in itertools.combinations(grp, k):
                    for xs_ in (xs, xs[::-1]):  # image far->near order maps to increasing or decreasing x
                        ip, pp = [], []
                        for c, x in zip(sub, xs_):
                            if x in FULLX:
                                for tli, y in ((tl[0], 0.0), (tl[1], 68.0)):
                                    p = _isect(c["line"], tli) if tli is not None else None
                                    if p is not None and -200 < p[0] < W_ + 200 and abs(p[1] - c["v"]) < 150:
                                        ip.append(p); pp.append((x, y))
                            else:
                                gx = [v for v in FULLX if abs(v - x) < 20]
                                gv = [cc["v"] for cc, xx in zip(sub, xs_) if xx in gx]
                                for sgn, u_c in ((-1, c["u0"]), (1, c["u1"])):
                                    sd = pooled_side(segs, c, gv[0] if gv else c["v"] + 0.5 * c["w"], u_c)
                                    p = _isect(c["line"], sd) if sd is not None else None
                                    if p is not None:
                                        ip.append(p); pp.append((x, 34 + sgn * HW[x]))
                        if len(ip) < 4:
                            continue
                        ip, pp = np.array(ip, float), np.array(pp, float)
                        for vn in ("as-is", "y-flip"):
                            q = pp.copy()
                            if vn == "y-flip": q[:, 1] = 68.0 - q[:, 1]
                            H0 = cv2.findHomography(ip, q, 0)[0]
                            if H0 is None: continue
                            try:
                                G0 = np.linalg.inv(H0)
                                img, ok = pitch._in_view(G0, masks[0].shape)
                            except Exception:
                                continue
                            if ok.sum() < 300 or not pitch.orientation_ok(H0, masks[0].shape): continue
                            q_ = img[ok].astype(int)
                            sc = float(np.minimum(dt[np.clip(q_[:, 1], 0, H_ - 1), np.clip(q_[:, 0], 0, W_ - 1)], 20).mean())
                            out.append((sc, ip, q, dict(variant=vn, k=k, xs=[float(x) for x in xs_])))
    out.sort(key=lambda t: t[0])
    return out


def seed(frame, max_triples=8, v2_top=10):
    """-> dict(found, H, verification, ...). found only when the branch's unmodified gate accepts."""
    t0 = time.time()
    masks = pitch.line_mask(frame)
    segs = segments(masks[0])
    cl = hclusters(segs) if len(segs) else []
    longs = [c for c in cl if c["len"] > 500]
    res = dict(found=False, n_clusters=len(cl), n_long=len(longs), tried=0, best=None)
    best = None
    for ti, (g, six, box) in enumerate(triples(longs, max_triples)):
        ip, pp = correspondences(segs, g, six, box)
        if len(ip) < 4:
            continue
        for vn, q in variants(pp):
            try:
                H0, _, _ = pitch.calibrate(ip, q)
                r = pitch.refine(H0, masks, ip, q, kp_weight=0.35)
            except Exception:
                continue
            res["tried"] += 1
            ok = bool(pitch.passes(r))
            if r["H"] is None:
                continue
            stats = {k: float(r[k]) for k in ("support", "worst", "error_m", "uncertainty_m")}
            if ok and (best is None or stats["error_m"] < best[0]["error_m"]):
                best = (stats, r["H"], dict(triple=ti, variant=vn, goal=g is not None, n_corr=len(ip)))
        if best is not None:  # first structural read that passes wins (candidates are ordered)
            break
    if best:
        H = best[1]
        tv = temporal._verify(H, masks, frame.shape)
        res.update(found=True, H=H, verification=dict(best[0], verified=True), cand=best[2],
                   temporal_verify=dict({k: float(tv[k]) for k in ("support", "worst", "error_m", "uncertainty_m")}, passes=bool(pitch.passes(tv))))
    if best is None:  # v2: generic enumeration, ranked by cheap chamfer, top few refined
        for sc, ip, q, info in v2_candidates(segs, cl, frame.shape, masks)[:v2_top]:
            try:
                H0 = cv2.findHomography(ip, q, 0)[0]
                r = pitch.refine(H0, masks, ip, q, kp_weight=0.35)
            except Exception:
                continue
            res["tried"] += 1
            if r["H"] is None: continue
            stats = {k: float(r[k]) for k in ("support", "worst", "error_m", "uncertainty_m")}
            if pitch.passes(r) and (best is None or stats["error_m"] < best[0]["error_m"]):
                best = (stats, r["H"], dict(info, v2=True, n_corr=len(ip), prescore=round(sc, 2)))
        if best:
            tv = temporal._verify(best[1], masks, frame.shape)
            res.update(found=True, H=best[1], verification=dict(best[0], verified=True), cand=best[2],
                       temporal_verify=dict({k: float(tv[k]) for k in ("support", "worst", "error_m", "uncertainty_m")}, passes=bool(pitch.passes(tv))))
    res["secs"] = round(time.time() - t0, 2)
    return res

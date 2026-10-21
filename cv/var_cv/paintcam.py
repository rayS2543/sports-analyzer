"""Camera of one frame from its painted pitch lines alone (no player positions, no keypoint network).

A detected long straight line is an unlabelled line of the pitch: it is a goal line / 6-yard / penalty-area front
line (constant pitch x), a side line of the boxes (constant pitch y), or neither (an edge of a graphic, a net).
Four lines (two of each direction) fix a ground homography exactly, so every assignment of detected lines to
template lines is a candidate. Candidates must not be mirrored, are ranked by how well the rest of the pitch
template lies on painted pixels and how much of the long painted lines the template explains, and the best are
refined by the chamfer fit that the detector uses (pitch.refine) and kept only if they pass its line checks
(pitch.passes). A homography is not forced to be a physical camera: a long lens makes the focal length from the
orthogonality of the ground axes useless, and the detector's own homographies are free either way. Both ends of
the pitch are returned (the template is symmetric under a half turn); the painted lines cannot choose, the
caller does from the players.

Template lines: constant x: goal line, goal area front, penalty area front, halfway; constant y: touchlines,
goal area and penalty area sides.
"""

import itertools
import math

import cv2
import numpy as np
from scipy.spatial import cKDTree

from . import pitch

MIN_LINE_PX = 150        # painted pixels a line needs (a goal-area side in a wide replay is ~200)
MAX_LINES = 8
INLIER_PX = 2.5
CAP_PX = 12.0


def detect_lines(masks, min_px=MIN_LINE_PX, max_lines=MAX_LINES):
    """Long straight painted lines: [{"n": unit normal, "rho", "p0", "p1", "px"}] (n . p = rho), longest first."""
    lines, region = masks
    skel = pitch._skeleton(lines)
    skel[region == 0] = 0
    P = np.argwhere(skel > 0)[:, ::-1].astype(np.float64)
    out = []
    for _ in range(max_lines):
        if len(P) < min_px:
            break
        img = np.zeros(skel.shape, np.uint8)
        img[P[:, 1].astype(int), P[:, 0].astype(int)] = 255
        found = cv2.HoughLines(img, 1, np.pi / 720, min_px)
        if found is None:
            break
        rho, th = found[0][0]
        n = np.array([math.cos(th), math.sin(th)])
        for _ in range(2):  # refit on the inliers, twice
            inl = np.abs(P @ n - rho) < INLIER_PX
            if inl.sum() < min_px:
                break
            vx, vy, x0, y0 = cv2.fitLine(P[inl].astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
            n = np.array([-vy, vx])
            rho = float(n @ [x0, y0])
        inl = np.abs(P @ n - rho) < INLIER_PX
        P_gone = np.abs(P @ n - rho) < 4 * INLIER_PX
        d = np.array([n[1], -n[0]])
        run = _runs(P[inl], d)
        if len(run) >= min_px:
            along = run @ d
            out.append({"n": n, "rho": float(rho), "p0": n * rho + d * along.min(), "p1": n * rho + d * along.max(),
                        "px": len(run), "pts": run[:: max(1, len(run) // 80)]})
        P = P[~P_gone]
    out.sort(key=lambda l: -l["px"])
    return out


def _runs(pts, d, gap=40.0, min_len=60.0):
    """The inlier pixels that lie in stretches (gaps <= `gap` px along the line) at least `min_len` px long: noise
    that happens to be collinear with a painted line, far from it, is not part of the line."""
    if not len(pts):
        return pts
    a = pts @ d
    o = np.argsort(a)
    a, pts = a[o], pts[o]
    cut = np.where(np.diff(a) > gap)[0] + 1
    keep = [pts[i:j] for i, j in zip(np.r_[0, cut], np.r_[cut, len(a)]) if a[j - 1] - a[i] >= min_len]
    return np.vstack(keep) if keep else pts[:0]


def _norm(size):
    w, h = size
    s = 0.5 * max(w, h)
    return np.array([[1 / s, 0, -w / 2 / s], [0, 1 / s, -h / 2 / s], [0, 0, 1.0]])


def template_lines():
    """Homogeneous template lines of the half pitch around goal 0: {"x0","x5.5",...}: (a, b, c) with a x + b y + c = 0."""
    gw, bw = pitch.GOAL_W, pitch.BOX_W
    cy = pitch.WIDTH / 2
    xs = {"goal": 0.0, "area6": pitch.GOAL_L, "area18": pitch.BOX_L, "halfway": pitch.LENGTH / 2}
    ys = {"touch0": 0.0, "box_a": cy - bw / 2, "area6_a": cy - gw / 2, "area6_b": cy + gw / 2, "box_b": cy + bw / 2,
          "touch1": pitch.WIDTH}
    return ({k: np.array([1.0, 0.0, -v]) for k, v in xs.items()}, {k: np.array([0.0, 1.0, -v]) for k, v in ys.items()})


def _skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def _rows(l_img, l_t):
    """Linear constraints on vec(G) (pitch -> normalised image) from G^T l_img ~ l_t: (3, 9)."""
    B = np.zeros((3, 9))
    for k in range(3):
        for m in range(3):
            B[k, 3 * m + k] = l_img[m]
    return _skew(l_t) @ B


def candidates(lines, size):
    """Pitch -> image homographies G (pixels) from every assignment of 2 detected lines to two constant-x
    template lines and 2 others to two constant-y ones, filtered to physical cameras. Returns [(G, labels)];
    the half-turn image of each (the other end of the pitch) is included."""
    xs, ys = template_lines()
    T = _norm(size)
    Tinv = np.linalg.inv(T)
    li = []
    for l in lines:  # normalised image line: n . p = rho -> [nx, ny, -rho] in pixels; transform covariantly
        v = np.array([l["n"][0], l["n"][1], -l["rho"]])
        li.append(Tinv.T @ v)
    out = []
    rot = np.array([[-1, 0, pitch.LENGTH], [0, -1, pitch.WIDTH], [0, 0, 1.0]])  # half turn about the pitch centre
    ix = list(itertools.permutations(range(len(lines)), 2))
    for (a, b), (kx0, kx1) in itertools.product(ix, itertools.combinations(xs, 2)):
        for (c, d), (ky0, ky1) in itertools.product([p for p in ix if not set(p) & {a, b}], itertools.combinations(ys, 2)):
            A = np.vstack([_rows(li[a], xs[kx0]), _rows(li[b], xs[kx1]), _rows(li[c], ys[ky0]), _rows(li[d], ys[ky1])])
            _, sv, vt = np.linalg.svd(A)
            if sv[-2] < 1e-6 * sv[0]:  # not a unique solution
                continue
            Gn = vt[-1].reshape(3, 3)
            G = Tinv @ Gn
            G /= np.linalg.norm(G)
            if abs(G[2, 2]) < 1e-12:
                continue
            Hi = np.linalg.inv(G / G[2, 2])
            if not pitch.orientation_ok(Hi, (size[1], size[0])):
                continue
            labels = (a, b, c, d, kx0, kx1, ky0, ky1)
            out.append((G / G[2, 2], labels))
            Gr = G @ rot
            out.append((Gr / Gr[2, 2], labels + ("rot",)))
    return out


def score(G, masks, dmap, cloud):
    """Lower is better: the template's in-view samples off the paint (mean capped distance / CAP) plus the share of
    the long painted lines (points in `cloud`) that no template sample lies within 4 px of. inf when too little
    of the template is in view to say anything."""
    lines_m, region = masks
    h, w = lines_m.shape[:2]
    img = pitch.project(G, pitch.SAMPLES)
    ok = np.isfinite(img).all(1) & (img[:, 0] > 2) & (img[:, 0] < w - 2) & (img[:, 1] > 2) & (img[:, 1] < h - 2)
    if ok.sum() < 120:
        return math.inf
    q = img[ok]
    q = q[region[q[:, 1].astype(int), q[:, 0].astype(int)] > 0]
    if len(q) < 80:
        return math.inf
    a = float(np.mean(np.minimum(pitch._sample(dmap, q.astype(np.float32)), CAP_PX))) / CAP_PX
    d, _ = cKDTree(q).query(cloud, distance_upper_bound=4.0)
    return a + (1.0 - float(np.mean(np.isfinite(d))))


def fit_frame(masks, size, keep=6):
    """Homographies (pitch -> image) of one frame from its painted lines that pass the detector's own line checks
    (pitch.passes), best supported first: [{"G", "support", "worst", "error_m", "uncertainty_m", "sigma", "labels"}].
    Several are returned because the painted lines cannot tell the two ends of the pitch apart."""
    lines = detect_lines(masks)
    if len(lines) < 4:
        return []
    cands = candidates(lines, size)
    if not cands:
        return []
    dmap = pitch._dist_map(*masks, 20.0)
    cloud = np.vstack([l["pts"] for l in lines])
    ranked = sorted(((score(G, masks, dmap, cloud), k) for k, (G, _) in enumerate(cands)), key=lambda r: r[0])
    none = np.zeros((0, 2))
    out, seen = [], []
    for sc, k in ranked:
        if not math.isfinite(sc) or len(out) >= keep or len(seen) >= 4 * keep:
            break
        G, labels = cands[k]
        probe = pitch.project(G, pitch.SAMPLES[::40])
        if any(np.nanmax(np.linalg.norm(probe - q, axis=1)) < 6.0 for q in seen):  # the same camera, other labels
            continue
        seen.append(probe)
        r = pitch.refine(np.linalg.inv(G), masks, none, none)
        if pitch.passes(r):
            out.append(dict(r, G=np.linalg.inv(r["H"]), labels=labels, score=sc))
    out.sort(key=lambda r: -r["support"])
    return out

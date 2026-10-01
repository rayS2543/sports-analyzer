"""Pitch model, image<->pitch homography, line-verified calibration with per-point uncertainty.

Keypoint order and edge list follow roboflow/sports `SoccerPitchConfiguration`
(https://github.com/roboflow/sports, MIT License, Copyright (c) 2024 Roboflow),
which the football-pitch-detection model was trained against. The coordinates
are our own: IFAB markings on a LENGTH x WIDTH pitch in metres, origin = far-left
corner flag in the broadcast view, x along the length, y across.
"""

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

LENGTH, WIDTH = 105.0, 68.0  # overridden by set_dimensions()
BOX_W, BOX_L = 40.32, 16.5  # penalty area
GOAL_W, GOAL_L = 18.32, 5.5  # goal area
CIRCLE_R, SPOT = 9.15, 11.0
# Roboflow's keypoints 11/12 (and 19/20) sit where the penalty arc meets the box line.
ARC_HALF = float(np.sqrt(CIRCLE_R**2 - (BOX_L - SPOT) ** 2))
EDGES = [  # 1-based, as in roboflow/sports
    (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (7, 8), (10, 11), (11, 12), (12, 13), (14, 15), (15, 16),
    (16, 17), (18, 19), (19, 20), (20, 21), (23, 24), (25, 26), (26, 27), (27, 28), (28, 29), (29, 30),
    (1, 14), (2, 10), (3, 7), (4, 8), (5, 13), (6, 17), (14, 25), (18, 26), (23, 27), (24, 28), (21, 29), (17, 30),
]


def _vertices():
    L, W, cy = LENGTH, WIDTH, WIDTH / 2
    return np.array([
        (0, 0), (0, cy - BOX_W / 2), (0, cy - GOAL_W / 2), (0, cy + GOAL_W / 2), (0, cy + BOX_W / 2), (0, W),
        (GOAL_L, cy - GOAL_W / 2), (GOAL_L, cy + GOAL_W / 2), (SPOT, cy),
        (BOX_L, cy - BOX_W / 2), (BOX_L, cy - ARC_HALF), (BOX_L, cy + ARC_HALF), (BOX_L, cy + BOX_W / 2),
        (L / 2, 0), (L / 2, cy - CIRCLE_R), (L / 2, cy + CIRCLE_R), (L / 2, W),
        (L - BOX_L, cy - BOX_W / 2), (L - BOX_L, cy - ARC_HALF), (L - BOX_L, cy + ARC_HALF), (L - BOX_L, cy + BOX_W / 2),
        (L - SPOT, cy), (L - GOAL_L, cy - GOAL_W / 2), (L - GOAL_L, cy + GOAL_W / 2),
        (L, 0), (L, cy - BOX_W / 2), (L, cy - GOAL_W / 2), (L, cy + GOAL_W / 2), (L, cy + BOX_W / 2), (L, W),
        (L / 2 - CIRCLE_R, cy), (L / 2 + CIRCLE_R, cy),
    ], dtype=np.float64)


def _polylines(step=0.25):
    """Every painted line as a dense polyline in pitch metres."""
    lines = []
    for a, b in EDGES:
        p, q = VERTICES[a - 1], VERTICES[b - 1]
        lines.append(np.linspace(p, q, max(2, int(np.linalg.norm(q - p) / step) + 1)))
    for q in range(8):  # centre circle as eight 45-degree arcs, each judged on its own by the line checks
        th = np.linspace(q * np.pi / 4, (q + 1) * np.pi / 4, int(np.pi / 4 * CIRCLE_R / step))
        lines.append(np.c_[LENGTH / 2 + CIRCLE_R * np.cos(th), WIDTH / 2 + CIRCLE_R * np.sin(th)])
    half = np.arccos((BOX_L - SPOT) / CIRCLE_R)  # penalty arcs: the part outside the box
    th = np.linspace(-half, half, int(2 * half * CIRCLE_R / step))
    lines.append(np.c_[SPOT + CIRCLE_R * np.cos(th), WIDTH / 2 + CIRCLE_R * np.sin(th)])
    lines.append(np.c_[LENGTH - SPOT - CIRCLE_R * np.cos(th), WIDTH / 2 + CIRCLE_R * np.sin(th)])
    return lines


def set_dimensions(length, width):
    """Rebuild every derived geometry table for a pitch of the given size (metres)."""
    global LENGTH, WIDTH, VERTICES, LINES, SAMPLES, LINE_ID, BOUNDARY
    LENGTH, WIDTH = float(length), float(width)
    VERTICES = _vertices()
    LINES = _polylines()
    SAMPLES = np.vstack(LINES)
    LINE_ID = np.concatenate([np.full(len(line), i) for i, line in enumerate(LINES)])
    # The far touchline and the goal lines sit against ad boards (thin, merged, clipped): they
    # count towards overall support only. The near touchline is thick and clean when in view.
    BOUNDARY = {i for i, (a, b) in enumerate(EDGES)
                if (VERTICES[a - 1][1] == 0 and VERTICES[b - 1][1] == 0)
                or (VERTICES[a - 1][0] == VERTICES[b - 1][0] and VERTICES[a - 1][0] in (0, LENGTH))}


set_dimensions(LENGTH, WIDTH)


def project(H, pts):
    """Apply homography to Nx2 points. Returns Nx2 (NaN where the point is at/behind the horizon)."""
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    with np.errstate(divide="ignore", invalid="ignore"):
        out = p[:, :2] / p[:, 2:3]
    out[p[:, 2] <= 1e-9] = np.nan
    return out


def _dlt(src, dst):
    H, _ = cv2.findHomography(src, dst, 0)
    return H


def calibrate(img_pts, pitch_pts, ransac_m=1.0):
    """Fit image->pitch homography to keypoints.

    Returns (H or None, inlier mask, loo_m). loo_m is the RMS leave-one-out error
    over RANSAC inliers (each inlier predicted by a fit on the others); it needs
    >= 5 inliers to mean anything and is inf otherwise.
    """
    img_pts = np.asarray(img_pts, np.float64)
    pitch_pts = np.asarray(pitch_pts, np.float64)
    n = len(img_pts)
    if n < 4:
        return None, np.zeros(n, bool), float("inf")
    H, mask = cv2.findHomography(img_pts, pitch_pts, cv2.RANSAC, ransac_m)
    if H is None:
        return None, np.zeros(n, bool), float("inf")
    inl = mask.ravel().astype(bool)
    if inl.sum() < 5:
        return H, inl, float("inf")
    src, dst = img_pts[inl], pitch_pts[inl]
    H = _dlt(src, dst)  # refit on inliers
    errs = []
    for i in range(len(src)):
        keep = np.arange(len(src)) != i
        Hi = _dlt(src[keep], dst[keep])
        if Hi is None:
            return H, inl, float("inf")
        errs.append(np.linalg.norm(project(Hi, src[i])[0] - dst[i]))
    errs = np.nan_to_num(np.array(errs), nan=1e6)
    return H, inl, float(np.sqrt(np.mean(errs**2)))


def draw_pitch(frame, H, color=(255, 0, 255)):
    """Debug overlay: project the pitch lines back into the image via H^-1."""
    G = np.linalg.inv(H)
    for line in LINES:
        img = project(G, line)
        ok = ~np.isnan(img).any(1) & (np.abs(img) < 1e4).all(1)
        if ok.sum() > 1:
            cv2.polylines(frame, [img[ok].astype(np.int32)], False, color, 2)
    return frame


def line_mask(frame):
    """(lines, region): candidate painted-line pixels (bright, thin, on grass) and the grass region.

    Grass = large green areas (closed, then opened with a 41 px kernel), so crowd,
    ad boards and on-screen graphics are excluded even if they contain green specks,
    while lines right at the pitch edge are kept.
    """
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    top = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 50, 20), (85, 255, 255))  # low V floor: grass in stadium shadow
    region = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))  # fill lines/players
    region = cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((41, 41), np.uint8))  # drop specks in crowd/ads
    region = cv2.dilate(region, np.ones((7, 7), np.uint8))
    # White paint in stadium shadow can be darker than sunlit grass. Require
    # local contrast, with a noise floor, rather than losing every shadowed line.
    contrast = np.clip(0.15 * g, 8, 25)
    return ((top > contrast) & (region > 0)).astype(np.uint8) * 255, region


def _skeleton(mask):
    """1-px centrelines of the line mask (morphological skeleton), so the fit targets the middle of
    a painted line instead of anywhere inside its 3-8 px band (a flat-bottomed cost)."""
    elem = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    img, skel = mask.copy(), np.zeros_like(mask)
    while cv2.countNonZero(img):
        eroded = cv2.erode(img, elem)
        skel |= cv2.subtract(img, cv2.dilate(eroded, elem))
        img = eroded
    return skel


def _dist_map(lines, region, cap=20.0):
    """Distance (px) to the nearest line centreline, capped; off-grass counts as `cap` (lines lie on grass).
    The off-grass step is applied after smoothing so the grass/ad-board boundary never pulls lines."""
    d = cv2.GaussianBlur(np.minimum(cv2.distanceTransform(255 - _skeleton(lines), cv2.DIST_L2, 5), cap), (5, 5), 0)
    d[region == 0] = cap
    return d.astype(np.float32)


def _sample(dmap, pts):
    if len(pts) == 0:
        return np.zeros(0, np.float32)
    p = np.nan_to_num(pts, nan=-1e4).astype(np.float32).reshape(1, -1, 2)
    return cv2.remap(dmap, p[..., 0], p[..., 1], cv2.INTER_LINEAR, borderValue=20.0).ravel()


def _in_view(G, shape, margin=2):
    img = project(G, SAMPLES)
    h, w = shape[:2]
    ok = ~np.isnan(img).any(1)
    ok &= (img[:, 0] > margin) & (img[:, 0] < w - margin) & (img[:, 1] > margin) & (img[:, 1] < h - margin)
    return img, ok


def orientation_ok(H, shape):
    """A real camera looking at the pitch maps image->pitch without mirroring (det of the Jacobian > 0)."""
    h, w = shape[:2]
    p = project(H, [[w / 2, h * 0.6], [w / 2 + 1, h * 0.6], [w / 2, h * 0.6 + 1]])
    if np.isnan(p).any():
        return False
    return np.linalg.det(np.c_[p[1] - p[0], p[2] - p[0]]) > 0


def m_per_px(H, pts, e=0.5):
    """Metres per image pixel at each point: sqrt(|det J|) of the image->pitch map."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    px = project(H, pts + [e, 0]) - project(H, pts - [e, 0])
    py = project(H, pts + [0, e]) - project(H, pts - [0, e])
    return np.sqrt(np.abs(px[:, 0] * py[:, 1] - px[:, 1] * py[:, 0])) / (2 * e)


CORR_PX = 40  # correlation length of line-fit residuals along a painted line (px)
FAIL = {"H": None, "support": 0.0, "worst": 0.0, "error_m": float("inf"),
        "uncertainty_m": float("inf"), "sigma": None}


def refine(H, masks, kp_img, kp_pitch, kp_weight=0.2, stages=((50.0, 10.0), (20.0, 3.0))):
    """Snap a homography onto the painted lines (chamfer fit) and score it.

    masks: (lines, region) from line_mask(). Parameters: pixel offsets of the image
    positions of 4 fixed pitch points (well conditioned). Residuals: distance from
    projected model lines to detected line pixels (Huber), plus anchor points
    (keypoints, or the propagated prior) at `kp_weight` per pixel so the fit
    cannot slide along a single line.

    Returns dict:
      H        refined image->pitch homography
      support  fraction of in-view model line samples within 3 px of a line pixel
      worst    lowest support (5 px) of any interior model line spanning >= 150 px in view
      error_m  RMS pitch-plane residual of matched line samples (<= 8 px)
      sigma    callable(image points Nx2) -> 1-sigma pitch position error (m) at those points:
               homography parameter covariance (from the line fit) propagated to the point,
               plus the line-localisation noise at that point's scale. It grows away from the
               lines that constrain the fit, i.e. at image edges and in extrapolated regions.
    """
    lines, region = masks
    h, w = lines.shape[:2]
    G0 = np.linalg.inv(H)
    _, ok = _in_view(G0, lines.shape)
    if ok.sum() < 80:
        return dict(FAIL, H=H)
    a_img = np.array([[0.15, 0.35], [0.85, 0.35], [0.85, 0.9], [0.15, 0.9]]) * [w, h]
    anchors = project(H, a_img).astype(np.float32)  # pitch points under 4 image anchors
    if np.isnan(anchors).any():
        return dict(FAIL, H=H)
    st = {"pts": SAMPLES[ok][::2], "kp_img": np.asarray(kp_img, np.float64).reshape(-1, 2),
          "kp_pitch": np.asarray(kp_pitch, np.float64).reshape(-1, 2), "dmap": None}

    def G_of(x):
        return cv2.getPerspectiveTransform(anchors, (a_img + x.reshape(4, 2)).astype(np.float32)).astype(np.float64)

    def resid(x):
        G = G_of(x)
        k = (project(G, st["kp_pitch"]) - st["kp_img"]).ravel() * kp_weight
        return np.r_[_sample(st["dmap"], project(G, st["pts"])), np.nan_to_num(k, nan=100.0)].astype(np.float64)

    def jac(x, step=0.5):  # central differences at a pixel-sized step: smooths the piecewise-linear map
        return np.stack([(resid(x + step * e) - resid(x - step * e)) / (2 * step) for e in np.eye(8)], axis=1)

    x = np.zeros(8)
    for cap, scale in stages:  # coarse-to-fine: wide capture range, then tight fit
        st["dmap"] = _dist_map(lines, region, cap)
        x = least_squares(resid, x, jac=jac, loss="huber", f_scale=scale, max_nfev=50).x
    G = G_of(x)
    Hr = np.linalg.inv(G)
    img, ok = _in_view(G, lines.shape)
    if ok.sum() < 80 or not orientation_ok(Hr, lines.shape):
        return dict(FAIL, H=Hr)
    d = _sample(st["dmap"], img[ok])  # distance to line centrelines (fit + error)
    band = np.minimum(cv2.distanceTransform(255 - lines, cv2.DIST_L2, 5), 20.0)
    band[region == 0] = 20.0
    db = _sample(band, img[ok])  # distance to the painted band itself (evidence checks)
    hit, ids = db < 3.0, LINE_ID[ok]
    _, inner = _in_view(G, lines.shape, margin=40)  # lines grazing the frame edge are too uncertain to judge
    inner = inner[ok]
    worst = 1.0
    for i in set(np.unique(ids[inner])) - BOUNDARY:
        sel = inner & (ids == i)
        if np.linalg.norm(np.ptp(img[ok][sel], axis=0)) >= (60 if i >= len(EDGES) else 150):  # arcs are short
            worst = min(worst, float((db[sel] < 5.0).mean()))
    near = d < 8.0
    if near.sum() < 30:
        return dict(FAIL, H=Hr, support=float(hit.mean()), worst=worst)
    mpp = m_per_px(Hr, img[ok][near])
    # residual in metres only where the image resolves the pitch (< 0.5 m/px); near the horizon one
    # pixel spans metres and would swamp the fit-quality number with foreshortening, not misfit
    near_idx = np.where(near)[0][np.isfinite(mpp) & (mpp < 0.5)]
    near = np.zeros_like(near)
    near[near_idx] = True
    if near.sum() < 30:
        return dict(FAIL, H=Hr, support=float(hit.mean()), worst=worst)
    err = float(np.sqrt(np.mean((d[near] * m_per_px(Hr, img[ok][near])) ** 2)))

    # Parameter covariance from the matched line rows of the Jacobian at the solution.
    st.update(pts=SAMPLES[ok][near], kp_img=np.zeros((0, 2)), kp_pitch=np.zeros((0, 2)))
    J = jac(x)
    s2 = max(float(np.mean(d[near] ** 2)), 1.0)  # px^2; floor = line localisation quantisation
    # Line residuals are strongly correlated along a line (one mis-placed line shifts every sample
    # on it), so the samples are not independent: count one observation per CORR_PX of matched
    # line length instead of one per sample, i.e. inflate the covariance by n_samples / n_effective.
    q = img[ok][near]
    seg = np.linalg.norm(np.diff(q, axis=0), axis=1)
    length = float(seg[seg < 10].sum())  # image length of matched lines (ignore jumps between lines)
    inflate = max(1.0, len(q) / max(length / CORR_PX, 1.0))
    # A pseudoinverse assigns zero variance to unobserved directions. A line-only
    # close-up must not gain certainty just because its homography is underdetermined.
    _, singular, vt = np.linalg.svd(J, full_matrices=False)
    if singular[-1] <= singular[0] * 1e-6:
        return dict(FAIL, H=Hr, support=float(hit.mean()), worst=worst, error_m=err)
    cov = inflate * s2 * (vt.T / singular**2) @ vt
    Hs = [np.linalg.inv(G_of(x + 0.5 * e)) for e in np.eye(8)] + [np.linalg.inv(G_of(x - 0.5 * e)) for e in np.eye(8)]

    def sigma(points):
        points = np.asarray(points, np.float64).reshape(-1, 2)
        Jp = np.stack([project(Hs[k], points) - project(Hs[k + 8], points) for k in range(8)], axis=2)
        var = np.einsum("nik,kl,nil->n", Jp, cov, Jp)
        loc2 = s2 * m_per_px(Hr, points) ** 2
        return np.sqrt(np.maximum(var, 0) + loc2)

    uncertainty = region_error(sigma, region)
    return {"H": Hr, "support": float(hit.mean()), "worst": worst, "error_m": err, "sigma": sigma,
            "uncertainty_m": uncertainty if uncertainty is not None else float("inf")}


def icp_init(H, masks, radii=(200, 150, 100, 70, 45, 25, 12)):
    """Pull a rough homography onto the painted lines from far away (large-radius ICP).

    The chamfer fit only sees lines within ~50 px. When the keypoint model misplaces whole
    features (e.g. predicts the centre circle 150 px too small), match every in-view model
    line sample to its nearest line-centre pixel within a shrinking radius and re-fit the
    homography with RANSAC each round. Returns an image->pitch homography or None.
    """
    lines, region = masks
    skel = _skeleton(lines)
    skel[region == 0] = 0
    if cv2.countNonZero(skel) < 50:
        return None
    src = np.where(skel > 0, 0, 255).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    coords = np.argwhere(src == 0)[:, ::-1].astype(np.float64)  # label k <-> k-th zero pixel (row-major), as x, y
    h, w = lines.shape[:2]
    G = np.linalg.inv(H)
    for r in radii:
        img, ok = _in_view(G, lines.shape)
        if ok.sum() < 30:
            return None
        pts, p = SAMPLES[ok], img[ok]
        # model -> data: each projected model sample to its nearest line-centre pixel
        lab = labels[np.clip(p[:, 1].astype(int), 0, h - 1), np.clip(p[:, 0].astype(int), 0, w - 1)]
        q = coords[np.clip(lab - 1, 0, len(coords) - 1)]
        keep = np.linalg.norm(q - p, axis=1) < r
        # data -> model: each line-centre pixel to its nearest projected model sample, so painted
        # lines the model misses (e.g. the far side of a too-small circle) pull the fit outwards
        dist, idx = cKDTree(p).query(coords[::3], distance_upper_bound=r)
        found = np.isfinite(dist)
        src_pts = np.r_[pts[keep], pts[idx[found]]]
        dst_pts = np.r_[q[keep], coords[::3][found]]
        if len(src_pts) < 30:
            return None
        Gn, inl = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, max(3.0, r / 4))
        if Gn is None or inl.sum() < 30:
            return None
        G = Gn
    return np.linalg.inv(G)


def ellipse_to_conic(e):
    (cx, cy), (a2, b2), ang = e
    a, b, t = a2 / 2, b2 / 2, np.deg2rad(ang)
    ct, sn = np.cos(t), np.sin(t)
    A = ct * ct / a**2 + sn * sn / b**2
    B = 2 * ct * sn * (1 / a**2 - 1 / b**2)
    Cc = sn * sn / a**2 + ct * ct / b**2
    D = -2 * A * cx - B * cy
    E = -B * cx - 2 * Cc * cy
    F = A * cx * cx + B * cx * cy + Cc * cy * cy - 1
    return np.array([[A, B / 2, D / 2], [B / 2, Cc, E / 2], [D / 2, E / 2, F]])


def fit_centre_circle(H, masks):
    """Ellipse fitted to painted line-centre arcs around where H predicts the centre circle
    (halfway line and touchline pixels excluded). Returns the image conic or None when no ellipse
    with enough support (>= 200 px of arc spread around >= 200 degrees) is found."""
    lines, region = masks
    G = np.linalg.inv(H)
    circ = np.vstack([LINES[len(EDGES) + q] for q in range(8)])
    pc = project(G, circ)
    if np.isnan(pc).any():
        return None
    skel = _skeleton(lines)
    skel[region == 0] = 0
    lo, hi = pc.min(0), pc.max(0)
    size = hi - lo
    ys, xs = np.nonzero(skel)
    P = np.c_[xs, ys].astype(np.float64)
    sel = ((P > lo - 1.5 * size) & (P < hi + 1.5 * size)).all(1)
    P = P[sel]
    others = [project(G, l) for i, l in enumerate(LINES[:len(EDGES)])]
    others = np.vstack([o[~np.isnan(o).any(1)] for o in others if len(o)])
    if len(others):
        d, _ = cKDTree(others).query(P, distance_upper_bound=8)
        P = P[~np.isfinite(d)]
    if len(P) < 60:
        return None
    # Candidate arcs = connected pieces of the remaining line-centre pixels; the painted circle shows
    # up as a few long arcs. Fit an ellipse to every long arc and every pair of arcs, keep the one
    # that explains the most pixels, then refit on its inliers.
    img = np.zeros(lines.shape, np.uint8)
    img[P[:, 1].astype(int), P[:, 0].astype(int)] = 255
    n, lab = cv2.connectedComponents(cv2.dilate(img, np.ones((3, 3), np.uint8)))
    arcs = [np.argwhere(lab == i)[:, ::-1].astype(np.float32) for i in range(1, n)]
    arcs = sorted((a for a in arcs if len(a) >= 40), key=len, reverse=True)[:8]

    def inliers(e):  # pixels within 3 px of the ellipse outline
        poly = cv2.ellipse2Poly((int(e[0][0]), int(e[0][1])), (int(e[1][0] / 2), int(e[1][1] / 2)), int(e[2]), 0, 360, 3)
        if len(poly) < 10:
            return np.zeros(len(P), bool)
        d, _ = cKDTree(poly.astype(np.float64)).query(P, distance_upper_bound=3)
        return np.isfinite(d)

    cands = arcs + [np.vstack([a, b]) for i, a in enumerate(arcs) for b in arcs[i + 1:]]
    best, best_n = None, 0
    for c in cands:
        if len(c) < 5:
            continue
        e = cv2.fitEllipse(c)
        (cx, cy), (a2, b2), _ = e
        if not (0.3 * size[0] < max(a2, b2) < 4 * max(size[0], 1) and min(a2, b2) > 10):
            continue
        for _ in range(2):  # refit on inliers
            m = inliers(e)
            if m.sum() < 5:
                break
            e = cv2.fitEllipse(P[m].astype(np.float32))
        k = int(inliers(e).sum())
        if k > best_n:
            best, best_n = e, k
    if best is None or best_n < 150:
        return None
    inl = P[inliers(best)]
    ang = np.degrees(np.arctan2(inl[:, 1] - best[0][1], inl[:, 0] - best[0][0]))
    if len(np.unique((ang // 20).astype(int))) < 10:  # >= 200 degrees of arc actually painted
        return None
    return ellipse_to_conic(cv2.fitEllipse(inl.astype(np.float32)))


def _conic_line(C, l):
    """Intersections (0 or 2 image points) of conic C with homogeneous line l."""
    a, b, c = l
    n2 = a * a + b * b
    if n2 < 1e-12:
        return []
    p0 = np.array([-a * c / n2, -b * c / n2, 1.0])
    d = np.array([-b, a, 0.0])
    qa, qb, qc = d @ C @ d, 2 * d @ C @ p0, p0 @ C @ p0
    disc = qb * qb - 4 * qa * qc
    if abs(qa) < 1e-15 or disc < 0:
        return []
    ts = [(-qb + sgn * np.sqrt(disc)) / (2 * qa) for sgn in (1, -1)]
    return [(p0 + t * d)[:2] for t in ts]


def _fit_image_line(l, masks, band=12):
    """Refit an image line to the painted line-centre pixels within `band` px of the predicted line l."""
    skel = _skeleton(masks[0])
    skel[masks[1] == 0] = 0
    ys, xs = np.nonzero(skel)
    P = np.c_[xs, ys].astype(np.float64)
    dist = np.abs(P @ l[:2] + l[2]) / max(np.hypot(l[0], l[1]), 1e-12)
    P = P[dist < band]
    if len(P) < 40:
        return l
    vx, vy, x0, y0 = cv2.fitLine(P.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.cross([x0, y0, 1.0], [x0 + vx, y0 + vy, 1.0])


def circle_pose(H, masks, iters=4):
    """Re-solve the homography from the painted centre circle and halfway line.

    Keypoint fits often get the circle's size badly wrong (on the Alaves-Real Madrid wide camera
    by ~40%), and the chamfer fit cannot escape: the model circle settles in the valley between the
    painted arcs. The painted circle's image is an ellipse; with the halfway line and the current
    vanishing point it yields four exact correspondences: circle x halfway line (pitch keypoints 15,
    16) and the tangent points towards the across-pitch vanishing point (31, 32). Iterated a few
    times since the vanishing point comes from the current estimate. Returns image->pitch H or None.
    """
    C = fit_centre_circle(H, masks)
    if C is None:
        return None
    cx, cy, r = LENGTH / 2, WIDTH / 2, CIRCLE_R
    world = {"15": (cx, cy - r), "16": (cx, cy + r), "31": (cx - r, cy), "32": (cx + r, cy)}
    for _ in range(iters):
        G = np.linalg.inv(H)
        l = np.cross(G @ [cx, 0, 1.0], G @ [cx, WIDTH, 1.0])
        l = _fit_image_line(l, masks)
        pts = {}
        for (ka, kb), found in ((("15", "16"), _conic_line(C, l)),
                                (("31", "32"), _conic_line(C, C @ (G @ [0, 1, 0.0])))):  # tangents from V_y
            if len(found) != 2:
                return None
            pa, pb = project(G, [world[ka], world[kb]])
            d = pb - pa  # order the two intersections the way the current estimate orders them
            first, second = sorted(found, key=lambda q: float(np.dot(q - pa, d)))
            pts[ka], pts[kb] = first, second
        keys = sorted(pts)
        Hn, _ = cv2.findHomography(np.array([pts[k] for k in keys]), np.array([world[k] for k in keys], float), 0)
        if Hn is None:
            return None
        H = Hn
    return H


MAX_LOO_M = 3.0  # loose keypoint-only gate; the line checks are the real test
KP_CONF = 0.5
BORDER_PX = 8  # keypoints this close to the frame edge are usually clipped predictions
MIN_SUPPORT, MIN_LINE_SUPPORT, MAX_ERROR_M = 0.5, 0.3, 1.0
MAX_POSITION_ERROR_M = 1.0  # 90th-percentile 1-sigma position uncertainty over visible grass


def passes(r):
    return bool(r["H"] is not None and r["sigma"] is not None and r["support"] >= MIN_SUPPORT
                and r["worst"] >= MIN_LINE_SUPPORT and r["error_m"] <= MAX_ERROR_M
                and r["uncertainty_m"] <= MAX_POSITION_ERROR_M)


def region_error(sigma, region, step=40):
    """90th-percentile 1-sigma position error over the visible grass; inf if any of it is unobservable.
    Not the maximum: the grass mask's edge samples (stands, frame corners) extrapolate far from every
    line and would reject frames that locate 90% of the pitch to a few decimetres. Each player still
    carries its own per-point uncertainty."""
    h, w = region.shape[:2]
    ys, xs = np.mgrid[step // 2:h:step, step // 2:w:step]
    pts = np.c_[xs.ravel(), ys.ravel()].astype(float)
    pts = pts[region[pts[:, 1].astype(int), pts[:, 0].astype(int)] > 0]
    if not len(pts):
        return None
    s = sigma(pts)
    return float(np.percentile(s, 90)) if np.isfinite(s).all() else float("inf")


def calibrate_frame(frame, kps, masks=None):
    """Detected calibration for one frame. kps: 32x3 (x, y, conf) from the pitch model, or None.

    Tries the confident keypoints, then a lower-confidence set; each fit is refined on the
    painted lines and must pass the line checks. Returns a dict with H (image->pitch) or
    None, ok, keypoints, loo_m, support, worst_line, error_m, sigma, failure (reason or None).
    """
    masks = masks if masks is not None else line_mask(frame)
    out = {"H": None, "ok": False, "keypoints": 0, "loo_m": None, "support": 0.0, "worst_line": 0.0,
           "error_m": None, "sigma": None, "failure": "no pitch keypoints detected"}
    if kps is None:
        return out
    h, w = frame.shape[:2]
    x, y, c = kps[:, 0], kps[:, 1], kps[:, 2]
    inside = (x > BORDER_PX) & (x < w - BORDER_PX) & (y > BORDER_PX) & (y < h - BORDER_PX)
    best = None
    for conf in (KP_CONF, 0.3):
        m = inside & (c > conf)
        out["keypoints"] = max(out["keypoints"], int(m.sum()))
        H, inl, loo = calibrate(kps[m, :2], VERTICES[m])
        if H is None or inl.sum() < 4:
            continue
        if np.isfinite(loo) and loo > MAX_LOO_M:
            out["failure"] = f"keypoints inconsistent (leave-one-out {loo:.1f} m)"
            continue
        r = refine(H, masks, kps[m][inl, :2], VERTICES[m][inl])
        r["loo_m"] = loo if np.isfinite(loo) else None
        if best is None or (passes(r), r["support"]) > (passes(best), best["support"]):
            best = r
        if passes(r):
            break
    if best is not None and not passes(best):
        # keypoint fit far off: re-solve from the painted centre circle, or pull it in with
        # large-radius ICP, then the same refinement and line checks
        none = np.zeros((0, 2))
        for start in (circle_pose, icp_init):
            h0 = start(best["H"], masks)
            if h0 is None or not orientation_ok(h0, masks[0].shape):
                continue
            r = refine(h0, masks, none, none)
            r["loo_m"] = best.get("loo_m")
            if passes(r):
                best = r
                break
    if best is None:
        if out["keypoints"] < 4:
            out["failure"] = f"only {out['keypoints']} usable pitch keypoints"
        return out
    ok = passes(best)
    out.update(H=best["H"], ok=ok, loo_m=best.get("loo_m"), support=best["support"], worst_line=best["worst"],
               error_m=best["error_m"] if np.isfinite(best["error_m"]) else None, sigma=best["sigma"],
               failure=None if ok else f"line check failed (support {best['support']:.2f}, "
                                        f"worst line {best['worst']:.2f}, "
                                        f"position uncertainty {best['uncertainty_m']:.2f} m)")
    return out

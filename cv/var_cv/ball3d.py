"""Ball height from one broadcast camera: per-frame camera + physics fit per flight segment.

apply(analysis) adds analysis["ball3d"] (per-shot camera centre, box-size calibration, segments) and,
on every calibrated frame whose ball was detected:
  ball.z                    height of the ball's bottom above the grass, m (0 = on the ground; null = unknown)
  ball.airborne             bool (null = unknown)
  ball.x, ball.y            ground point under the ball (corrected for height)
  ball.ground_x, ground_y   the old naive projection (image point assumed to be on the grass)
  ball.height_uncertainty_m 1-sigma height uncertainty (null = unknown)
  ball.height_model         "ballistic" | "rolling" | "at_feet" | "unfitted" | "outlier"

Method
1. Camera. H maps pitch (x, y, 1) -> image. With the principal point at the image centre, square
   pixels and zero skew, K = diag(f, f, 1) and H ~ K [r1 r2 t]. Orthogonality of r1, r2 (Zhang) gives two
   equations linear in w = 1/f^2 for the centred homography A = [a1 a2 a3]:
       (a1x a2x + a1y a2y) w + a1z a2z = 0
       (|a1xy|^2 - |a2xy|^2) w + (a1z^2 - a2z^2) = 0
   solved by least squares; then [r1 r2 t] = K^-1 A / scale, R orthonormalised by SVD, C = -R^T t.
   A broadcast camera pans/tilts/zooms about a fixed point, so the shot's camera centre is the median
   of the per-frame centres. Given C (height axis up), the projection of (x, y, h) is
       P = [h1 h2 c h3],  c = -(h3 + Cx h1 + Cy h2) / Ch      (from P C = 0)
   which reproduces H exactly on the grass, so ground_x/ground_y and x/y agree for a rolling ball.
2. Observations: the ball-box centre = projection of (x, y, h + 0.11) and its radius (depth cue:
   r_px = f * 0.11 / depth; the box/ball size ratio is first calibrated on the shot's rolling stretches,
   whose depth is known, and the cue is off when there are none). Without a box, the box's bottom-centre (`image_bottom`, or v1 `image`)
   = projection of (x, y, h).
3. Segments. Within a shot, the calibrated observations are split into segments by dynamic programming:
   minimise sum over segments of (robust reprojection chi^2 + k ln n + break penalty), where each segment
   is the better of
       rolling:   h = 0,  x = x0 + vx t + ax t^2/2 (same for y), weak prior |a| ~ 2 m/s^2   (k = 4)
       ballistic: x = x0 + vx t, y = y0 + vy t, h = z0 + vz t - 9.81 t^2 / 2, h >= 0     (k = 6)
   There is no break penalty where the ball is at a player's feet (kicks, deflections) or where the
   previous flight has reached the grass (bounces). Hard-hit flights (> DRAG_MIN_MPS) are refitted with
   quadratic air drag held constant at the mid-flight velocity; the drag fit is kept when it costs less. Residuals are made linear in the parameters
   (u * p3.X - p1.X, divided by the current depth: iteratively reweighted, converges to the pixel error);
   residuals over 4 sigma are truncated (outlier detections).
4. Output: height from the segment model; ground point = the observed ray cut at that height, so the
   ball still lands exactly on its pixel. Uncertainty = linearised fit covariance (+ calibration error
   x tan(elevation)). A rolling segment reports how high a hop could hide in it (_hidden_hop).
   Pixel sigma per detection = hypot(1.5 px box jitter, that frame's calibration error in px).
Segments with fewer than MIN_OBS detections are "unfitted": one camera cannot tell height from depth
without the physics constraint, so z/airborne stay null there -- unless the ball sits in the lowest 20%
of a player's box ("at_feet": z = 0 +- 0.35 m). Detections that miss their segment's trajectory by more
than 4 sigma are "outlier" (usually a false ball) and keep the naive position with z null.
"""

import numpy as np

G = 9.81
BALL_R = 0.11
SIGMA_DET_PX = 1.5  # ball-box centre jitter, px. Per frame it is combined with that frame's calibration
                    # error (reprojection_error_m converted to px at the ball): sigma_i = hypot(1.5, e_i / m_per_px)
SIGMA_ACC = 2.0     # rolling-ball acceleration prior, m/s^2 (grass friction, skids)
OUTLIER = 16.0      # chi^2 cap per observation (4 sigma)
MIN_OBS = 5         # detections needed before a segment can be called ballistic or rolling
MAX_GAP_S = 1.0     # never fit across a longer gap in detections
MAX_SEG = 60        # longest segment considered (observations)
BREAK = 6.0         # extra cost of a segment boundary away from any player
MAX_SPEED = 45.0    # m/s: faster fits are not a football
HOP_WINDOW = 7      # detections at each end of a rolling segment re-tested for a hidden hop
AT_FEET_BAND = 0.2  # ball bottom in the lowest 20% of a player's box = at his feet (~0.35 m of leg)
AT_FEET_SIGMA_M = 0.35
DRAG_K = 0.0133     # 1/m: rho Cd A / 2m, air 1.2 kg/m^3, Cd 0.25 (fast ball, past the drag crisis), size-5 ball
DRAG_MIN_MPS = 15.0 # below this drag moves the ball < ~0.3 m over a typical segment: ignored


def camera_from_homography(H, width, height):
    """Returns {"f", "R", "t", "C"} (world z = R's third axis; C[2] sign depends on handedness) or None."""
    H = np.asarray(H, float)
    T = np.array([[1, 0, width / 2], [0, 1, height / 2], [0, 0, 1.0]])
    A = np.linalg.solve(T, H)
    A[:2] /= width  # focal length in units of image width, for conditioning
    A /= np.linalg.norm(A[:, :2])  # one common scale: |r1| = |r2| is one of the constraints
    a1, a2 = A[:, 0], A[:, 1]
    coef = np.array([a1[0] * a2[0] + a1[1] * a2[1], a1[0] ** 2 + a1[1] ** 2 - a2[0] ** 2 - a2[1] ** 2])
    rhs = -np.array([a1[2] * a2[2], a1[2] ** 2 - a2[2] ** 2])
    w = coef @ rhs / max(coef @ coef, 1e-18)
    if not np.isfinite(w) or w <= 0:
        return None
    f = 1 / np.sqrt(w)
    M = np.diag([1 / f, 1 / f, 1.0]) @ A
    n1, n2 = np.linalg.norm(M[:, 0]), np.linalg.norm(M[:, 1])
    if max(n1, n2) / min(n1, n2) > 1.5:  # inconsistent: not a pinhole with this principal point
        return None
    r1, r2, t = M[:, 0] / n1, M[:, 1] / n2, M[:, 2] / np.sqrt(n1 * n2)
    g = np.linalg.solve(H, [width / 2, height / 2, 1.0])  # pitch point under the image centre
    if (r1 * g[0] / g[2] + r2 * g[1] / g[2] + t)[2] < 0:  # it must be in front of the camera
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.c_[r1, r2, np.cross(r1, r2)])
    R = U @ Vt
    return {"f": f * width, "R": R, "t": t, "C": -R.T @ t}


def projection(H, C):
    """3x4 P for pitch points (x, y, h, 1), h = height up, given camera centre C = (x, y, height > 0)."""
    H = np.asarray(H, float)
    return np.c_[H[:, 0], H[:, 1], -(H[:, 2] + C[0] * H[:, 0] + C[1] * H[:, 1]) / C[2], H[:, 2]]


def _focal_scale(P, width, height):
    """(f, s) with P ~ s K [R | t]: depth of X = (P X)_3 / s."""
    T = np.array([[1, 0, width / 2], [0, 1, height / 2], [0, 0, 1.0]])
    M = np.linalg.solve(T, P[:, :3])
    MM = M @ M.T
    s = np.sqrt(MM[2, 2])
    return np.sqrt(max((MM[0, 0] + MM[1, 1]) / 2, 1e-12)) / s, s


# ---------- trajectory models: X(tau) = A(tau) theta + b(tau), X = (x, y, observed-point height) ----------

def _design(model, tau, off, acc=None):
    """acc: constant extra acceleration (x, y, h) of a ballistic segment (air drag), or None."""
    n = len(tau)
    A = np.zeros((n, 3, 6))
    b = np.zeros((n, 3))
    b[:, 2] = off
    if acc is not None:
        b += 0.5 * np.outer(tau ** 2, acc)
    A[:, 0, 0] = A[:, 1, 1] = 1
    if model == "ballistic":  # x0 y0 z0 vx vy vz
        A[:, 2, 2] = 1
        A[:, 0, 3] = A[:, 1, 4] = A[:, 2, 5] = tau
        b[:, 2] -= G * tau ** 2 / 2
    else:  # rolling: x0 y0 vx vy ax ay
        A[:, 0, 2] = A[:, 1, 3] = tau
        A[:, 0, 4] = A[:, 1, 5] = tau ** 2 / 2
    return A, b


def _fit(model, obs, idx, theta0=None, anchors=(), acc=None):
    """Robust fit of one model to observations idx (Levenberg-Marquardt on pixel error).
    theta0: warm start (same t0). anchors: [(t, (x, y, h), sigma_m)] continuity with neighbouring
    segments (the ball does not teleport at a kick or bounce). acc: fixed drag acceleration (ballistic).
    A ballistic fit faster than DRAG_MIN_MPS is refit once with drag from its own launch velocity.
    Returns dict or None."""
    t, P, u, off, r, f, s, sp = (obs[k][idx] for k in ("t", "P", "u", "off", "r", "f", "s", "sig"))
    sp = sp[:, None]
    tau = t - t[0]
    A, b = _design(model, tau, off, acc if model == "ballistic" else None)
    MA = np.einsum("njk,nkp->njp", P[:, :, :3], A)                 # dq/dtheta, n x 3 x 6
    q0 = np.einsum("njk,nk->nj", P[:, :, :3], b) + P[:, :, 3]      # q = MA theta + q0
    has_r = ~np.isnan(r)
    r0, sig_r, fRs = np.nan_to_num(r), 1.0 + 0.15 * np.nan_to_num(r), f * BALL_R * s
    T = tau[-1]
    if anchors:
        An, bn = _design(model, np.array([a[0] for a in anchors]) - t[0], np.zeros(len(anchors)),
                         acc if model == "ballistic" else None)
        Xn = np.array([a[1] for a in anchors], float)
        sn = np.array([a[2] for a in anchors], float)[:, None]
        if model == "rolling":
            Xn[:, 2] = 0.0  # a rolling segment has no height to tie

    def resid(th, jac=False):
        q = MA @ th + q0
        if (q[:, 2] <= 1e-9).any():
            return None
        proj = q[:, :2] / q[:, 2:3]
        e_px = (proj - u) / sp
        e_r = np.where(has_r, (fRs / q[:, 2] - r0) / sig_r, 0.0)
        e2 = (e_px ** 2).sum(1) + e_r ** 2
        extra = []
        if model == "rolling":
            extra = [th[4] / SIGMA_ACC, th[5] / SIGMA_ACC]
        else:  # h >= 0 at both ends (h is concave, so the ends suffice)
            extra = [30 * min(0.0, th[2]), 30 * min(0.0, th[2] + th[5] * T - G * T * T / 2)]
        if anchors:
            extra = [*extra, *(((An @ th + bn) - Xn) / sn).ravel()]
        if not jac:
            return e2, np.array(extra)
        d_px = (MA[:, :2] - proj[:, :, None] * MA[:, 2:3]) / (q[:, 2:3, None] * sp[:, :, None])
        d_r = np.where(has_r[:, None], -fRs[:, None] / q[:, 2:3] ** 2 * MA[:, 2] / sig_r[:, None], 0.0)
        Je = np.zeros((2, 6))
        if model == "rolling":
            Je[0, 4] = Je[1, 5] = 1 / SIGMA_ACC
        else:
            Je[0, 2] = 30.0 * (th[2] < 0)
            Je[1, [2, 5]] = np.array([1.0, T]) * 30.0 * (th[2] + th[5] * T - G * T * T / 2 < 0)
        if anchors:
            Je = np.vstack([Je, (An / sn[:, :, None]).reshape(-1, 6)])
        return e2, np.array(extra), np.c_[e_px, e_r], np.concatenate([d_px, d_r[:, None]], 1), Je

    def cost(th):  # Cauchy loss for the optimiser: outliers still pull a little, so no truncation traps
        out = resid(th)
        return np.inf if out is None else float((OUTLIER * np.log1p(out[0] / OUTLIER)).sum() + (out[1] ** 2).sum())

    theta = theta0 if theta0 is not None and np.isfinite(cost(theta0)) else None
    if theta is None:
        theta = min(_inits(model, tau, P, u, off, sp[:, 0]), key=cost)
    c, lam = cost(theta), 1e-3
    if not np.isfinite(c):
        return None
    for _ in range(30):
        e2, ex, e, De, Je = resid(theta, jac=True)
        w = 1 / np.sqrt(1 + e2 / OUTLIER)  # IRLS weights of the Cauchy loss
        J = np.vstack([(De * w[:, None, None]).reshape(-1, 6), Je])
        y = np.concatenate([(e * w[:, None]).ravel(), ex])
        JtJ, g = J.T @ J, J.T @ y
        while lam < 1e8:
            step = np.linalg.solve(JtJ + lam * np.diag(np.diag(JtJ) + 1e-9), -g)
            c2 = cost(theta + step)
            if c2 < c:
                break
            lam *= 10
        else:
            break
        theta, lam, done = theta + step, max(lam / 10, 1e-7), c - c2 < 1e-6 * max(c, 1)
        c = c2
        if done:
            break
    e2, ex, e, De, Je = resid(theta, jac=True)
    inlier = e2 < OUTLIER
    if inlier.sum() < min(3, len(idx)):
        return None
    J = np.vstack([(De * inlier[:, None, None]).reshape(-1, 6), Je])
    nres = 2 * len(idx) + int(has_r.sum())
    k = 6 if model == "ballistic" else 4
    if model == "ballistic":
        speed = np.linalg.norm(theta[3:6])
    else:
        speed = np.linalg.norm(theta[2:4] + np.outer(tau[[0, -1]], theta[4:6]), axis=1).max()
    if speed > MAX_SPEED:
        return None
    out = {"model": model, "theta": theta, "idx": idx, "t0": t[0], "chi2": c, "inlier": inlier,
           "cost": c + k * np.log(max(nres, 2)), "J": J, "nres": nres, "k": k, "acc": acc}
    if model == "ballistic" and acc is None and speed > DRAG_MIN_MPS and DRAG_K > 0:
        # ponytail: constant drag from the mid-flight velocity (2 fixed-point passes); integrate the ODE if needed
        best, a, th = out, np.zeros(3), theta
        for _ in range(2):
            vmid = th[3:6] + (a + [0, 0, -G]) * T / 2
            a = -DRAG_K * np.linalg.norm(vmid) * vmid
            d = _fit(model, obs, idx, th, anchors, acc=a)
            if d is None:
                break
            th = d["theta"]
            best = min(best, d, key=lambda fit: fit["cost"])  # drag kept only when the data prefer it
        return best
    return out


def _inits(model, tau, P, u, off, sig):
    """Starting points. Rolling: a quadratic fit to the ground-plane reading of each pixel. Ballistic:
    for a grid of take-off speeds vz (z0 = 0) the height of every sample is known, so the horizontal
    motion is a linear least-squares problem in pixels (weighted by depth); the best few seed LM.
    Fixing the height avoids the degenerate 'ball at the camera' solution of a free algebraic fit."""
    Hg = np.concatenate([P[:, :, [0, 1]], (P[:, :, 2] * off[:, None] + P[:, :, 3])[:, :, None]], axis=2)
    g = np.linalg.solve(Hg, np.c_[u, np.ones(len(u))][:, :, None])[:, :, 0]
    g = g[:, :2] / g[:, 2:3]
    if model == "rolling":
        deg = 2 if len(tau) >= 4 else 1
        cx, cy = np.polyfit(tau, g[:, 0], deg), np.polyfit(tau, g[:, 1], deg)
        acc = [2 * cx[0], 2 * cy[0]] if deg == 2 else [0.0, 0.0]
        return [np.array([cx[-1], cy[-1], cx[-2], cy[-2], *acc])]
    M, p4 = P[:, :, :3], P[:, :, 3]
    L = np.einsum("nj,nk->njk", u, M[:, 2]) - M[:, :2]          # rows of u*p3 - p_j, n x 2 x 3
    B = np.zeros((len(tau), 3, 4))
    B[:, 0, 0] = B[:, 1, 1] = 1
    B[:, 0, 2] = B[:, 1, 3] = tau
    LB = np.einsum("njk,nkp->njp", L, B)
    out = []
    for vz in np.arange(0.0, 26.0, 2.0):
        c = np.zeros((len(tau), 3))
        c[:, 2] = vz * tau - G * tau ** 2 / 2 + off
        rhs = -(np.einsum("njk,nk->nj", L, c) + u * p4[:, 2:3] - p4[:, :2])
        w = np.ones(len(tau))
        for _ in range(2):  # reweight by depth so rows measure pixels
            th4 = np.linalg.lstsq((LB * w[:, None, None]).reshape(-1, 4), (rhs * w[:, None]).ravel(), rcond=None)[0]
            X = np.einsum("nkp,p->nk", B, th4) + c
            depth = np.einsum("nk,nk->n", M[:, 2], X) + p4[:, 2]
            if (depth <= 0).any():
                break
            w = 1 / (sig * depth / np.median(depth))
        else:
            out.append(np.array([th4[0], th4[1], 0.0, th4[2], th4[3], vz]))
    return out or [np.array([g[0, 0], g[0, 1], 0.0, 0.0, 0.0, G * max(tau[-1], 1e-3) / 2])]


def _residuals(obs, idx, X):
    """Per-observation chi^2 (reprojection + radius) at 3D points X."""
    P, u, r, f, s = (obs[k][idx] for k in ("P", "u", "r", "f", "s"))
    q = np.einsum("njk,nk->nj", P, np.c_[X, np.ones(len(X))])
    proj = q[:, :2] / q[:, 2:3]
    e2 = ((proj - u) ** 2).sum(1) / obs["sig"][idx] ** 2
    rp = f * BALL_R * s / q[:, 2]
    er = np.where(np.isnan(r), 0.0, ((rp - np.nan_to_num(r)) / (1.0 + 0.15 * np.nan_to_num(r))) ** 2)
    return e2 + er, proj


def _position(fit, t):
    """(x, y, h of the ball's bottom) of a fitted segment at times t."""
    A, b = _design(fit["model"], np.asarray(t, float) - fit["t0"], np.zeros(len(t)), fit.get("acc"))
    return np.einsum("nkp,p->nk", A, fit["theta"]) + b


def _link(segs, obs):
    """Refit each segment with continuity anchors from its neighbours (two Gauss-Seidel sweeps),
    re-choosing rolling vs ballistic. Mostly helps short hops whose height alone is ambiguous."""
    t = obs["t"]
    for _ in range(2):
        for k, (fit, idx) in enumerate(segs):
            if fit is None:
                continue
            anchors = []
            for step, side in ((-1, 0), (1, -1)):
                nb = k + step
                while 0 <= nb < len(segs) and segs[nb][0] is None:  # skip unfitted runs (e.g. one outlier)
                    nb += step
                if not 0 <= nb < len(segs):
                    continue
                nfit, nidx = segs[nb]
                t_near, t_own = t[nidx[-1 - side]], t[idx[side]]  # facing ends of the two segments
                if abs(t_own - t_near) > MAX_GAP_S:
                    continue
                tm = (t_near + t_own) / 2
                X = _position(nfit, [tm])[0]
                sig = 0.5 + 5.0 * abs(t_own - t_near)  # a kick changes velocity, not position
                if nfit["model"] == "ballistic":
                    sig = float(np.hypot(sig, _height_sigma(nfit, obs, nidx, [tm])[0]))
                anchors.append((tm, X, sig, side))
            fits = [f for f in (_fit(m, obs, idx, fit["theta"] if m == fit["model"] else None,
                                     [a[:3] for a in anchors]) for m in ("rolling", "ballistic")) if f]
            if fits:
                segs[k] = (min(fits, key=lambda f: f["cost"]), idx)
                segs[k][0]["anchors"] = anchors
    return segs


def _hidden_hop(fit, obs, idx):
    """Per-frame height a rolling segment could be hiding: for the whole segment and its first/last
    HOP_WINDOW detections (where bounces and chips start or end), the best ballistic fit (tied to the
    neighbouring segments) is admitted when its chi^2 is within 4 of the rolling fit on the same
    detections; the answer is max hypot(h, sigma_h) over admitted fits, at least the lift that moves
    the pixel by 1 sigma."""
    sig = _rolling_sigma(fit, obs, idx)
    X = _position(fit, obs["t"][idx]) + np.c_[np.zeros((len(idx), 2)), obs["off"][idx]]
    e2 = np.minimum(_residuals(obs, idx, X)[0], OUTLIER)
    anchors = fit.get("anchors", [])
    n = len(idx)
    windows = [(0, n, [a[:3] for a in anchors])]
    if n > HOP_WINDOW:
        windows += [(0, HOP_WINDOW, [a[:3] for a in anchors if a[3] == 0]),
                    (n - HOP_WINDOW, n, [a[:3] for a in anchors if a[3] == -1])]
    for a, b, anc in windows:
        alt = _fit("ballistic", obs, idx[a:b], anchors=anc)
        if alt is None or alt["chi2"] > e2[a:b].sum() + 4.0:
            continue
        h, _ = _height(alt, obs["t"][idx[a:b]])
        sig[a:b] = np.maximum(sig[a:b], np.hypot(np.maximum(h, 0), _height_sigma(alt, obs, idx[a:b])))
    return sig


def _height(fit, t):
    th, tau = fit["theta"], np.asarray(t) - fit["t0"]
    if fit["model"] == "rolling":
        return np.zeros_like(tau), np.zeros_like(tau)
    h = th[2] + th[5] * tau - G * tau ** 2 / 2 + (0.5 * fit["acc"][2] * tau ** 2 if fit.get("acc") is not None else 0)
    return h, np.c_[np.zeros((len(tau), 2)), np.ones(len(tau)), np.zeros((len(tau), 2)), tau]


def _rolling_sigma(fit, obs, idx):
    """Height resolution on a rolling track: the lift that would move the ball's pixel by 1 sigma."""
    P = obs["P"][idx]
    A, b = _design("rolling", obs["t"][idx] - fit["t0"], obs["off"][idx])
    q = np.einsum("njk,nk->nj", P, np.c_[np.einsum("nkp,p->nk", A, fit["theta"]) + b, np.ones(len(idx))])
    dq = P[:, :, 2]
    dproj = (dq[:, :2] - q[:, :2] / q[:, 2:3] * dq[:, 2:3]) / q[:, 2:3]
    sig_px = obs["sig"][idx] * np.sqrt(max(1.0, fit["chi2"] / max(fit["nres"] - fit["k"], 1)))
    return sig_px / np.maximum(np.linalg.norm(dproj, axis=1), 1e-6)


def _height_sigma(fit, obs, idx, t=None):
    """1-sigma height of a ballistic fit (at its observation times, or t) from the linearised covariance."""
    t = obs["t"][idx] if t is None else np.asarray(t, float)
    J = fit["J"]
    dof = max(fit["nres"] - fit["k"], 1)
    scale = max(1.0, fit["chi2"] / dof)
    try:
        cov = np.linalg.inv(J.T @ J) * scale
    except np.linalg.LinAlgError:
        return np.full(len(t), np.nan)
    _, g = _height(fit, t)
    return np.sqrt(np.maximum(np.einsum("np,pq,nq->n", g, cov, g), 0))


def _lands(prev, t):
    """The segment before t is a flight that reaches the grass by t: a bounce is a free breakpoint, like a kick."""
    return prev is not None and prev[0] is not None and prev[0]["model"] == "ballistic" and _height(prev[0], [t])[0][0] <= 0


def segment(obs, near):
    """Optimal segmentation of one shot's observations (dynamic programming with PELT pruning:
    a start whose segment already fits worse than the best split so far can never win later).
    Returns [(fit or None, idx)]; None marks a run too short to fit."""
    n = len(obs["t"])
    best = np.full(n + 1, np.inf)
    best[0], back, choice = 0.0, np.zeros(n + 1, int), [None] * (n + 1)
    warm, alive = {}, []  # warm: (start, model) -> theta of the segment one observation shorter
    for j in range(1, n + 1):
        if j > 1 and obs["t"][j - 1] - obs["t"][j - 2] > MAX_GAP_S:
            alive = []
        alive = [i for i in alive if j - i <= MAX_SEG] + [j - 1]
        chi = {}
        for i in alive:
            idx = np.arange(i, j)
            pen = 0.0 if i == 0 or near[i] or near[i - 1] or _lands(choice[i], obs["t"][i]) else BREAK
            if j - i < MIN_OBS:  # too short to judge: pay a flat price per observation
                fit, cost = None, OUTLIER * 0.75 * (j - i)
            else:
                fits = []
                for m in ("rolling", "ballistic"):
                    if warm.get((i, m), 0) is None:
                        continue  # this model already failed on a shorter run from i
                    fit = _fit(m, obs, idx, warm.get((i, m)))
                    warm[(i, m)] = None if fit is None else fit["theta"]
                    if fit:
                        fits.append(fit)
                if not fits:
                    chi[i] = np.inf
                    continue
                fit = min(fits, key=lambda f: f["cost"])
                cost, chi[i] = fit["cost"], fit["chi2"]
            if best[i] + cost + pen < best[j]:
                best[j], back[j], choice[j] = best[i] + cost + pen, i, (fit, idx)
        alive = [i for i in alive if best[i] + chi.get(i, 0.0) <= best[j]]
    segs, j = [], n
    while j > 0:
        segs.append(choice[j])
        j = back[j]
    return segs[::-1]


def _observations(frames, W, Hh):
    """Collect calibrated ball observations of one shot, plus the camera for each."""
    rows = []
    for f in frames:
        b, cal = f.get("ball"), f.get("calibration") or {}
        H = cal.get("homography")
        if not b or H is None or not cal.get("ok", True):
            continue
        cam = camera_from_homography(H, W, Hh)
        bbox = b.get("bbox")
        if bbox:
            x1, y1, x2, y2 = bbox
            u, off, r = ((x1 + x2) / 2, (y1 + y2) / 2), BALL_R, min(x2 - x1, y2 - y1) / 2
        elif b.get("image_bottom") or b.get("image"):  # v1: "image" is the box's bottom-centre
            u, off, r = tuple(b.get("image_bottom") or b["image"]), 0.0, np.nan
        else:
            continue
        rows.append((f, np.asarray(H, float), cam, u, off, r))
    return rows


def _shot_centre(cams):
    Cs = np.array([c["C"] for c in cams if c is not None])
    if not len(Cs):
        return None
    C = np.median(np.c_[Cs[:, :2], np.abs(Cs[:, 2])], axis=0)
    return C if C[2] > 1.0 else None  # a camera on the grass is a failed recovery


def _near_player(f, b, band=0.5):
    """Ball bottom within the lower `band` of a player's box (image): kicks, deflections, dribbles."""
    u = b.get("image_bottom") or b.get("image")
    if b.get("bbox"):
        u = ((b["bbox"][0] + b["bbox"][2]) / 2, b["bbox"][3])
    if not u:
        return False
    for p in f.get("players", []):
        x1, y1, x2, y2 = p["bbox"]
        h = y2 - y1
        if x1 - 0.3 * h <= u[0] <= x2 + 0.3 * h and y2 - band * h <= u[1] <= y2 + 0.1 * h:
            return True
    return False


def apply(analysis):
    """Annotate analysis["frames"][].ball in place (see module docstring); per-shot camera summary
    in analysis["ball3d"]."""
    W, Hh = analysis["video"]["width"], analysis["video"]["height"]
    by_shot = {}
    for f in analysis["frames"]:
        by_shot.setdefault(f.get("shot"), []).append(f)
    summary = {}
    for shot, frames in by_shot.items():
        info = _apply_shot(sorted(frames, key=lambda f: f["t"]), W, Hh)
        if info:
            summary[str(shot)] = info
    analysis["ball3d"] = {"shots": summary, "gravity": G, "ball_radius_m": BALL_R, "detection_sigma_px": SIGMA_DET_PX}


def _cal_px(frame, H, u):
    """This frame's calibration error (m) in pixels at the ball's image position."""
    err = (frame.get("calibration") or {}).get("reprojection_error_m") or 0.0
    g = np.linalg.solve(H, [u[0], u[1], 1.0])
    g = g[:2] / g[2]
    q = np.array([H @ [g[0] + dx, g[1] + dy, 1.0] for dx, dy in ((0, 0), (1, 0), (0, 1))])
    q = q[:, :2] / q[:, 2:3]
    px_per_m = np.sqrt(abs(np.linalg.det(np.c_[q[1] - q[0], q[2] - q[0]])))
    return err * px_per_m


def _radius_scale(segs, obs):
    """Detector boxes are padded/blurred: calibrate box radius / true radius on rolling stretches
    (known depth), so the size cue cannot invent height. None = not enough evidence -> cue off."""
    ratios = []
    for fit, idx in segs:
        if fit is None or fit["model"] != "rolling":
            continue
        X = _position(fit, obs["t"][idx]) + np.c_[np.zeros((len(idx), 2)), obs["off"][idx]]
        w = np.einsum("nk,nk->n", obs["P"][idx][:, 2, :3], X) + obs["P"][idx][:, 2, 3]
        pred = obs["f"][idx] * BALL_R * obs["s"][idx] / w
        ok = fit["inlier"] & np.isfinite(obs["r_box"][idx])
        ratios += list(obs["r_box"][idx][ok] / pred[ok])
    return float(np.median(ratios)) if len(ratios) >= MIN_OBS else None


def _apply_shot(frames, W, Hh):
    rows = _observations(frames, W, Hh)
    if not rows:
        return None
    C = _shot_centre([r[2] for r in rows])
    for f, H, *_ in rows:  # keep the naive projection, whatever happens next
        b = f["ball"]
        b.setdefault("ground_x", b.get("x"))
        b.setdefault("ground_y", b.get("y"))
        b.update(z=None, airborne=None, height_uncertainty_m=None, height_model="unfitted")
    if C is None:
        return None
    Ps = np.array([projection(H, C) for _, H, *_ in rows])
    fs = np.array([_focal_scale(P, W, Hh) for P in Ps])
    obs = {"t": np.array([r[0]["t"] for r in rows], float), "P": Ps, "u": np.array([r[3] for r in rows], float),
           "off": np.array([r[4] for r in rows]), "r_box": np.array([r[5] for r in rows], float),
           "f": fs[:, 0], "s": fs[:, 1]}
    obs["sig"] = np.array([np.hypot(SIGMA_DET_PX, _cal_px(r[0], r[1], r[3])) for r in rows])
    obs["r"] = np.full(len(rows), np.nan)  # segment on trajectories alone, then calibrate the size cue
    near = np.array([_near_player(r[0], r[0]["ball"]) for r in rows])
    segs = segment(obs, near)
    kappa = _radius_scale(segs, obs)
    if kappa is not None:
        obs["r"] = obs["r_box"] / kappa
    segs = _link(segs, obs)
    for f, *_ in rows:  # unfitted, but the ball is at someone's feet: on the grass, give or take a shin
        b = f["ball"]
        if b["height_model"] == "unfitted" and _near_player(f, b, band=AT_FEET_BAND):
            b.update(z=0.0, airborne=False, height_uncertainty_m=AT_FEET_SIGMA_M, height_model="at_feet")
    for seg in segs:
        fit, idx = seg
        if fit is None:
            continue
        h, _ = _height(fit, obs["t"][idx])
        h = np.maximum(h, 0.0)
        if fit["model"] == "ballistic":
            sig = _height_sigma(fit, obs, idx)
        else:  # height and depth are nearly degenerate in one view: ask how high a hop could hide here
            sig = _hidden_hop(fit, obs, idx)
        for k, i in enumerate(idx):
            f, H = rows[i][0], rows[i][1]
            b = f["ball"]
            P = Ps[i]
            hv = h[k] + obs["off"][i]  # height of the observed point (centre or bottom)
            Hz = np.c_[P[:, 0], P[:, 1], P[:, 2] * hv + P[:, 3]]
            g = np.linalg.solve(Hz, [*obs["u"][i], 1.0])
            if not fit["inlier"][k]:
                b["height_model"] = "outlier"  # detection disagrees with the trajectory: leave it naive
                continue
            cal_err = (f.get("calibration") or {}).get("reprojection_error_m") or 0.0
            dist = np.hypot(g[0] / g[2] - C[0], g[1] / g[2] - C[1])
            s_cal = cal_err * (C[2] - h[k]) / max(dist, 1.0) if fit["model"] == "ballistic" else 0.0
            s = float(np.hypot(sig[k], s_cal)) if np.isfinite(sig[k]) else None
            b.update(x=round(float(g[0] / g[2]), 2), y=round(float(g[1] / g[2]), 2), z=round(float(h[k]), 2),
                     airborne=bool(fit["model"] == "ballistic" and h[k] > 0.05),
                     height_uncertainty_m=None if s is None else round(s, 2), height_model=fit["model"])
    return {"camera_m": [round(float(v), 2) for v in C], "box_radius_scale": None if kappa is None else round(kappa, 3),
            "segments": [{"model": fit["model"], "t0": float(obs["t"][idx[0]]), "t1": float(obs["t"][idx[-1]])}
                         for fit, idx in segs if fit is not None]}

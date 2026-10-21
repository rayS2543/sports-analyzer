"""Cross-view calibration: calibrate a replay / close-up shot from the calibrated LIVE shot of the same play.

python -m var_cv.crossview --replay var_data/ID/23.0-28.0 --live var_data/ID/1.0-7.0 \
    --video var_data/ID/video.mp4 [--anchor LIVE_T:REPLAY_T] [--shot N] [--out DIR] [--no-lines]

Rewrites <replay>/analysis.json atomically (or <out>/analysis.json) and writes crossview.json next to it.
A close-up shows only parallel lines or an arc sliver, which cannot fix a homography alone. The live wide
shot of the same moment already knows every player's pitch position; the replay camera is solved from
those positions seen in the replay, plus whatever paint is visible, plus the replay's own camera motion.

Model. One broadcast camera that pans, tilts and zooms about a FIXED centre C (shared by the shot), with an
optional principal-point offset pp (shared, prior sigma SIGMA_PP_PX: digitally cropped replays) and per frame
a rotation R_t and focal length f_t. Pitch frame z points into the grass (the camera sits at z < 0).
Ground homography (pitch -> image): G_t = K_t R_t [e1 e2 -C],  K_t = [[f_t, 0, w/2 + px], [0, f_t, h/2 + py], [0, 0, 1]].
Time map: t_live = t_anchor_live + offset + s * (t_replay - t_anchor_replay); s = playback speed.

Joint robust least squares over the shot (Huber, iteratively re-weighted, sparse Jacobian):
  1. feet: a replay foot pixel (pose ankle midpoint, or box bottom-centre) vs the projection of that player's
     live pitch position at the synced time (raw_x/raw_y interpolated inside one live shot, never across a
     gap > MAX_LIVE_GAP_S). Whitened by Sigma_px = J (sigma_live^2 + SIGMA_BODY_M^2) J^T + SIGMA_PX^2 I, J = d pixel / d ground.
     s and offset are parameters, so the sync uncertainty enters the covariance directly.
  2. paint: chamfer distance of the projected pitch model to the painted-line centrelines (pitch._dist_map),
     each sample weighted so CORR_PX of matched line counts as one observation (pitch.CORR_PX).
  3. camera motion: track.camera_motion between consecutive samples vs K_t R_t R_{t-1}^T K_{t-1}^-1 on a 3x3
     image grid (soft: LK drift cannot accumulate).
  4. priors: pp ~ N(0, SIGMA_PP_PX); offset ~ N(0, SIGMA_OFFSET_S) around the anchor; flat priors with soft walls on
     camera height (1.5-60 m), C not inside the pitch, f (300-30000 px) and s (0.15-1.05).
Fixed-centre check first: every motion homography is fitted to the conjugate-rotation form K1 R K0^-1;
a median residual above MOVING_PX means the camera translates (steadicam, rail, spidercam): honest failure.

Sync and identities. Anchors are paired incidents (live fouls.json x replay fouls.json, opponents), or
--anchor. Seeds = one replay A/B pair <-> one live pair near the anchor (team-consistent). For every seed
and s on a grid (then offset and s refined), the shot's foot pixels are chained into one reference image
through the camera motion, a camera (C, R, f) is fitted to the seed, every other replay track is assigned to
a live player by team + geometry (Hungarian, gated, kept only when unambiguous: reid._unambiguous), refitted,
and scored by a capped chi^2 over ALL replay observations (SEARCH_SIGMA body heights per observation). A
materially different hypothesis (|ds| > 0.1 or camera centre > 5 m away) within chi^2 + 4 of the best = "sync ambiguous".

Acceptance (the bar for detected frames): Gauss-Newton covariance (robust variance factor >= 1), rank rule
(singular values > 1e-6 of the largest; null directions fail their frames "underdetermined"); per-frame 1-sigma
position error = covariance propagated to the ground point + 1 px localisation + the live calibration's own
error (a shared floor, it does not average out); pitch.region_error p90 <= 1 m over the visible grass; >= 2
matched players spanning >= 3 m, or 1 player plus a non-parallel line family; every leave-one-player-out
prediction within 2 sigma (median over that player's frames), at least one such check possible.
"""

import argparse
import json
import math
import os
import sys

CPU_THREADS = 4
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, str(CPU_THREADS))
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.optimize import least_squares  # noqa: E402
from scipy.optimize._numdiff import approx_derivative  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

from . import ball3d, pitch, reid, temporal, track  # noqa: E402

cv2.setNumThreads(0)  # this OpenCV parallelises with GCD: 0 is the only effective cap (see fouls.py)

SIGMA_PX = 2.0          # foot pixel localisation (pose ankles / box bottom)
SIGMA_BODY_M = 0.3      # replay foot point vs the live track's foot anchor (which foot, stance)
SIGMA_PP_PX = 15.0
SIGMA_OFFSET_S = 0.15
SIGMA_LINE_PX = 2.0     # floor of the per-observation chamfer noise
MOVING_PX = 2.0         # median conjugate-rotation residual above this = the camera translates
SEARCH_SIGMA = 0.25     # search residual unit: body heights (~0.45 m)
CAP = 9.0               # capped chi^2 per observation (3 sigma)
MAX_LIVE_GAP_S = 0.35   # live positions are interpolated only between samples this close
SEED_RADIUS_M = 8.0     # live seed players: within this of the anchor incident's players
MAX_SEEDS = 400
S_COARSE = np.round(np.arange(0.2, 1.0001, 0.1), 3)
D_GRID = (-0.15, -0.075, 0.0, 0.075, 0.15)
MAX_POSITION_ERROR_M = pitch.MAX_POSITION_ERROR_M
LOO_SIGMAS = 2.0
BODY_H = 1.75           # an upright player's box spans ~this height (m): apparent size fixes distance x zoom
SIGMA_LOGH = 0.15       # its spread (stance, pose box), as a log ratio
SEED_WINDOW_S = 0.6     # live seconds around the anchor where track identities are trusted for the start
MAX_FEET_CHI2 = 6.0     # mean capped chi^2 per replay foot observation (3 rows: x, y, apparent height)
MIN_MOTION_M = 2.0     # some matched player must move this far (live) during the replay to fix its speed
HUBER_K = 1.5           # IRLS Huber threshold on whitened residuals (priors are never down-weighted)
GRID = np.array([[u, v] for u in (0.1, 0.5, 0.9) for v in (0.1, 0.5, 0.9)])


# ------------------------------------------------------------------ camera model

def K_of(f, pp, size):
    w, h = size
    return np.array([[f, 0, w / 2 + pp[0]], [0, f, h / 2 + pp[1]], [0, 0, 1.0]])


def ground_h(C, R, f, pp, size):
    """pitch (x, y, 1) -> image homography of a camera at C (z < 0 above the grass) with rotation R."""
    return K_of(f, pp, size) @ np.c_[R[:, 0], R[:, 1], -R @ np.asarray(C, float)]


def look_at(C, target):
    fwd = (np.asarray(target, float) - C) / np.linalg.norm(np.asarray(target, float) - C)
    right = np.cross([0, 0, 1.0], fwd)
    right /= max(np.linalg.norm(right), 1e-9)
    return np.stack([right, np.cross(fwd, right), fwd])


def _rot(rv):
    return Rotation.from_rotvec(rv).as_matrix()


def conjugate_fit(M, size):
    """Best K1 R K0^-1 (pp at the centre) for a motion homography M. Returns (rms px, f0, f1)."""
    w, h = size
    Q = GRID * [w, h]
    target = pitch.project(M, Q)
    best = (np.inf, None, None)
    for f in (800.0, 1600.0, 3200.0, 6400.0):
        A = np.linalg.inv(K_of(f, (0, 0), size)) @ M @ K_of(f, (0, 0), size)
        U, _, Vt = np.linalg.svd(A)
        R0 = U @ Vt * np.sign(np.linalg.det(U @ Vt))

        def res(p):
            Mh = K_of(math.exp(p[4]), (0, 0), size) @ _rot(p[:3]) @ np.linalg.inv(K_of(math.exp(p[3]), (0, 0), size))
            return np.nan_to_num((pitch.project(Mh, Q) - target).ravel(), nan=1e3)

        r = least_squares(res, np.r_[Rotation.from_matrix(R0).as_rotvec(), math.log(f), math.log(f)],
                          x_scale=[0.01, 0.01, 0.01, 0.1, 0.1], max_nfev=200)
        rms = float(np.sqrt(np.mean(r.fun ** 2)))
        if rms < best[0]:
            best = (rms, math.exp(r.x[3]), math.exp(r.x[4]))
    return best


# ------------------------------------------------------------------ inputs

def live_tracks(analysis, shot):
    """{gid: {"team", "t", "xy", "sig"}} from the calibrated frames of one live shot (smoothed positions)."""
    rows, teams = {}, {}
    for f in analysis["frames"]:
        if f.get("shot") != shot or not (f.get("calibration") or {}).get("ok"):
            continue
        for p in f.get("players") or []:
            x, y = p.get("x"), p.get("y")  # smoothed: raw per-frame jitter would fake sync information
            if x is None:
                continue
            g = p.get("global_id", p["track_id"])
            rows.setdefault(g, []).append((f["t"], x, y, p.get("position_uncertainty_m") or 0.5))
            teams.setdefault(g, Counter())["ref" if p.get("role") == "referee" else p.get("team")] += 1
    out = {}
    for g, r in rows.items():
        r = np.array(sorted(r))
        out[g] = {"team": teams[g].most_common(1)[0][0], "t": r[:, 0], "xy": r[:, 1:3], "sig": r[:, 3]}
    return out


def live_at(tr, tau):
    """(xy Nx2, sig N) at times tau; NaN where the live track cannot be interpolated."""
    tau = np.atleast_1d(np.asarray(tau, float))
    t = tr["t"]
    xy = np.c_[np.interp(tau, t, tr["xy"][:, 0]), np.interp(tau, t, tr["xy"][:, 1])]
    sig = np.interp(tau, t, tr["sig"])
    j = np.clip(np.searchsorted(t, tau), 1, max(1, len(t) - 1))
    if len(t) > 1:
        gap_ok = (t[j] - t[j - 1]) <= MAX_LIVE_GAP_S
    else:
        gap_ok = np.ones(len(tau), bool)
    ok = (tau >= t[0] - 0.05) & (tau <= t[-1] + 0.05) & (gap_ok | (tau <= t[0]) | (tau >= t[-1]))
    xy[~ok] = np.nan
    sig[~ok] = np.nan
    return xy, sig


def team_ok(rt, lt):
    return rt is None or rt == lt


# ------------------------------------------------------------------ chain + reference camera (search)

def segments(motions):
    seg = [0]
    for M in motions[1:]:
        seg.append(seg[-1] + (M is None))
    return seg


def chain(motions, ref):
    """T[i]: image i -> image ref through the camera motion (None outside ref's motion-connected segment)."""
    seg = segments(motions)
    T = [None] * len(motions)
    T[ref] = np.eye(3)
    for i in range(ref + 1, len(motions)):
        if seg[i] != seg[ref]:
            break
        T[i] = T[i - 1] @ np.linalg.inv(motions[i])
    for i in range(ref - 1, -1, -1):
        if seg[i] != seg[ref]:
            break
        T[i] = T[i + 1] @ motions[i + 1]
    return T


def _ref_G(p, size):
    return ground_h(p[:3], _rot(p[3:6]), math.exp(p[6]), (0, 0), size)


def _height_px(p, X, size):
    """Apparent height (px) of an upright BODY_H player standing at X for reference camera p (pp at the centre)."""
    K, R, C = K_of(math.exp(p[6]), (0, 0), size), _rot(p[3:6]), p[:3]
    foot = (K @ R @ (np.c_[X, np.zeros(len(X))] - C).T).T
    head = (K @ R @ (np.c_[X, np.full(len(X), -BODY_H)] - C).T).T
    with np.errstate(divide="ignore", invalid="ignore"):
        d = foot[:, :2] / foot[:, 2:3] - head[:, :2] / head[:, 2:3]
    return np.where((foot[:, 2] > 0) & (head[:, 2] > 0), np.linalg.norm(d, axis=1), np.nan)


def _fit_ref(X, U, S, size, p0, fixed_C=None, Hh=None):
    """Camera (C, rotvec, log f) of the reference image from world points X and reference pixels U (Huber,
    residual unit S px) and, where Hh is finite, the players' apparent heights (log ratio / SIGMA_LOGH).
    fixed_C: solve rotation + focal only. Returns (params, robust cost)."""
    hm = np.isfinite(Hh) if Hh is not None else np.zeros(len(X), bool)

    def full(q):
        return np.r_[fixed_C, q] if fixed_C is not None else q

    def res(q):
        pq = full(q)
        r = (pitch.project(_ref_G(pq, size), X) - U) / S[:, None]
        rh = np.log(Hh[hm] / _height_px(pq, X[hm], size)) / SIGMA_LOGH if hm.any() else np.zeros(0)
        return np.nan_to_num(np.r_[r.ravel(), rh], nan=30.0)

    q0 = p0[3:] if fixed_C is not None else p0
    xs = [0.01, 0.01, 0.01, 0.05] if fixed_C is not None else [2, 2, 2, 0.01, 0.01, 0.01, 0.05]
    r = least_squares(res, q0, loss="huber", f_scale=1.0, x_scale=xs, max_nfev=80)
    return full(r.x), float(r.cost)


F_GRID = np.exp(np.linspace(math.log(300.0), math.log(20000.0), 18))


def centre_grid(c, dense=False):
    """Camera centres around ground point c (bearing x horizontal distance x height), outside the pitch."""
    if dense:
        b = np.radians(np.arange(0, 360, 4))
        dist = np.exp(np.arange(math.log(8.0), math.log(170.0), math.log(1.12)))
        hgt = np.exp(np.arange(math.log(1.5), math.log(55.0), math.log(1.35)))
    else:
        b = np.radians(np.arange(0, 360, 10))
        dist = np.exp(np.linspace(math.log(8.0), math.log(150.0), 10))
        hgt = np.array([2.0, 5.0, 10.0, 18.0, 30.0, 45.0])
    B, D, Hh = np.meshgrid(b, dist, hgt, indexing="ij")
    Cs = np.c_[c[0] + (D * np.cos(B)).ravel(), c[1] + (D * np.sin(B)).ravel(), -Hh.ravel()]
    inside = np.minimum.reduce([Cs[:, 0], pitch.LENGTH - Cs[:, 0], Cs[:, 1], pitch.WIDTH - Cs[:, 1]])
    return Cs[inside <= 1.0]


def grid_ref(X, U, S, size, fixed_C=None, keep=1, per_f=False, Cs=None, Hh=None):
    """Global start for the reference camera: every camera centre on a grid around the action (bearing x
    distance x height, outside the pitch) and every focal length on F_GRID; the rotation for each is the
    closed-form Wahba fit of image rays to world bearings. Score = capped chi^2 of the reprojected feet.
    Returns up to `keep` parameter vectors (C, rotvec, log f), best first."""
    X3 = np.c_[X, np.zeros(len(X))]
    c = X3.mean(0)
    if fixed_C is not None:
        Cs = np.asarray(fixed_C, float)[None]
    elif Cs is not None:
        Cs = np.asarray(Cs, float).reshape(-1, 3)
    else:
        Cs = centre_grid(c)
    w, h = size
    bear = X3[None] - Cs[:, None]                                        # nC x N x 3
    bear /= np.linalg.norm(bear, axis=2, keepdims=True)
    out = []
    best_c = np.full(len(Cs), np.inf)
    best_p = [None] * len(Cs)
    for f in F_GRID:
        ray = np.c_[(U - [w / 2, h / 2]) / f, np.ones(len(U))]
        ray /= np.linalg.norm(ray, axis=1, keepdims=True)
        M = np.einsum("nj,cnk->cjk", ray, bear)                        # sum r b^T, R b ~ r
        Uu, _, Vt = np.linalg.svd(M)
        dd = np.sign(np.linalg.det(Uu @ Vt))
        Uu[:, :, 2] *= dd[:, None]
        R = Uu @ Vt                                                     # nC x 3 x 3
        cam = np.einsum("cjk,cnk->cnj", R, bear)
        front = cam[:, :, 2] > 1e-3
        px = f * cam[:, :, :2] / np.where(front, cam[:, :, 2], 1.0)[:, :, None] + [w / 2, h / 2]
        d2 = np.sum((px - U) ** 2, axis=2) / S ** 2
        cost = np.where(front, np.minimum(d2, CAP), CAP).sum(1)
        if Hh is not None and np.isfinite(Hh).any():  # apparent size: distance against zoom
            hm = np.isfinite(Hh)
            headc = np.einsum("cjk,cnk->cnj", R, X3[None, hm] + [0, 0, -BODY_H] - Cs[:, None])
            ok = (headc[:, :, 2] > 1e-3) & front[:, hm]
            hp = f * np.linalg.norm(headc[:, :, :2] / np.where(ok, headc[:, :, 2], 1.0)[:, :, None]
                                    - cam[:, hm, :2] / np.where(ok, cam[:, hm, 2], 1.0)[:, :, None], axis=2)
            with np.errstate(divide="ignore", invalid="ignore"):
                rh = (np.log(Hh[hm] / hp) / SIGMA_LOGH) ** 2
            cost += np.where(ok & np.isfinite(rh), np.minimum(rh, CAP), CAP).sum(1)
        better = cost < best_c
        for k in np.where(better)[0]:
            best_c[k], best_p[k] = cost[k], (R[k], f)
        for k in np.argsort(cost)[:keep]:
            out.append((cost[k], Cs[k], R[k], f))
    if per_f:  # each camera centre with its best focal length
        order = np.argsort(best_c)[:keep]
        return [(float(best_c[k]), np.r_[Cs[k], Rotation.from_matrix(best_p[k][0]).as_rotvec(), math.log(best_p[k][1])])
                for k in order if best_p[k] is not None]
    out.sort(key=lambda r: r[0])
    return [np.r_[C, Rotation.from_matrix(R).as_rotvec(), math.log(f)] for _, C, R, f in out[:keep]]


def fit_ref(X, U, S, size, fixed_C=None, warm=None, Hh=None):
    """Reference camera from chained feet: grid start (and the warm start), then local robust least squares."""
    best = (None, np.inf)
    for p0 in ([warm] if warm is not None else []) + grid_ref(X, U, S, size, fixed_C, keep=3, Hh=Hh):
        p, c = _fit_ref(X, U, S, size, p0, fixed_C, Hh)
        if p[2] < -0.5 and c < best[1]:
            best = (p, c)
    return best


def _decompose_chain(T, Kref, size):
    """f and relative rotation of image i from the chain T (image i -> ref), pure rotation, pp at the centre."""
    A = np.linalg.inv(K_of(1.0, (0, 0), size)) @ np.linalg.inv(T) @ Kref  # = diag(f, f, 1) R_rel, up to scale
    n0, n1, n2 = np.linalg.norm(A, axis=1)
    f = (n0 + n1) / (2 * n2)
    B = np.diag([1 / f, 1 / f, 1.0]) @ A / n2
    U, _, Vt = np.linalg.svd(B)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R = -R
    return f, R


# ------------------------------------------------------------------ problem container

class Shot:
    """Replay shot: frames [{t, people: [{track, team, foot, h}], masks, motion}], size, live tracks, anchors."""

    def __init__(self, frames, size, live, use_lines=True):
        self.frames, self.size, self.live, self.use_lines = frames, size, live, use_lines
        self.t = np.array([f["t"] for f in frames])
        self.obs = [(i, p["track"], np.asarray(p["foot"], float), float(p["h"]), p.get("team"), bool(p.get("h_ok")))
                    for i, f in enumerate(frames) for p in f["people"]]
        self.tracks = {}
        for o, (i, k, *_rest) in enumerate(self.obs):
            self.tracks.setdefault(k, []).append(o)
        self.team = {k: Counter(self.obs[o][4] for o in os_ if self.obs[o][4]).most_common(1)[0][0]
                     if any(self.obs[o][4] for o in os_) else None for k, os_ in self.tracks.items()}
        self.motions = [f.get("motion") for f in frames]
        self.dmaps = None
        if use_lines:
            self.dmaps = [None if f.get("masks") is None else
                          {cap: pitch._dist_map(*f["masks"], cap) for cap in (50.0, 20.0)} for f in frames]


def _live_matrix(shot, tau_of):
    """Live positions of every gid at every replay frame: {gid: (xy n x 2, sig n)}."""
    tau = tau_of(shot.t)
    return {g: live_at(tr, tau) for g, tr in shot.live.items()}


def _d2(shot, obs_ids, gids, Lxy, Gs, U, scale=None):
    """Squared residuals in SEARCH units, (len(obs_ids), len(gids)); NaN where the live player is not observable.
    Lxy: {gid: (n frames x 2)}; Gs: one pitch->image homography, or one per frame; U: pixels per obs (same image)."""
    I = np.array([shot.obs[o][0] for o in obs_ids], int)
    S = np.array([SEARCH_SIGMA * shot.obs[o][3] * (1.0 if scale is None else scale[o]) for o in obs_ids])
    D = np.full((len(obs_ids), len(gids)), np.nan)
    if not len(obs_ids):
        return D
    for b, g in enumerate(gids):
        xy = Lxy[g][I]
        if isinstance(Gs, np.ndarray) and Gs.ndim == 2:
            q = pitch.project(Gs, xy)
        else:
            q = np.array([pitch.project(Gs[i], xy[j:j + 1])[0] if Gs[i] is not None else [np.nan, np.nan]
                          for j, i in enumerate(I)])
        D[:, b] = np.sum((q - U) ** 2, axis=1) / S ** 2
    return D


def _assign(shot, obs_ids, gids, D, fixed):
    """Team + geometry assignment of replay tracks to live gids. D: _d2 matrix for obs_ids x gids.
    fixed: {track: gid} kept as is. Unmatched observations cost CAP; a pair is kept only when the data
    clearly prefers it (reid._unambiguous: forbidding it raises the optimal total by chi^2 >= 4)."""
    tracks = sorted({shot.obs[o][1] for o in obs_ids} - set(fixed))
    cols = [b for b, g in enumerate(gids) if g not in set(fixed.values())]
    if not tracks or not cols:
        return {}
    k_of = np.array([shot.obs[o][1] for o in obs_ids])
    C = np.full((len(tracks), len(cols)), np.inf)
    for a, k in enumerate(tracks):
        rows = np.where(k_of == k)[0]
        if len(rows) < 2:
            continue
        for c, b in enumerate(cols):
            if not team_ok(shot.team[k], shot.live[gids[b]]["team"]):
                continue
            d2 = D[rows, b]
            cost = np.where(np.isfinite(d2), np.minimum(d2, CAP), CAP)
            if np.mean(cost) <= 4.0 and np.isfinite(d2).sum() >= 2:
                C[a, c] = cost.sum() - CAP * len(rows) + reid.UNMATCHED
    pairs = reid._unambiguous(C, reid._hungarian(C))
    return {tracks[a]: gids[cols[c]] for a, c in pairs}


def _score(shot, obs_ids, gids, D, pairs):
    """Capped chi^2 over every replay observation; unmatched or unobservable ones cost CAP."""
    col = {g: b for b, g in enumerate(gids)}
    tot = 0.0
    for r, o in enumerate(obs_ids):
        g = pairs.get(shot.obs[o][1])
        d2 = D[r, col[g]] if g is not None else np.nan
        tot += min(d2, CAP) if np.isfinite(d2) else CAP
    return tot


# ------------------------------------------------------------------ search

def _seed_points(shot, T, seg_obs, pairs, L, S_scale, frames=None):
    """Chained correspondences of the paired tracks: world X, reference pixels U, residual unit S, apparent
    height Hh in reference pixels (NaN where the box is not an upright, uncut body)."""
    X, U, S, Hh = [], [], [], []
    for o in seg_obs:
        i, k, u, hpx = shot.obs[o][:4]
        g = pairs.get(k)
        if g is None or (frames is not None and i not in frames):
            continue
        xy = L[g][0][i]
        if np.isnan(xy).any():
            continue
        X.append(xy)
        U.append(pitch.project(T[i], u)[0])
        S.append(SEARCH_SIGMA * hpx * S_scale[o])
        Hh.append(hpx * S_scale[o] if shot.obs[o][5] else np.nan)
    return np.array(X).reshape(-1, 2), np.array(U).reshape(-1, 2), np.array(S), np.array(Hh)


def _chain_scale(T, u):
    """Local scale of the chain homography at u (ref px per frame px)."""
    J = np.array([pitch.project(T, u + d)[0] - pitch.project(T, u - d)[0] for d in ([0.5, 0], [0, 0.5])])
    return math.sqrt(abs(np.linalg.det(J)))


def _near_anchor(shot, anchor, s, d):
    """Replay frames within SEED_WINDOW_S of live time of the anchor: where the paired identities are trusted."""
    tau = anchor["live_t"] + d + s * (shot.t - anchor["replay_t"])
    return set(np.where(np.abs(tau - anchor["live_t"]) <= SEED_WINDOW_S)[0])


def evaluate(shot, ctx, anchor, seed, s, d, warm=None):
    """Score one (seed identities, s, offset) hypothesis on the reference segment. Returns dict or None."""
    tau_of = lambda t: anchor["live_t"] + d + s * (np.asarray(t) - anchor["replay_t"])  # noqa: E731
    L = _live_matrix(shot, tau_of)
    Lxy = {g: v[0] for g, v in L.items()}
    T, seg_obs, Ss = ctx["T"], ctx["seg_obs"], ctx["scale"]
    gids = list(shot.live)
    U = np.array([ctx["uref"][o] for o in seg_obs]).reshape(-1, 2)
    pairs = dict(seed)
    near = _near_anchor(shot, anchor, s, d)
    X, Up, S, Hh = _seed_points(shot, T, seg_obs, pairs, L, Ss, near)
    if len(X) < 4 or np.ptp(X, axis=0).max() < 1.0:
        return None
    p, _ = fit_ref(X, Up, S, shot.size, warm=warm, Hh=Hh)
    if p is None:
        return None
    for _ in range(2):
        D = _d2(shot, seg_obs, gids, Lxy, _ref_G(p, shot.size), U, Ss)
        pairs = {**dict(seed), **_assign(shot, seg_obs, gids, D, dict(seed))}
        X, Up, S, Hh = _seed_points(shot, T, seg_obs, pairs, L, Ss, near)
        p2, _ = fit_ref(X, Up, S, shot.size, warm=p, Hh=Hh)
        if p2 is None:
            break
        p = p2
    D = _d2(shot, seg_obs, gids, Lxy, _ref_G(p, shot.size), U, Ss)
    return {"score": _score(shot, seg_obs, gids, D, pairs), "p": p, "s": float(s), "d": float(d), "pairs": pairs,
            "seed": seed, "anchor": anchor}


def seeds_for(shot, anchor, ref_seg_obs):
    """Seed identity pairs: one opponent pair seen in the replay near the anchor <-> one live pair near it."""
    tR, tL = anchor["replay_t"], anchor["live_t"]
    near_rep = Counter(shot.obs[o][1] for o in ref_seg_obs if abs(shot.t[shot.obs[o][0]] - tR) <= 0.25)
    n_obs = Counter(shot.obs[o][1] for o in ref_seg_obs)
    rep = [k for k in near_rep if n_obs[k] >= 3]
    pos = {g: live_at(tr, tL)[0][0] for g, tr in shot.live.items()}
    pos = {g: v for g, v in pos.items() if not np.isnan(v).any()}
    hint = [pos[g] for g in (anchor.get("live_pair") or []) if g in pos]
    if hint:
        c = np.mean(hint, axis=0)
        live = [g for g in pos if np.linalg.norm(pos[g] - c) <= SEED_RADIUS_M]
    else:
        live = list(pos)
    out = []
    rp = anchor.get("replay_pair") or []
    for a in range(len(rep)):
        for b in range(a + 1, len(rep)):
            ka, kb = rep[a], rep[b]
            for ga in live:
                for gb in live:
                    if ga == gb or not team_ok(shot.team[ka], shot.live[ga]["team"]) \
                            or not team_ok(shot.team[kb], shot.live[gb]["team"]):
                        continue
                    if shot.team[ka] is not None and shot.team[ka] == shot.team[kb]:
                        continue  # a contact anchor involves opponents
                    prio = (ka in rp) + (kb in rp) + (ga in (anchor.get("live_pair") or [])) + (gb in (anchor.get("live_pair") or []))
                    out.append((-prio, ((ka, ga), (kb, gb))))
    out.sort(key=lambda x: x[0])
    return [s for _, s in out[:MAX_SEEDS]]


def search(shot, anchors):
    """Every (anchor, seed, coarse speed) hypothesis, best search score first. Returns (hyps, ctx by ref, notes)."""
    notes = []
    best_all = []
    ctx_by_ref = {}
    for anchor in anchors:
        ref = int(np.argmin(np.abs(shot.t - anchor["replay_t"])))
        if ref not in ctx_by_ref:
            T = chain(shot.motions, ref)
            seg_obs = [o for o, ob in enumerate(shot.obs) if T[ob[0]] is not None]
            uref = {o: pitch.project(T[shot.obs[o][0]], shot.obs[o][2])[0] for o in seg_obs}
            scale = {o: _chain_scale(T[shot.obs[o][0]], shot.obs[o][2]) for o in seg_obs}
            ctx_by_ref[ref] = {"ref": ref, "T": T, "seg_obs": seg_obs, "uref": uref, "scale": scale}
        ctx = ctx_by_ref[ref]
        seeds = seeds_for(shot, anchor, ctx["seg_obs"])
        notes.append(f"anchor live {anchor['live_t']:.3f} s <-> replay {anchor['replay_t']:.3f} s "
                     f"({anchor.get('source', 'given')}): {len(seeds)} identity seeds")
        coarse = []
        for seed in seeds:
            warm = None
            for s in S_COARSE:
                r = evaluate(shot, ctx, anchor, seed, s, 0.0, warm)
                if r is not None:
                    r["ctx"] = ref
                    coarse.append(r)
                    warm = r["p"]
        fine = coarse
        best_all += fine
    best_all.sort(key=lambda r: r["score"])
    return best_all, ctx_by_ref, notes


# ------------------------------------------------------------------ joint fit

class Joint:
    """Robust joint fit of the fixed-centre PTZ replay camera, time map and per-frame rotation/zoom."""

    def __init__(self, shot, fit_idx, R0, f0, C, pp, s, d, anchor, matched, s_fixed=None, sigma_m=1.0):
        self.shot, self.idx = shot, list(fit_idx)
        self.pos = {i: k for k, i in enumerate(self.idx)}
        self.R0, self.f0 = [np.array(r) for r in R0], np.array(f0, float)
        self.anchor, self.matched, self.s_fixed, self.sigma_m = anchor, dict(matched), s_fixed, sigma_m
        self.x = np.r_[C, pp, s, d, np.zeros(4 * len(self.idx))]
        self.dropped = set()
        self.obs_gid = None  # per-observation live identity (set by _rematch): live tracks can swap people
        self.coarse = False  # coarse stage: feet + camera motion only, principal point held at the centre
        self.pp_free = False  # the principal point is freed only once the camera has settled (last round)

    # parameters -> cameras
    def cams(self, x):
        C, pp = x[:3], x[3:5]
        Rs, fs, Gs, Ks = [], [], [], []
        for k in range(len(self.idx)):
            q = x[7 + 4 * k: 11 + 4 * k]
            R = _rot(q[:3]) @ self.R0[k]
            f = self.f0[k] * math.exp(q[3])
            K = K_of(f, pp, self.shot.size)
            Rs.append(R), fs.append(f), Ks.append(K), Gs.append(K @ np.c_[R[:, 0], R[:, 1], -R @ C])
        return Rs, fs, Ks, Gs

    def tau(self, x, t):
        return self.anchor["live_t"] + x[6] + x[5] * (np.asarray(t) - self.anchor["replay_t"])

    def rebase(self):
        Rs, fs, _, _ = self.cams(self.x)
        self.R0, self.f0 = Rs, np.array(fs)
        self.x[7:] = 0.0

    def setup(self, cap):
        """Fix residual blocks and weights at the current estimate (one IRLS round)."""
        shot, x = self.shot, self.x
        Rs, fs, Ks, Gs = self.cams(x)
        w, h = shot.size
        # feet
        self.feet = []
        for o, (i, k, u, hpx, *_) in enumerate(shot.obs):
            g = self.obs_gid.get(o) if self.obs_gid is not None else self.matched.get(k)
            if g is None or i not in self.pos or o in self.dropped:
                continue
            xy, sig = live_at(shot.live[g], self.tau(x, shot.t[i]))
            if np.isnan(xy).any():
                continue
            G = Gs[self.pos[i]]
            p = G @ np.r_[xy[0], 1.0]
            if p[2] <= 0:
                continue
            uu = p[:2] / p[2]
            J = (G[:2, :2] - np.outer(uu, G[2, :2])) / p[2]
            Sig = J @ J.T * (sig[0] ** 2 + SIGMA_BODY_M ** 2) + SIGMA_PX ** 2 * np.eye(2)
            Wm = np.linalg.inv(np.linalg.cholesky(Sig))
            self.feet.append((o, i, g, u, Wm, hpx if shot.obs[o][5] else None))
        # paint
        self.lines = []
        if shot.use_lines and not self.coarse:
            for i in self.idx:
                dm = shot.dmaps[i]
                if dm is None:
                    continue
                G = Gs[self.pos[i]]
                img, ok = pitch._in_view(G, (h, w))
                region = shot.frames[i]["masks"][1]
                xi = np.clip(img[:, 0].astype(int), 0, w - 1)
                yi = np.clip(img[:, 1].astype(int), 0, h - 1)
                ok &= region[yi, xi] > 0
                if ok.sum() < 20:
                    continue
                pts, q, ids = pitch.SAMPLES[ok], img[ok], pitch.LINE_ID[ok]
                wts = np.zeros(len(pts))
                for lid in np.unique(ids):
                    sel = ids == lid
                    seg = np.linalg.norm(np.diff(q[sel], axis=0), axis=1)
                    n_eff = max(float(seg[seg < 10].sum()) / pitch.CORR_PX, 0.25)
                    wts[sel] = math.sqrt(n_eff / sel.sum())
                keep = np.arange(len(pts))[::max(1, len(pts) // 150)]
                wts = wts[keep] * math.sqrt(len(pts) / len(keep)) / SIGMA_LINE_PX
                self.lines.append((i, pts[keep], wts, dm[cap], ids[keep]))
        # motion
        self.motion = []
        Q = GRID * [w, h]
        for a, b in zip(self.idx, self.idx[1:]):
            M = shot.motions[b]
            if b == a + 1 and M is not None:
                self.motion.append((a, b, Q, pitch.project(M, Q)))
        self._sparsity()
        self.rw = np.ones(self.n_data)
        # no re-weighting: the capped distance maps bound paint outliers and feet beyond 4 sigma are dropped

    def huber_weights(self):
        """sqrt of the Huber IRLS weights of the data rows at the current estimate (for the covariance)."""
        rw, self.rw = self.rw, np.ones(self.n_data)
        r = self.residuals(self.x)[:self.n_data]
        self.rw = rw
        if self.n_feet:  # one weight per foot observation (its 2-vector norm)
            nf = np.repeat(np.linalg.norm(r[:self.n_feet].reshape(-1, 3), axis=1), 3)
            r = np.r_[nf, np.abs(r[self.n_feet:])]
        return np.sqrt(np.minimum(1.0, HUBER_K / np.maximum(np.abs(r), 1e-9)))

    def bounds(self):
        n = len(self.idx)
        lo = np.r_[-200.0, -150.0, -80.0, -150.0, -150.0, 0.15, -0.4, np.tile([-0.5, -0.5, -0.5, -1.0], n)]
        hi = np.r_[pitch.LENGTH + 200, pitch.WIDTH + 150, -1.0, 150.0, 150.0, 1.05, 0.4, np.tile([0.5, 0.5, 0.5, 1.0], n)]
        if self.s_fixed is not None:
            lo[5], hi[5] = self.s_fixed - 1e-6, self.s_fixed + 1e-6
        if self.coarse or not self.pp_free:
            lo[3:5], hi[3:5] = self.x[3:5] - 1e-6, self.x[3:5] + 1e-6
        return lo, np.maximum(hi, lo + 1e-9)

    def lsq(self, max_nfev):
        lo, hi = self.bounds()
        x0 = np.clip(self.x, lo + 1e-9, hi - 1e-9)
        # exact trust-region steps: the camera centre is coupled to every frame's rotation, and the inexact
        # (lsmr) sparse solver stalls along that coupling
        def jac(x):
            return approx_derivative(self.residuals, x, rel_step=2e-4, sparsity=self.sparse(), bounds=(lo, hi)).toarray()
        return least_squares(self.residuals, x0, jac=jac, bounds=(lo, hi), x_scale="jac", tr_solver="exact",
                             max_nfev=max_nfev, method="trf")

    def jacobian(self):
        return approx_derivative(self.residuals, self.x, rel_step=2e-4, sparsity=self.sparse()).toarray()

    def robust_cost(self):
        """chi^2 with the Huber loss on data residuals (unweighted), plain priors."""
        rw, self.rw = self.rw, np.ones(self.n_data)
        r = self.residuals(self.x)
        self.rw = rw
        d, pr = np.abs(r[:self.n_data]), r[self.n_data:]
        return float(np.sum(np.where(d <= HUBER_K, d ** 2, 2 * HUBER_K * d - HUBER_K ** 2)) + np.sum(pr ** 2))

    def score(self):
        """Comparable cost across hypotheses: Huber chi^2 of paint + camera motion + priors, and for EVERY replay
        observation in the fitted frames min(chi^2, CAP), unmatched or unobservable ones CAP."""
        rw, self.rw = self.rw, np.ones(self.n_data)
        r = self.residuals(self.x)
        self.rw = rw
        f2 = np.sum(r[:self.n_feet].reshape(-1, 3) ** 2, axis=1)
        d, pr = np.abs(r[self.n_feet:self.n_data]), r[self.n_data:]
        n_obs = sum(1 for ob in self.shot.obs if ob[0] in self.pos)
        return float(np.minimum(f2, CAP).sum() + CAP * (n_obs - len(f2))
                     + np.sum(np.where(d <= HUBER_K, d ** 2, 2 * HUBER_K * d - HUBER_K ** 2)) + np.sum(pr ** 2))

    def s_sigma(self):
        if not hasattr(self, "_s_sig"):
            cov = self.covariance()[0]
            self._s_sig = math.sqrt(max(cov[5, 5], 0)) if cov is not None else np.inf
        return self._s_sig

    def _sparsity(self):
        """Residual-row layout (column sets); the sparse matrix itself is built on demand (sparse())."""
        shared = [0, 1, 2, 3, 4]
        fr = lambda i: list(range(7 + 4 * self.pos[i], 11 + 4 * self.pos[i]))  # noqa: E731
        blocks = [(shared + [5, 6] + fr(i), 3) for _, i, *_ in self.feet]
        blocks += [(shared + fr(i), len(pts)) for i, pts, *_ in self.lines]
        blocks += [([3, 4] + fr(a) + fr(b), 2 * len(Q)) for a, b, Q, _ in self.motion]
        self.n_feet = 3 * len(self.feet)
        self.n_data = sum(k for _, k in blocks)
        blocks += [([3], 1), ([4], 1), ([0, 1], 1), ([6], 1)] + [(fr(i), 1) for i in self.idx]
        self._blocks, self._S = blocks, None

    def sparse(self):
        if self._S is None:
            rows, cols, r0 = [], [], 0
            for cs, k in self._blocks:
                rr = np.repeat(np.arange(r0, r0 + k), len(cs))
                rows.append(rr), cols.append(np.tile(cs, k))
                r0 += k
            from scipy.sparse import csr_matrix
            self._S = csr_matrix((np.ones(sum(len(r) for r in rows), int), (np.concatenate(rows), np.concatenate(cols))),
                                 shape=(r0, 7 + 4 * len(self.idx)))
        return self._S

    def residuals(self, x):
        shot = self.shot
        Rs, fs, Ks, Gs = self.cams(x)
        out = []
        for o, i, g, u, Wm, hpx in self.feet:
            xy, _ = live_at(shot.live[g], self.tau(x, shot.t[i]))
            k = self.pos[i]
            q = pitch.project(Gs[k], xy)[0]
            if not (np.isfinite(q).all() and np.isfinite(xy).all()):
                out.append(np.array([30.0, 30.0, 0.0]))
                continue
            rh = 0.0
            if hpx is not None:  # apparent height of an upright player: distance against zoom
                head = Ks[k] @ Rs[k] @ (np.r_[xy[0], -BODY_H] - x[:3])
                hp = np.linalg.norm(head[:2] / head[2] - q) if head[2] > 0 else np.nan
                rh = math.log(hpx / hp) / SIGMA_LOGH if np.isfinite(hp) and hp > 0 else 30.0
            out.append(np.r_[Wm @ (q - u), rh])
        out = [np.concatenate(out)] if out else []
        for i, pts, wts, dm, _ in self.lines:
            out.append(pitch._sample(dm, pitch.project(Gs[self.pos[i]], pts)).astype(float) * wts)
        for a, b, Q, target in self.motion:
            ka, kb = self.pos[a], self.pos[b]
            Mh = Ks[kb] @ Rs[kb] @ Rs[ka].T @ np.linalg.inv(Ks[ka])
            out.append(np.nan_to_num((pitch.project(Mh, Q) - target).ravel(), nan=1e3) / self.sigma_m)
        data = np.concatenate(out) if out else np.zeros(0)
        if len(data) == len(getattr(self, "rw", ())):
            data = data * self.rw
        C, pp, d = x[:3], x[3:5], x[6]
        inside = min(C[0], pitch.LENGTH - C[0], C[1], pitch.WIDTH - C[1])
        out = [data, np.array([pp[0] / SIGMA_PP_PX, pp[1] / SIGMA_PP_PX, max(0.0, inside - 1.0), d / SIGMA_OFFSET_S])]
        out.append(np.array([max(0.0, math.log(300.0 / f)) / 0.05 + max(0.0, math.log(f / 30000.0)) / 0.05 for f in fs]))
        return np.concatenate(out)

    def solve(self, cap, max_nfev=60):
        self.setup(cap)
        r = self.lsq(max_nfev)
        self.x, self.res = r.x, r
        self.rebase()
        return r

    def run(self, rounds=3, rematch=None, max_nfev=100):
        for k in range(rounds):
            self.pp_free = k == rounds - 1
            self.solve(50.0 if k == 0 and rounds > 1 else 20.0, max_nfev)
            if rematch is not None and k == 0:
                rematch(self)
        # outlier truncation: feet observations beyond 4 sigma are dropped (usually a swapped close-up track)
        self.rw = np.ones(self.n_data)
        r = self.residuals(self.x)[:self.n_feet].reshape(-1, 3)
        bad = {self.feet[j][0] for j in np.where(np.linalg.norm(r, axis=1) > 4.0)[0]}
        if bad:
            self.dropped |= bad
            self.solve(20.0, max_nfev)
        self.setup(20.0)
        return self

    # ---------------- uncertainty
    def covariance(self):
        """(cov, ok_frames set, underdetermined frames set). Null directions fail their frames."""
        rw = self.rw
        self.rw = np.ones(self.n_data)
        rf = self.residuals(self.x)[:self.n_feet].reshape(-1, 3)[:, :2].ravel()
        self.rw = np.ones(self.n_data)
        J = self.jacobian()
        self.rw = rw
        var = max(1.0, float(np.median(rf ** 2) / 0.455)) if len(rf) else 1.0
        cols = list(range(J.shape[1]))
        bad = set()
        for _ in range(len(self.idx) + 1):
            Js = J[:, cols]
            _, sv, vt = np.linalg.svd(Js, full_matrices=False)
            if sv[-1] > sv[0] * 1e-6:
                break
            null = vt[sv <= sv[0] * 1e-6]
            weight = np.abs(null).max(0)
            hit = [cols[c] for c in np.where(weight > 0.1)[0]]
            if any(c < 7 for c in hit):
                return None, set(), set(self.idx)
            frames = {self.idx[(c - 7) // 4] for c in hit}
            bad |= frames
            drop = {7 + 4 * self.pos[i] + j for i in frames for j in range(4)}
            rows = np.abs(J[:, sorted(drop)]).sum(1) == 0
            J = J[rows]
            cols = [c for c in cols if c not in drop]
        else:
            return None, set(), set(self.idx)
        cov = np.zeros((self.x.size, self.x.size))
        sub = vt.T @ np.diag(1 / sv ** 2) @ vt * var
        cov[np.ix_(cols, cols)] = sub
        self.var_factor = var
        return cov, set(self.idx) - bad, bad

    def sigma_fn(self, cov, i, floor_m):
        """Gauss-Newton error propagated to the ground point, the 1 px localisation, the live floor, and the
        profile floor: a converged alternative fit d chi^2 worse that moves this point by e counts as
        e / sqrt(max(d chi^2, 1)) sigma (the curvature alone under-reports a flat, rough cost ridge)."""
        base = self._sigma_gn(cov, i, floor_m)
        alts = [(dc, np.linalg.inv(f.cams(f.x)[3][f.pos[i]])) for dc, f in getattr(self, "alternatives", [])
                if i in f.pos]
        if not alts:
            return base
        H0 = np.linalg.inv(self.cams(self.x)[3][self.pos[i]])

        def sigma(points):
            points = np.asarray(points, float).reshape(-1, 2)
            g0 = pitch.project(H0, points)
            prof = np.zeros(len(points))
            for dc, Hk in alts:
                e2 = np.sum((pitch.project(Hk, points) - g0) ** 2, axis=1) / max(dc, 1.0)
                prof = np.maximum(prof, np.nan_to_num(e2, nan=np.inf))
            return np.sqrt(base(points) ** 2 + prof)
        return sigma

    def _sigma_gn(self, cov, i, floor_m):
        """callable(image points) -> 1-sigma ground position error (m) for replay frame i."""
        k = self.pos[i]
        pidx = [0, 1, 2, 3, 4] + list(range(7 + 4 * k, 11 + 4 * k))
        steps = [0.05, 0.05, 0.05, 1.0, 1.0, 1e-4, 1e-4, 1e-4, 1e-4]
        Cs = cov[np.ix_(pidx, pidx)]
        Ginv = [np.linalg.inv(self.cams(self.x)[3][k])]
        Gp, Gm = [], []
        for j, st in zip(pidx, steps):
            e = np.zeros_like(self.x)
            e[j] = st
            Gp.append(np.linalg.inv(self.cams(self.x + e)[3][k]))
            Gm.append(np.linalg.inv(self.cams(self.x - e)[3][k]))
        H0 = Ginv[0]

        def sigma(points):
            points = np.asarray(points, float).reshape(-1, 2)
            Jp = np.stack([(pitch.project(a, points) - pitch.project(b, points)) / (2 * st)
                           for a, b, st in zip(Gp, Gm, steps)], axis=2)
            v = np.einsum("nik,kl,nil->n", Jp, Cs, Jp)
            loc = pitch.m_per_px(H0, points) ** 2
            return np.sqrt(np.maximum(v, 0) + loc + floor_m ** 2)
        return sigma


# ------------------------------------------------------------------ solve

def _fail_all(n, why, report):
    report.update(status="failed", failure=why)
    report["frame_results"] = [{"ok": False, "failure": why} for _ in range(n)]
    return report


def _init_cams(shot, hyp, ctx, p):
    """Initial per-frame cameras from reference camera p = (C, rotvec, log f): chain decomposition in the
    reference segment, a C-fixed fit elsewhere."""
    size, n = shot.size, len(shot.frames)
    C, Rref, fref = p[:3], _rot(p[3:6]), math.exp(p[6])
    Kref = K_of(fref, (0, 0), size)
    R0, f0 = {}, {}
    for i, T in enumerate(ctx["T"]):
        if T is not None:
            f, Rrel = _decompose_chain(T, Kref, size)
            R0[i], f0[i] = Rrel @ Rref, f
    seg = segments(shot.motions)
    anchor, matched = hyp["anchor"], hyp["pairs"]
    L = _live_matrix(shot, lambda t: anchor["live_t"] + hyp["d"] + hyp["s"] * (np.asarray(t) - anchor["replay_t"]))
    for sid in sorted(set(seg) - {seg[ctx["ref"]]}):
        members = [i for i in range(n) if seg[i] == sid]
        T = chain(shot.motions, members[len(members) // 2])
        X, U, S = [], [], []
        for o, (i, k, u, hpx, *_) in enumerate(shot.obs):
            if seg[i] == sid and k in matched and not np.isnan(L[matched[k]][0][i]).any():
                X.append(L[matched[k]][0][i]), U.append(pitch.project(T[i], u)[0]), S.append(SEARCH_SIGMA * hpx)
        if len(X) < 2:
            continue
        q, _ = fit_ref(np.array(X), np.array(U), np.array(S), size, fixed_C=C)
        if q is None:
            continue
        Kseg = K_of(math.exp(q[6]), (0, 0), size)
        for i in members:
            f, Rrel = _decompose_chain(T[i], Kseg, size)
            R0[i], f0[i] = Rrel @ _rot(q[3:6]), f
    return sorted(R0), R0, f0, C


def _joint_init(shot, hyp, ctx, p, sigma_m):
    idx, R0, f0, C = _init_cams(shot, hyp, ctx, p)
    if not idx or C[2] > -0.5:
        return None
    jf = Joint(shot, idx, [R0[i] for i in idx], [f0[i] for i in idx], C, (0.0, 0.0), hyp["s"], hyp["d"],
               hyp["anchor"], hyp["pairs"], sigma_m=sigma_m)
    jf.seeds, jf.hyp = dict(hyp["seed"]), hyp
    return jf


Q = 4  # paint screening resolution: 1/4


def _paint(shot, i):
    """Quarter-resolution paint of frame i: (distance map to paint centrelines, paint points, grass region)."""
    if not hasattr(shot, "_paint"):
        shot._paint = {}
    if i not in shot._paint:
        m = shot.frames[i].get("masks")
        if m is None:
            shot._paint[i] = None
        else:
            sk = pitch._skeleton(m[0])
            sk[m[1] == 0] = 0
            h, w = sk.shape
            skq = cv2.resize(cv2.dilate(sk, np.ones((Q, Q), np.uint8)), (w // Q, h // Q), interpolation=cv2.INTER_AREA)
            skq = (skq > 0).astype(np.uint8) * 255
            dist = np.minimum(cv2.distanceTransform(255 - skq, cv2.DIST_L2, 3), 12.0)
            pts = np.argwhere(skq > 0)[:, ::-1].astype(np.float32)
            pts = pts[:: max(1, len(pts) // 300)]
            reg = cv2.resize(m[1], (w // Q, h // Q), interpolation=cv2.INTER_NEAREST)
            shot._paint[i] = (dist, pts, reg)
    return shot._paint[i]


def paint_cost(shot, i, G):
    """Two-sided chamfer (quarter-res px, capped at 12 = 48 px) between the projected pitch model and the
    painted lines of frame i: model samples on grass with no paint near, and paint with no model line near."""
    pq = _paint(shot, i)
    if pq is None:
        return 0.0
    dist, pts, reg = pq
    h, w = dist.shape
    S = np.diag([1.0 / Q, 1.0 / Q, 1.0]) @ G
    img = pitch.project(S, pitch.SAMPLES[::4])
    ok = np.isfinite(img).all(1) & (img[:, 0] >= 0) & (img[:, 0] < w - 1) & (img[:, 1] >= 0) & (img[:, 1] < h - 1)
    q = img[ok]
    on = reg[q[:, 1].astype(int), q[:, 0].astype(int)] > 0
    q = q[on]
    a = float(np.mean(pitch._sample(dist, q.astype(np.float32)) ** 2)) * min(1.0, len(q) / 50) if len(q) else 0.0
    if not len(pts):
        return a
    model = np.zeros((h, w), np.uint8)
    for line in pitch.LINES:
        pl = pitch.project(S, line)
        pl = pl[np.isfinite(pl).all(1) & (np.abs(pl) < 1e4).all(1)]
        if len(pl) > 1:
            cv2.polylines(model, [pl.astype(np.int32)], False, 255, 1)
    dm = np.minimum(cv2.distanceTransform(255 - model, cv2.DIST_L2, 3), 12.0)
    b = float(np.mean(pitch._sample(dm, pts) ** 2))
    return a + b


def screen(shot, hyp, ctx, keep=2, n_feet=200, n_frames=4, n_starts=4):
    """Candidate reference cameras for one hypothesis: every camera centre on the grid (grid_ref) ranked by
    its feet fit, then the best n_feet re-ranked with the paint of n_frames frames spread over the reference
    segment (a small patch of grass hardly separates a far camera + long lens from a near one + wide lens;
    the paint does). Returns [(cost, p)] best first."""
    L = _live_matrix(shot, lambda t: hyp["anchor"]["live_t"] + hyp["d"] + hyp["s"] * (np.asarray(t) - hyp["anchor"]["replay_t"]))
    X, U, S, Hh = _seed_points(shot, ctx["T"], ctx["seg_obs"], hyp["pairs"], L, ctx["scale"],
                               _near_anchor(shot, hyp["anchor"], hyp["s"], hyp["d"]))
    if len(X) < 4:
        return []
    seg = [i for i, T in enumerate(ctx["T"]) if T is not None and _paint(shot, i) is not None]
    frames = [seg[k] for k in np.linspace(0, len(seg) - 1, min(n_frames, len(seg))).astype(int)] if seg else []

    def scored(cands):
        out = []
        for _, p in cands:
            p, fc = _fit_ref(X, U, S, shot.size, p, fixed_C=p[:3], Hh=Hh)  # focal + rotation for this centre
            fc *= 2
            Kref = K_of(math.exp(p[6]), (0, 0), shot.size)
            lc = 0.0
            for i in frames:
                f, Rrel = _decompose_chain(ctx["T"][i], Kref, shot.size)
                lc += paint_cost(shot, i, ground_h(p[:3], Rrel @ _rot(p[3:6]), f, (0, 0), shot.size))
            out.append((fc + 10.0 * lc / max(1, len(frames)), p))
        return out

    out = scored(grid_ref(X, U, S, shot.size, keep=n_feet, per_f=True, Cs=centre_grid(np.r_[X.mean(0), 0.0], dense=True), Hh=Hh))
    out.sort(key=lambda r: r[0])
    # second level: a 1.5 m grid (and +-30% height) around the best few coarse centres
    fine = []
    for _, p in out[:4]:
        dx = np.arange(-4.5, 4.51, 1.5)
        Cs = [p[:3] + [a, b, 0.0] for a in dx for b in dx]
        Cs = [c * [1, 1, k] for c in Cs for k in (0.7, 1.0, 1.4)]
        fine += scored(grid_ref(X, U, S, shot.size, keep=30, per_f=True, Cs=Cs, Hh=Hh))
    out += fine
    out.sort(key=lambda r: r[0])
    starts = []
    for c, p in out:
        if all(np.linalg.norm(p[:3] - q[:3]) > 2.0 for _, q in starts):
            starts.append((c, p))
        if len(starts) == n_starts:
            break
    fitted = [mini_fit(shot, ctx, X, U, S, p, hyp, L, Hh) for _, p in starts]
    fitted.sort(key=lambda r: r[0])
    picked = []
    for c, p in fitted:
        if all(np.linalg.norm(p[:3] - q[:3]) > 1.0 for _, q in picked):
            picked.append((c, p))
        if len(picked) == keep:
            break
    return picked


def mini_fit(shot, ctx, X, U, S, p0, hyp, L, Hh, n_frames=10):
    """Hard-chained fit of the reference camera (C, R_ref, f_ref: 7 parameters; every frame's camera follows
    through the camera motion) to the chained feet and the paint of up to n_frames frames, coarse to fine.
    Coupling all frames through one camera gives the paint a far wider capture range than per-frame fits.
    Returns (robust chi^2, p)."""
    size = shot.size
    seg = [i for i, T in enumerate(ctx["T"]) if T is not None]
    lf = [i for i in seg if shot.dmaps is not None and shot.dmaps[i] is not None]
    lf = [lf[k] for k in np.linspace(0, len(lf) - 1, min(n_frames, len(lf))).astype(int)] if lf else []
    Sf = S * 0.5  # SEARCH_SIGMA/2 body heights ~ 0.22 m

    def cams(p):
        Kref = K_of(math.exp(p[6]), (0, 0), size)
        out = {}
        for i in lf:
            f, Rrel = _decompose_chain(ctx["T"][i], Kref, size)
            out[i] = ground_h(p[:3], Rrel @ _rot(p[3:6]), f, (0, 0), size)
        return out

    def setup(p, cap):
        Gs = cams(p)
        st = []
        w, h = size
        for i in lf:
            img, ok = pitch._in_view(Gs[i], (h, w))
            region = shot.frames[i]["masks"][1]
            xi = np.clip(np.nan_to_num(img[:, 0]).astype(int), 0, w - 1)
            yi = np.clip(np.nan_to_num(img[:, 1]).astype(int), 0, h - 1)
            ok &= region[yi, xi] > 0
            pts = pitch.SAMPLES[ok][::max(1, int(ok.sum()) // 200)]
            if len(pts):
                q = pitch.project(Gs[i], pts)
                seg_len = np.linalg.norm(np.diff(q, axis=0), axis=1)
                n_eff = max(float(seg_len[seg_len < 40].sum()) / pitch.CORR_PX, 0.25)
                st.append((i, pts, math.sqrt(n_eff / len(pts)) / SIGMA_LINE_PX, shot.dmaps[i][cap]))
        return st

    hm = np.isfinite(Hh)

    def res(p, st):
        r = [(pitch.project(_ref_G(p, size), X) - U).ravel() / np.repeat(Sf, 2),
             np.log(Hh[hm] / _height_px(p, X[hm], size)) / SIGMA_LOGH]
        Gs = cams(p)
        for i, pts, wgt, dm in st:
            r.append(pitch._sample(dm, pitch.project(Gs[i], pts)).astype(float) * wgt)
        return np.nan_to_num(np.concatenate(r), nan=30.0)

    p = np.asarray(p0, float)
    for cap in ((50.0, 20.0) if lf else (20.0,)):
        st = setup(p, cap)
        r = least_squares(res, p, args=(st,), loss="huber", f_scale=1.5, x_scale=[1, 1, 1, 0.01, 0.01, 0.01, 0.03],
                          max_nfev=60, diff_step=1e-4)
        p = r.x
    # comparable across hypotheses: identities re-assigned with this camera, every chained replay
    # observation counts (unmatched ones CAP)
    G = _ref_G(p, size)
    seg_obs, gids = ctx["seg_obs"], list(shot.live)
    Lxy = {g: v[0] for g, v in L.items()}
    Uo = np.array([ctx["uref"][o] for o in seg_obs]).reshape(-1, 2)
    D = _d2(shot, seg_obs, gids, Lxy, G, Uo, ctx["scale"])
    seeds = dict(hyp["seed"])
    pairs = {**seeds, **_assign(shot, seg_obs, gids, D, seeds)}
    tot = _score(shot, seg_obs, gids, D, pairs)
    lines = res(p, st)[len(X) * 2 + int(hm.sum()):]
    a = np.abs(lines)
    tot += float(np.sum(np.where(a <= 1.5, a ** 2, 3.0 * a - 2.25)))
    return tot, p


def _rematch(jf):
    """Re-assign the non-seed replay tracks with the joint fit's own per-frame cameras and time map."""
    shot = jf.shot
    Gs = jf.cams(jf.x)[3]
    Gf = [Gs[jf.pos[i]] if i in jf.pos else None for i in range(len(shot.frames))]
    Lxy = {g: v[0] for g, v in _live_matrix(shot, lambda t: jf.tau(jf.x, t)).items()}
    obs_ids = [o for o, ob in enumerate(shot.obs) if ob[0] in jf.pos]
    gids = list(shot.live)
    U = np.array([shot.obs[o][2] for o in obs_ids]).reshape(-1, 2)
    D = _d2(shot, obs_ids, gids, Lxy, Gf, U)
    jf.matched = {**jf.seeds, **_assign(shot, obs_ids, gids, D, jf.seeds)}
    # each observation to the live player its camera puts it on, when that is clear: a live track that
    # swaps two people mid-shot (tangles) then still contributes the right positions
    jf.obs_gid = {}
    for r, o in enumerate(obs_ids):
        team = shot.obs[o][4]
        d2 = np.array([D[r, b] if team_ok(team, shot.live[g]["team"]) else np.nan for b, g in enumerate(gids)])
        d2 = np.where(np.isfinite(d2), d2, np.inf)
        order = np.argsort(d2)
        if np.isfinite(d2[order[0]]) and d2[order[0]] <= 4.0 and (len(order) < 2 or d2[order[1]] - d2[order[0]] >= 4.0):
            jf.obs_gid[o] = gids[order[0]]


def fit_shot(shot, hyps, ctxs, sigma_m, notes):
    """Search hypotheses -> joint fits. Each (seed, speed) hypothesis is screened at several camera distances
    (a small patch of grass hardly separates a far camera + long lens from a near one + wide lens; the paint
    and the camera motion do) by its cost at the starting point; the best few are fitted fully.
    Returns (best fit, rival fit with a materially different speed or None)."""
    seeds = []
    for h in hyps:
        if h["seed"] not in seeds:
            seeds.append(h["seed"])
    # the best seed at every 0.1 of speed (the search's own speed ranking is weak: its camera is crude),
    # and the runner-up seed's best hypothesis
    cands, seen = [], set()
    for h in hyps:
        key = (h["seed"], round(h["s"], 1))
        if h["seed"] == seeds[0] and key not in seen:
            seen.add(key)
            cands.append(h)
    if len(seeds) > 1:
        cands.append(next(h for h in hyps if h["seed"] == seeds[1]))
    # cands are in search-score order. Joint fits (the only comparable score) start from the best screened
    # camera of: the 3 best-searched hypotheses, the best screened camera overall, and the best one at a
    # materially different speed (the rival for the ambiguity rule).
    scr = []
    for rank, h in enumerate(cands):
        for c, p0 in screen(shot, h, ctxs[h["ctx"]], keep=1):
            scr.append((c, h, p0, rank))
    if not scr:
        return None, None
    picks = [r for r in scr if r[3] < 3]
    best_scr = min(scr, key=lambda r: r[0])
    if best_scr not in picks:
        picks.append(best_scr)
    other = min((r for r in scr if all(abs(r[1]["s"] - q[1]["s"]) > 0.1 for q in picks)), key=lambda r: r[0], default=None)
    if other is not None:
        picks.append(other)
    picks = [r[:3] for r in picks]
    fits = []
    for sc, h, p0 in picks:
        jf = _joint_init(shot, h, ctxs[h["ctx"]], p0, sigma_m)
        if jf is None:
            continue
        jf.run(rematch=_rematch)
        jf.final_score = jf.score()
        fits.append(jf)
        notes.append(f"joint fit from s={h['s']:.3f}, camera {np.round(p0[:3], 1).tolist()}: s={jf.x[5]:.3f}, "
                     f"C={np.round(jf.x[:3], 1).tolist()}, chi^2 {jf.final_score:.1f}")
    if not fits:
        return None, None
    fits.sort(key=lambda f: f.final_score)
    best = fits[0]
    # walk the camera centre along its least-determined direction (distance trades against zoom): the fit
    # can stall on that ridge; restarts a few metres either side keep the lowest chi^2
    cov = best.covariance()[0]
    if cov is not None:
        for step in np.r_[np.eye(3), -np.eye(3)] * 1.5:
            jf = Joint(shot, best.idx, best.R0, best.f0, best.x[:3] + step, best.x[3:5], best.x[5], best.x[6],
                       best.anchor, best.matched, sigma_m=best.sigma_m)
            jf.x[7:] = best.x[7:]
            jf.seeds, jf.hyp = best.seeds, best.hyp
            jf.run(rounds=1, max_nfev=60)
            jf.final_score = jf.score()
            notes.append(f"restart C{np.round(step, 1).tolist()} m: C={np.round(jf.x[:3], 2).tolist()}, s={jf.x[5]:.3f}, "
                         f"chi^2 {jf.final_score:.1f}")
            fits.append(jf)
        fits.sort(key=lambda f: f.final_score)
        best = fits[0]
    # converged alternatives with the same time map: their spread is a profile-likelihood floor on the error
    best.alternatives = [(f.final_score - best.final_score, f) for f in fits[1:]
                         if abs(f.x[5] - best.x[5]) <= 0.05 and f.final_score - best.final_score <= 9.0]
    rival = min((f for f in fits[1:] if abs(f.x[5] - best.x[5]) > 0.05), key=lambda f: f.final_score, default=None)
    return best, rival


def feet_failure(feet_chi, matched_chi, n_obs, n_matched, people_matched, people_total, span_m):
    """Why a joint fit was rejected on its feet residuals. feet_chi charges every replay foot without a live
    partner the full CAP ("3 sigma"), so when most feet have none the number says nothing about the camera:
    the replay then shows people the live shot does not track, and there is nothing to check a camera against."""
    head = f"no consistent camera: the best fit leaves the replay feet {math.sqrt(feet_chi):.1f} sigma from the live players on average"
    detail = f"{n_matched} of {n_obs} replay foot observations ({people_matched} of {people_total} replay people) match a live player"
    if n_matched < 0.5 * n_obs:
        sig = "" if matched_chi is None else f", and those are {math.sqrt(matched_chi):.1f} sigma off"
        return (f"{head}; {detail}, spanning {span_m:.1f} m{sig}. Most replay people are not tracked in the live shot "
                "(or could not be identified), so a camera cannot be checked against them")
    return f"{head} ({detail}; wrong identities, or live tracks that swap people)"


def solve(frames, size, live, anchors, use_lines=True, loo=True):
    """Pure core (no I/O). frames: replay shot samples [{t, people: [{track, team, foot, h}], masks, motion}].
    Returns a report dict with per-frame "frame_results" [{ok, failure, G (pitch->image), sigma, p90_m, ...}]."""
    n = len(frames)
    report = {"status": "failed", "failure": None, "notes": [], "speed": None, "offset_s": None, "sync_sigma_s": None,
              "speed_sigma": None, "camera_centre": None, "matched": [], "fixed_centre_residual_px": None,
              "frames": n, "calibrated_frames": 0}
    if not anchors:
        return _fail_all(n, "no sync anchor: no paired foul incidents (pass --anchor LIVE_T:REPLAY_T)", report)
    if not live:
        return _fail_all(n, "live shot has no calibrated player positions", report)
    shot = Shot(frames, size, live, use_lines)

    # 1. fixed-centre check
    fits = [conjugate_fit(M, size) for M in shot.motions[1:] if M is not None]
    rms = [r[0] for r in fits]
    fc = float(np.median(rms)) if rms else None
    report["fixed_centre_residual_px"] = None if fc is None else round(fc, 2)
    if fc is not None and fc > MOVING_PX:
        return _fail_all(n, f"replay camera moves (fixed-centre residual {fc:.1f} px > {MOVING_PX:g} px; a per-frame "
                            "fallback would need >= 4 identified players in every frame)", report)
    sigma_m = max(1.0, fc or 1.0)

    # 2. sync + identities
    hyps, ctxs, notes = search(shot, anchors)
    report["notes"] += notes
    if not hyps:
        return _fail_all(n, "underdetermined: no identified opponent pair moves or spreads enough (>= 4 feet, >= 1 m) "
                            "to fix a camera", report)
    jf, jr = fit_shot(shot, hyps, ctxs, sigma_m, report["notes"])
    if jf is None:
        return _fail_all(n, "underdetermined", report)
    # goodness of fit before anything else: replay feet that no camera puts on the live players mean wrong
    # identities or a live track that swaps people, not an ambiguous sync
    r = jf.residuals(jf.x)[:jf.n_feet].reshape(-1, 3)
    n_obs = sum(1 for ob in shot.obs if ob[0] in jf.pos)
    feet_chi = (float(np.minimum(np.sum(r ** 2, axis=1), CAP).sum()) + CAP * (n_obs - len(r))) / max(n_obs, 1)
    report["feet_chi2_per_observation"] = round(feet_chi, 2)
    if feet_chi > MAX_FEET_CHI2:
        anchor_xy = [live_at(shot.live[g], jf.anchor["live_t"])[0][0] for g in set(jf.matched.values())]
        anchor_xy = [p for p in anchor_xy if np.isfinite(p).all()]
        span = max((float(np.linalg.norm(a - b)) for a in anchor_xy for b in anchor_xy), default=0.0)
        why = feet_failure(feet_chi, float(np.mean(np.minimum(np.sum(r ** 2, axis=1), CAP))) if len(r) else None, n_obs, len(r),
                           len(set(jf.matched)), len({ob[1] for ob in shot.obs if ob[0] in jf.pos}), span)
        _fail_all(n, why, report)
        Gs = jf.cams(jf.x)[3]
        for i in jf.idx:  # rejected camera, kept for --debug-dir overlays only (never written as a homography)
            report["frame_results"][i].update(G=Gs[jf.pos[i]] / Gs[jf.pos[i]][2, 2], live_t=float(jf.tau(jf.x, shot.t[i])))
        return report
    if jr is not None and jr.final_score - jf.final_score < 4.0:  # a materially different time map fits as well
        report.update(speed=round(float(jf.x[5]), 3))
        return _fail_all(n, f"sync ambiguous (speed {jf.x[5]:.2f} vs {jr.x[5]:.2f}, chi^2 within 4)", report)
    # the speed is only observable through the players' motion: live positions are smoothed noise, and a
    # wiggle of a few decimetres must not pass for a time map
    moved = 0.0
    for g in set(jf.matched.values()):
        xy = live_at(shot.live[g], jf.tau(jf.x, shot.t[jf.idx]))[0]
        xy = xy[np.isfinite(xy).all(1)]
        if len(xy) >= 2:
            moved = max(moved, float(np.linalg.norm(np.ptp(xy, axis=0))))
    if moved < MIN_MOTION_M:
        report.update(speed=round(float(jf.x[5]), 3))
        return _fail_all(n, f"sync ambiguous (matched players move at most {moved:.1f} m during the replay: "
                            "its speed is not observable)", report)
    if 3 * jf.s_sigma() > 0.1:  # speeds (v_live = v_replay / s) would be unknown
        report.update(speed=round(float(jf.x[5]), 3))
        return _fail_all(n, f"sync ambiguous (speed {jf.x[5]:.2f} +- {jf.s_sigma():.2f})", report)
    anchor, matched, seeds = jf.anchor, jf.matched, jf.seeds
    idx = jf.idx
    results = [{"ok": False, "failure": "no camera-motion link to the calibrated frames and fewer than 2 matched players"}
               for _ in range(n)]

    # 4. uncertainty + acceptance
    cov, ok_frames, bad = jf.covariance()
    x = jf.x
    if cov is None:
        return _fail_all(n, "underdetermined (camera centre or time map not observable)", report)
    s_sig = math.sqrt(max(cov[5, 5], 0))
    d_sig = math.sqrt(max(cov[6, 6], 0))
    Cc = x[:3]
    report.update(speed=round(float(x[5]), 4), speed_sigma=round(s_sig, 4), offset_s=round(float(x[6]), 4),
                  sync_sigma_s=round(d_sig, 4), camera_centre=[round(float(Cc[0]), 2), round(float(Cc[1]), 2),
                                                               round(float(-Cc[2]), 2)],
                  camera_centre_sigma_m=round(math.sqrt(max(float(np.linalg.eigvalsh(cov[:3, :3])[-1]), 0.0) + max(
                      [float(np.sum((f.x[:3] - x[:3]) ** 2)) / max(dc, 1.0) for dc, f in getattr(jf, "alternatives", [])],
                      default=0.0)), 2),
                  principal_point_offset_px=[round(float(v), 1) for v in x[3:5]], var_factor=round(jf.var_factor, 2),
                  anchor={"live_t": anchor["live_t"], "replay_t": anchor["replay_t"], "source": anchor.get("source")})
    Rs, fs, Ks, Gs = jf.cams(x)
    used = {}  # gid -> list of (o, frame)
    for o, i, g, u, *_ in jf.feet:
        used.setdefault(g, []).append((o, i))
    sig_live = [live_at(shot.live[g], jf.tau(x, shot.t[i]))[1][0] for g, lst in used.items() for o, i in lst]
    floor = float(np.nanmedian(sig_live)) if sig_live else 0.5
    report["live_position_floor_m"] = round(floor, 3)
    pair_frames = {}  # (replay track, live gid) -> frames actually used in the fit
    for o, i, g, u, *_ in jf.feet:
        pair_frames.setdefault((shot.obs[o][1], g), set()).add(i)
    report["matched"] = [{"replay_track": int(k), "live_gid": int(g), "team": shot.live[g]["team"],
                          "frames": len(fr), "seed": seeds.get(k) == g} for (k, g), fr in sorted(pair_frames.items())]
    # shot-level evidence
    pts = np.array([live_at(shot.live[g], jf.tau(x, shot.t[i]))[0][0] for g, lst in used.items() for o, i in lst])
    span = float(np.ptp(pts, axis=0).max()) if len(pts) else 0.0
    families = _line_families(jf, Gs)
    enough = (len(used) >= 2 and span >= 3.0) or (len(used) >= 1 and (len(families) >= 2 or "arc" in families))
    report["line_families"] = sorted(families)
    report["matched_span_m"] = round(span, 2)
    shot_fail = None
    if not enough:
        shot_fail = (f"too few matched players ({len(used)} matched, spanning {span:.1f} m; need 2 spanning >= 3 m, "
                     "or 1 plus a non-parallel line family)")
    # leave-one-player-out
    loo_res = []
    if loo and shot_fail is None:
        loo_res = _leave_one_out(jf, used, floor)
        report["leave_one_out"] = loo_res
        checked = [r for r in loo_res if r["z_median"] is not None]
        failing = [r for r in checked if r["z_median"] > LOO_SIGMAS]
        if not checked:
            shot_fail = "leave-one-player-out check impossible (removing any player leaves the camera underdetermined)"
        elif failing:
            w = max(failing, key=lambda r: r["z_median"])
            shot_fail = (f"leave-one-player-out check failed: live player {w['live_gid']} predicted "
                         f"{w['error_m_median']:.2f} m off ({w['z_median']:.1f} sigma > {LOO_SIGMAS:g})")
    per_frame_res = {}
    for o, i, g, u, *_ in jf.feet:
        xy, _ = live_at(shot.live[g], jf.tau(x, shot.t[i]))
        q = pitch.project(Gs[jf.pos[i]], xy)[0]
        per_frame_res.setdefault(i, []).append(float(np.linalg.norm(q - u)))
    for i in idx:
        k = jf.pos[i]
        res = {"ok": False, "G": Gs[k] / Gs[k][2, 2], "live_t": float(jf.tau(x, shot.t[i])),
               "point_residual_px": round(float(np.sqrt(np.mean(np.square(per_frame_res[i])))), 2)
               if i in per_frame_res else None, "players": len(per_frame_res.get(i, []))}
        res.update(_line_stats(shot, i, Gs[k]))
        if i in bad:
            res["failure"] = "underdetermined (no players, paint or camera-motion link fix this frame)"
        elif shot_fail:
            res["failure"] = shot_fail
        elif not pitch.orientation_ok(np.linalg.inv(Gs[k]), (size[1], size[0])):
            res["failure"] = "camera solution mirrored"
        else:
            sig = jf.sigma_fn(cov, i, floor)
            region = frames[i]["masks"][1] if frames[i].get("masks") is not None else np.full((size[1], size[0]), 255, np.uint8)
            p90 = pitch.region_error(sig, region)
            res["sigma"], res["p90_m"] = sig, p90
            if p90 is None:
                res["failure"] = "no visible grass"
            elif p90 > MAX_POSITION_ERROR_M:
                res["failure"] = f"position uncertainty {p90:.2f} m > {MAX_POSITION_ERROR_M:g} m (p90 over the visible grass)"
            else:
                res["ok"], res["failure"] = True, None
        results[i] = res
    report["frame_results"] = results
    report["calibrated_frames"] = sum(r["ok"] for r in results)
    report["status"] = "done" if report["calibrated_frames"] else "failed"
    if not report["calibrated_frames"]:
        report["failure"] = Counter(r["failure"] for r in results).most_common(1)[0][0]
    report["joint"] = jf
    report["cov"] = cov
    return report


def _line_families(jf, Gs):
    """Directions of painted lines the fit actually matched (>= 20 samples within 3 px in some frame)."""
    fam = set()
    for i, pts, wts, dm, ids in jf.lines:
        d = pitch._sample(dm, pitch.project(Gs[jf.pos[i]], pts))
        for lid in np.unique(ids):
            if (d[ids == lid] < 3.0).sum() < 20:
                continue
            if lid >= len(pitch.EDGES):
                fam.add("arc")
            else:
                a, b = pitch.EDGES[lid]
                dv = pitch.VERTICES[b - 1] - pitch.VERTICES[a - 1]
                fam.add("along" if abs(dv[0]) > abs(dv[1]) else "across")
    return fam


def _line_stats(shot, i, G):
    """Line support (fraction of in-view model samples within 3 px of paint) and RMS matched residual (m)."""
    m = shot.frames[i].get("masks")
    if m is None:
        return {"line_support": 0.0, "line_fit_residual_m": None}
    lines, region = m
    img, ok = pitch._in_view(G, lines.shape)
    if ok.sum() < 20:
        return {"line_support": 0.0, "line_fit_residual_m": None}
    band = np.minimum(cv2.distanceTransform(255 - lines, cv2.DIST_L2, 5), 20.0)
    band[region == 0] = 20.0
    db = pitch._sample(band, img[ok])
    near = db < 3.0
    err = None
    if near.sum() >= 10:
        err = float(np.sqrt(np.mean((db[near] * pitch.m_per_px(np.linalg.inv(G), img[ok][near])) ** 2)))
    return {"line_support": round(float(near.mean()), 3), "line_fit_residual_m": None if err is None else round(err, 3)}


def _leave_one_out(jf, used, floor):
    """Refit without each matched live player; predict its replay feet. z = error / sigma (median over frames)."""
    out = []
    shot = jf.shot
    for g, lst in used.items():
        if len(lst) < 3:
            continue
        sub = Joint(shot, jf.idx, jf.R0, jf.f0, jf.x[:3], jf.x[3:5], jf.x[5], jf.x[6], jf.anchor,
                    {k: v for k, v in jf.matched.items() if v != g}, jf.s_fixed, jf.sigma_m)
        sub.x = jf.x.copy()
        sub.dropped = set(jf.dropped)
        if jf.obs_gid is not None:
            sub.obs_gid = {o: v for o, v in jf.obs_gid.items() if v != g}
        sub.solve(20.0, max_nfev=40)
        sub.setup(20.0)
        cov, ok_frames, _ = sub.covariance()
        rec = {"live_gid": int(g), "frames": len(lst), "z_median": None, "error_m_median": None}
        if cov is not None:
            Gs = sub.cams(sub.x)[3]
            zs, es = [], []
            for o, i in lst:
                if i not in ok_frames:
                    continue
                u = shot.obs[o][2]
                gp = pitch.project(np.linalg.inv(Gs[sub.pos[i]]), u)[0]
                xy, sl = live_at(shot.live[g], sub.tau(sub.x, shot.t[i]))
                if np.isnan(gp).any() or np.isnan(xy).any():
                    continue
                e = float(np.linalg.norm(gp - xy[0]))
                s = float(np.sqrt(sub.sigma_fn(cov, i, floor)(u)[0] ** 2 + sl[0] ** 2 + SIGMA_BODY_M ** 2))
                zs.append(e / s), es.append(e)
            if zs:
                rec.update(z_median=round(float(np.median(zs)), 2), error_m_median=round(float(np.median(es)), 2))
        out.append(rec)
    return out


# ------------------------------------------------------------------ I/O

def write_json(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _incidents(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for inc in data.get("incidents") or []:
        c = (inc.get("indicators") or {}).get("contact") or {}
        pl = inc.get("players") or {}
        ch, vi = pl.get("challenger") or {}, pl.get("victim") or {}
        if not c.get("value") or ch.get("team") not in ("A", "B") or vi.get("team") not in ("A", "B") \
                or ch.get("team") == vi.get("team"):
            continue
        out.append({"t": inc["t"], "conf": float(c.get("confidence") or 0), "shot": inc.get("shot"),
                    "ids": {ch["team"]: ch.get("global_id") or ch.get("track_id"),
                            vi["team"]: vi.get("global_id") or vi.get("track_id")},
                    "tracks": {ch["team"]: ch.get("track_id"), vi["team"]: vi.get("track_id")}})
    return sorted(out, key=lambda i: -i["conf"])


def anchors_from(live_dir, replay_dir, given=None):
    """--anchor (live_t, replay_t) with identity hints from incidents at those times, else paired incidents:
    the 3 most confident live contacts x the 4 most confident replay contacts (opponents on both sides)."""
    li, ri = _incidents(Path(live_dir) / "fouls.json"), _incidents(Path(replay_dir) / "fouls.json")
    if given is not None:
        lt, rt = given
        lh = next((i for i in li if abs(i["t"] - lt) <= 0.3), None)
        rh = next((i for i in ri if abs(i["t"] - rt) <= 0.3), None)
        return [{"live_t": lt, "replay_t": rt, "source": "--anchor",
                 "live_pair": list(lh["ids"].values()) if lh else None,
                 "replay_pair": list(rh["tracks"].values()) if rh else None}]
    return [{"live_t": a["t"], "replay_t": b["t"], "source": f"paired incidents {a['t']:.3f}/{b['t']:.3f}",
             "live_pair": list(a["ids"].values()), "replay_pair": list(b["tracks"].values())}
            for a in li[:3] for b in ri[:4]]


def _foot(p, size):
    """Ground-contact pixel of a person: pose ankle midpoint when both ankles are confident, else the box
    bottom-centre; None when the feet are cut off or the person lies on the ground (box wider than tall)."""
    x1, y1, x2, y2 = p["bbox"]
    w, h = size
    if x2 - x1 > y2 - y1:
        return None
    ank = p.get("ankles")
    if ank and min(a[2] for a in ank) >= 0.5:
        u = np.mean([a[:2] for a in ank], axis=0)
    elif not ank and y2 < h - 3:
        u = np.array([(x1 + x2) / 2, y2])
    else:
        return None
    if not (3 <= u[0] <= w - 3 and 3 <= u[1] <= h - 3):
        return None
    return u


def load_shot(replay, closeup, video, shot_id, size, use_lines=True):
    """Decode the replay shot's sampled frames: people (close-up pose people when available), line masks and
    camera motion between consecutive samples."""
    fr = [f for f in replay["frames"] if f["shot"] == shot_id]
    cl = {}
    if closeup:
        for f in closeup.get("frames") or []:
            if f["shot"] == shot_id:
                cl[round(f["t"], 2)] = f["players"]
    use_cl = bool(cl)
    fps = replay["video"]["fps"]
    cap = cv2.VideoCapture(str(video))
    out, prev = [], None
    for f in fr:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(f["t"] * fps))
        ok, img = cap.read()
        if not ok:
            break
        people_src = cl.get(round(f["t"], 2), []) if use_cl else f.get("players") or []
        people = []
        for p in people_src:
            u = _foot(p, size)
            if u is not None and p.get("role", "player") != "referee":
                x1, y1, x2, y2 = p["bbox"]
                # apparent size only from an upright body whose box the frame does not cut
                h_ok = (y2 - y1 >= 1.8 * (x2 - x1)) and y1 > 3 and x1 > 3 and x2 < size[0] - 3 and y2 < size[1] - 3
                people.append({"track": p["track_id"], "team": p.get("team"), "foot": u, "h": float(y2 - y1), "h_ok": h_ok})
        gray = track.motion_gray(img)
        boxes = [p["bbox"] for p in people_src]
        motion = track.camera_motion(prev[0], gray, prev[1]) if prev is not None else None
        prev = (gray, boxes)
        out.append({"t": f["t"], "people": people, "masks": pitch.line_mask(img) if use_lines else None,
                    "motion": motion, "frame": f, "closeup_people": people_src if use_cl else None})
    cap.release()
    return out, use_cl


def pick_shots(replay, live, anchors, shot_id=None):
    if shot_id is None:
        votes = Counter()
        for a in anchors:
            for s in replay["shots"]:
                if s["start"] - 0.05 <= a["replay_t"] <= s["end"] + 0.05:
                    votes[s["id"]] += 1
        cands = [s for s in replay["shots"] if s.get("calibrated_ratio", 0) < 0.5]
        shot_id = votes.most_common(1)[0][0] if votes else (max(cands, key=lambda s: s["end"] - s["start"])["id"]
                                                             if cands else None)
    lv = Counter()
    for a in anchors:
        for s in live["shots"]:
            if s["start"] - 0.05 <= a["live_t"] <= s["end"] + 0.05:
                lv[s["id"]] += 1
    live_shot = lv.most_common(1)[0][0] if lv else max(live["shots"], key=lambda s: s.get("calibrated_ratio", 0))["id"]
    return shot_id, live_shot


def write_back(replay, shot_id, recs, report, speed_meta, live_ref, video):
    """Calibration, live_t, players (close-up people replace partial wide-detector boxes), smoothing, ball, ids."""
    res = report["frame_results"]
    for f in replay["frames"]:
        f.setdefault("live_t", None)
    cv_meta = {"live": live_ref, "speed": report["speed"], "offset_s": report["offset_s"],
               "sync_sigma_s": report["sync_sigma_s"], "camera_centre": report["camera_centre"],
               "matched": [{k: m[k] for k in ("replay_track", "live_gid", "team", "frames")} for m in report["matched"]],
               "fixed_centre_residual_px": report["fixed_centre_residual_px"]}
    for rec, r in zip(recs, res):
        f = rec["frame"]
        ok = bool(r.get("ok"))
        G = r.get("G")
        f["calibration"] = {
            "ok": ok, "source": "cross_view" if ok else None,
            "homography": [[float(v) for v in row] for row in G] if ok else None,
            "reprojection_error_m": round(r["p90_m"], 3) if ok else None,
            "line_fit_residual_m": r.get("line_fit_residual_m") if ok else None,
            "keypoints": 0, "line_support": r.get("line_support", 0.0), "keypoint_loo_m": None,
            "failure": None if ok else r.get("failure"),
            "cross_view": dict(cv_meta, point_residual_px=r.get("point_residual_px"))}
        f["live_t"] = round(r["live_t"], 3) if r.get("live_t") is not None and report["speed"] is not None else None
        H = np.linalg.inv(G) if ok else None
        sig = r.get("sigma") if ok else None
        if rec["closeup_people"] is not None:  # whole bodies from the pose model replace partial boxes
            size = (replay["video"]["width"], replay["video"]["height"])
            f["players"] = []
            for q in rec["closeup_people"]:
                u = _foot(q, size)
                f["players"].append({
                    "track_id": q["track_id"], "role": "player", "team": q.get("team"), "bbox": q["bbox"],
                    "confidence": round(float(np.mean([a[2] for a in q["ankles"]])), 3) if q.get("ankles") else None,
                    "foot": None if u is None else [round(float(u[0]), 1), round(float(u[1]), 1)],
                    "source": "closeup_pose"})
        for p in f["players"]:
            u = p.get("foot")
            x = y = unc = None
            if H is not None and u is not None:
                g = pitch.project(H, [u])[0]
                if np.isfinite(g).all() and -5 <= g[0] <= pitch.LENGTH + 5 and -5 <= g[1] <= pitch.WIDTH + 5:
                    x, y = round(float(g[0]), 2), round(float(g[1]), 2)
                    unc = round(float(sig([u])[0]), 3)
            p.update(x=x, y=y, position_uncertainty_m=unc)
            p.pop("raw_x", None), p.pop("raw_y", None)
        b = f.get("ball")
        if b:
            u = b.get("image_bottom") or b.get("image")
            for k in ("z", "airborne", "height_uncertainty_m", "height_model", "ground_x", "ground_y"):
                b.pop(k, None)
            g = pitch.project(H, [u])[0] if H is not None and u else None
            ok_b = g is not None and np.isfinite(g).all()
            b.update(x=round(float(g[0]), 2) if ok_b else None, y=round(float(g[1]), 2) if ok_b else None,
                     position_uncertainty_m=round(float(sig([u])[0]), 3) if ok_b else None)
    shot = next(s for s in replay["shots"] if s["id"] == shot_id)
    n_ok = sum(bool(r.get("ok")) for r in res)
    shot.update(calibrated_ratio=round(n_ok / max(1, len(res)), 3), usable=bool(n_ok / max(1, len(res)) >= 0.5 and n_ok >= 2),
                playback_speed=report["speed"] or shot.get("playback_speed", 1.0), replay_of=speed_meta)
    for s in replay["shots"]:
        s.setdefault("playback_speed", 1.0)
        s.setdefault("replay_of", None)
    frames = [rec["frame"] for rec in recs]
    temporal.smooth_tracks(frames, playback_speed=shot["playback_speed"])
    hooks = {}
    for name, call in (("ball3d", lambda: ball3d.apply(replay)), ("reid", lambda: reid.apply(replay, str(video)))):
        try:
            call()
            hooks[name] = "applied"
        except Exception as e:  # report, keep the calibration
            hooks[name] = f"error: {type(e).__name__}: {e}"
    replay["events"] = temporal.detect_passes(replay["frames"], speeds={s["id"]: s.get("playback_speed") or 1.0
                                                                         for s in replay["shots"]})
    replay.setdefault("pipeline", {}).setdefault("hooks", {}).update(hooks)
    replay["pipeline"]["cross_view"] = {"shot": shot_id, "calibrated_frames": n_ok, "live": live_ref}


def report_json(report, shot_id, live_ref):
    keep = ("status", "failure", "speed", "speed_sigma", "offset_s", "sync_sigma_s", "calibrated_frames", "frames",
            "matched", "camera_centre", "camera_centre_sigma_m", "principal_point_offset_px", "fixed_centre_residual_px", "notes", "anchor",
            "leave_one_out", "line_families", "matched_span_m", "live_position_floor_m", "var_factor", "feet_chi2_per_observation")
    out = {k: report.get(k) for k in keep}
    out.update(replay_shot=shot_id, live=live_ref, frame_results=[
        {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ("G", "sigma")}
        for r in report["frame_results"]])
    return out


def run(args):
    replay_dir, live_dir = Path(args.replay), Path(args.live)
    replay = json.loads((replay_dir / "analysis.json").read_text())
    live = json.loads((live_dir / "analysis.json").read_text())
    pitch.set_dimensions(replay["pitch"]["length_m"], replay["pitch"]["width_m"])
    closeup_path = replay_dir / "closeup.json"
    closeup = json.loads(closeup_path.read_text()) if closeup_path.exists() else None
    anchors = anchors_from(live_dir, replay_dir, args.anchor)
    shot_id, live_shot = pick_shots(replay, live, anchors, args.shot)
    out_dir = Path(args.out) if args.out else replay_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    live_ref = {"clip": live.get("clip_id"), "window": f"{live['window']['start']:.1f}-{live['window']['end']:.1f}",
                "shot": live_shot}
    if shot_id is None:
        rep = {"status": "failed", "failure": "no uncalibrated replay shot found", "replay_shot": None, "live": live_ref}
        write_json(out_dir / "crossview.json", rep)
        return rep
    size = (replay["video"]["width"], replay["video"]["height"])
    recs, used_closeup = load_shot(replay, closeup, args.video, shot_id, size, use_lines=not args.no_lines)
    report = solve(recs, size, live_tracks(live, live_shot), anchors, use_lines=not args.no_lines)
    report["notes"].insert(0, "replay people: " + ("close-up pose people (closeup.json)" if used_closeup
                                                    else "the analysis' own detections"))
    if args.no_lines:
        report["notes"].append("painted lines ignored (--no-lines)")
    a = report.get("anchor") or {}
    speed_meta = None if report["speed"] is None or report["status"] != "done" else {
        "clip": live.get("clip_id"), "window": live_ref["window"], "t_live_anchor": round(a["live_t"] + report["offset_s"], 3),
        "t_replay_anchor": a["replay_t"], "speed": report["speed"]}
    write_back(replay, shot_id, recs, report, speed_meta, live_ref, args.video)
    if report["status"] != "done":
        next(s for s in replay["shots"] if s["id"] == shot_id).update(playback_speed=1.0, replay_of=None)
    rep = report_json(report, shot_id, live_ref)
    write_json(out_dir / "analysis.json", replay)
    write_json(out_dir / "crossview.json", rep)
    if args.debug_dir:
        overlays(args.debug_dir, args.video, replay, shot_id, report, recs, live_tracks(live, live_shot))
    return rep


def overlays(debug_dir, video, replay, shot_id, report, recs, live):
    """Projected pitch lines (magenta) and the live players' synced positions (cyan, gid) on each replay frame."""
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = replay["video"]["fps"]
    for rec, r in zip(recs, report["frame_results"]):
        if r.get("G") is None:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(rec["t"] * fps))
        ok, img = cap.read()
        if not ok:
            continue
        pitch.draw_pitch(img, np.linalg.inv(r["G"]))
        for g, tr in live.items():
            xy, _ = live_at(tr, r["live_t"])
            if np.isnan(xy).any():
                continue
            q = pitch.project(r["G"], xy)[0]
            if np.isfinite(q).all() and -50 < q[0] < img.shape[1] + 50 and -50 < q[1] < img.shape[0] + 50:
                cv2.circle(img, (int(q[0]), int(q[1])), 7, (255, 255, 0), 2)
                cv2.putText(img, str(g), (int(q[0]) + 8, int(q[1]) - 8), 0, 0.6, (255, 255, 0), 2)
        for p in rec["people"]:
            cv2.drawMarker(img, (int(p["foot"][0]), int(p["foot"][1])), (0, 255, 255), cv2.MARKER_CROSS, 14, 2)
            cv2.putText(img, str(p["track"]), (int(p["foot"][0]) - 20, int(p["foot"][1]) + 20), 0, 0.5, (0, 255, 255), 1)
        txt = (f"t={rec['t']:.2f} live={r['live_t']:.2f} " + ("OK" if r.get("ok") else "FAIL: " + str(r.get("failure")))
               + (f" p90={r['p90_m']:.2f}m" if r.get("p90_m") is not None else ""))
        cv2.putText(img, txt[:110], (10, 30), 0, 0.6, (0, 0, 255) if not r.get("ok") else (0, 255, 0), 2)
        cv2.imwrite(str(Path(debug_dir) / f"cv_{rec['t']:.3f}.jpg"), cv2.resize(img, (960, 540)))
    cap.release()


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", required=True, help="replay window dir (analysis.json, optional closeup.json, fouls.json)")
    ap.add_argument("--live", required=True, help="live window dir (analysis.json, optional fouls.json)")
    ap.add_argument("--video", required=True, help="the replay clip's video.mp4")
    ap.add_argument("--anchor", help="LIVE_T:REPLAY_T, overrides paired incidents")
    ap.add_argument("--shot", type=int, help="replay shot id (default: the shot holding the anchor)")
    ap.add_argument("--out", help="write analysis.json + crossview.json here instead of the replay dir")
    ap.add_argument("--no-lines", action="store_true", help="ignore painted lines (evaluation)")
    ap.add_argument("--debug-dir", help="write overlay images here")
    args = ap.parse_args(argv)
    if args.anchor:
        lt, rt = args.anchor.split(":")
        args.anchor = (float(lt), float(rt))
    return args


def main(argv=None):
    args = parse(argv)
    out_dir = Path(args.out) if args.out else Path(args.replay)
    err = out_dir / "crossview.error.json"
    try:
        err.unlink(missing_ok=True)
        rep = run(args)
        print(json.dumps({k: rep.get(k) for k in ("status", "failure", "speed", "offset_s", "calibrated_frames", "frames",
                                                   "camera_centre", "fixed_centre_residual_px")}))
    except Exception as e:  # the backend reads this instead of a half-written result
        import traceback
        traceback.print_exc()
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(err, {"error": f"{type(e).__name__}: {e}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

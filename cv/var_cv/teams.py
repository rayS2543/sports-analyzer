"""Team assignment by jersey colour (2-means over upper-torso Lab colour) and per-frame sanity caps."""

import cv2
import numpy as np
from sklearn.cluster import KMeans

MIN_PIXELS = 12
MAX_PER_TEAM = 11
ODD_KIT = 3.0  # a kit this many "typical cluster radii" from both team colours is neither team's


def jersey_feature(frame, bbox):
    """Median Lab colour of the upper torso with grass pixels removed, or None."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    crop = frame[int(y1 + 0.15 * h):int(y1 + 0.5 * h), int(x1 + 0.25 * w):int(x2 - 0.25 * w)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    grass = (hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] > 50)
    keep = lab[~grass]
    return np.median(keep, axis=0) if len(keep) >= MIN_PIXELS else None


N_HUES = 12


def _torso(frame, bbox):
    """Upper-torso pixels (HSV and BGR) with grass removed, or None if too few."""
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    crop = frame[int(y1 + 0.15 * h):int(y1 + 0.5 * h), int(x1 + 0.25 * w):int(x2 - 0.25 * w)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.int32)
    bgr = crop.reshape(-1, 3)
    keep = ~((hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] > 50))  # grass
    if keep.sum() < MIN_PIXELS:
        return None
    return hsv[keep], bgr[keep]


def kit_feature(frame, bbox):
    """Colour signature of a kit: histogram over 12 saturated hues + light/dark neutrals, square-rooted
    (Hellinger), from the grass-free upper torso. Striped or two-tone shirts keep their mix instead of
    averaging to a muddy colour, and shading changes the value, not the bin. Returns (signature,
    display BGR: median of the saturated pixels when they cover >= 30% of the torso, else of all)
    or None."""
    t = _torso(frame, bbox)
    if t is None:
        return None
    hsv, bgr = t
    chroma = (hsv[:, 1] > 60) & (hsv[:, 2] > 50)
    hist = np.zeros(N_HUES + 2)
    np.add.at(hist, (hsv[chroma, 0] * N_HUES // 180), 1)
    v = hsv[~chroma, 2]
    hist[N_HUES] = (v >= 60).sum()  # white/grey: one bin, so a shadowed white shirt stays "white"
    hist[N_HUES + 1] = (v < 60).sum()  # black
    # display colour: the kit's main colour, not the average of its stripes
    main = bgr[chroma] if chroma.mean() >= 0.3 else bgr
    return np.sqrt(hist / hist.sum()), np.median(main, axis=0)


class TeamModel:
    """Two kits as colour signatures. Labels are deterministic: A is the lighter kit."""

    def __init__(self, centres, radius, colours):
        self.centres, self.radius, self.colours_bgr = np.asarray(centres, float), float(radius), np.asarray(colours, float)

    @classmethod
    def fit(cls, features, weights=None):
        """features: [(signature, median BGR)]; weights: detection quality per crop."""
        X = np.array([f[0] for f in features])
        C = np.array([f[1] for f in features], float)
        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(X, sample_weight=weights)
        cols = np.array([np.median(C[km.labels_ == k], axis=0) for k in range(2)])
        light = cv2.cvtColor(cols.reshape(1, 2, 3).astype(np.uint8), cv2.COLOR_BGR2LAB)[0, :, 0]
        order = np.argsort(-light.astype(int))
        d = np.linalg.norm(X[:, None] - km.cluster_centers_[None], axis=2).min(1)
        return cls(km.cluster_centers_[order], max(float(np.median(d)), 0.05), cols[order])

    def predict(self, feature):
        return "AB"[int(np.argmin(np.linalg.norm(self.centres - feature[0], axis=1)))]

    def margin(self, feature):
        """How clearly a crop belongs to one kit: 1 - nearest/second distance (0 = ambiguous)."""
        d = np.sort(np.linalg.norm(self.centres - feature[0], axis=1))
        return float(1 - d[0] / max(d[1], 1e-9))

    def odd(self, feature):
        """True when the kit is far from both teams (goalkeeper or referee kit)."""
        return float(np.linalg.norm(self.centres - feature[0], axis=1).min()) > ODD_KIT * self.radius

    def colours(self):
        return {name: "#{2:02x}{1:02x}{0:02x}".format(*(int(v) for v in bgr)) for name, bgr in zip("AB", self.colours_bgr)}

    def to_json(self):
        return {"centres": self.centres.tolist(), "radius": self.radius, "colours_bgr": self.colours_bgr.tolist()}

    @classmethod
    def from_json(cls, d):
        return cls(d["centres"], d["radius"], d["colours_bgr"])


def fit(features, weights=None):
    """TeamModel, or None when there are too few kit crops to cluster."""
    return TeamModel.fit(features, weights) if len(features) >= 6 else None


def cap_per_frame(players, min_sep_m=0.5):
    """Enforce football's head count on one frame's player dicts; returns the kept list.

    1. Duplicate boxes: two same-team people closer than min_sep_m on the pitch are one
       person; the less confident detection is removed.
    2. More than MAX_PER_TEAM on a team: the surplus with the weakest team evidence
       (`team_score`: the track's vote share x detection confidence) lose their team (null).
    Referees never have a team.
    """
    for p in players:
        if p["role"] == "referee":
            p["team"] = None
    out = []
    for p in sorted(players, key=lambda p: -p["confidence"]):
        dup = p["team"] and p["x"] is not None and any(
            q["team"] == p["team"] and q["x"] is not None and np.hypot(p["x"] - q["x"], p["y"] - q["y"]) < min_sep_m
            for q in out)
        if not dup:
            out.append(p)
    for team in "AB":
        members = sorted((p for p in out if p["team"] == team), key=lambda p: -p.get("team_score", p["confidence"]))
        for p in members[MAX_PER_TEAM:]:
            p["team"] = None
    kept = {id(p) for p in out}
    return [p for p in players if id(p) in kept]

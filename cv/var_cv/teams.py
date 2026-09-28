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


class TeamModel:
    """Two kit colours. Labels are arbitrary but deterministic: A is the lighter kit."""

    def __init__(self, features):
        X = np.asarray(features, np.float32)
        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(X)
        order = np.argsort(-km.cluster_centers_[:, 0])  # by lightness
        self.centres = km.cluster_centers_[order]
        d = np.linalg.norm(X[:, None] - self.centres[None], axis=2).min(1)
        self.radius = max(float(np.median(d)), 4.0)  # typical within-kit colour spread

    def predict(self, feature):
        return "AB"[int(np.argmin(np.linalg.norm(self.centres - feature, axis=1)))]

    def odd(self, feature):
        """True when the colour is far from both kits (goalkeeper or referee kit)."""
        return float(np.linalg.norm(self.centres - feature, axis=1).min()) > ODD_KIT * self.radius

    def colours(self):
        out = {}
        for name, lab in zip("AB", self.centres):
            b, g, r = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_LAB2BGR)[0, 0]
            out[name] = f"#{r:02x}{g:02x}{b:02x}"
        return out


def fit(features):
    """TeamModel, or None when there are too few jersey crops to cluster."""
    return TeamModel(features) if len(features) >= 6 else None


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

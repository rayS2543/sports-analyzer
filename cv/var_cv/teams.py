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


CROWD_OVERLAP = 0.3  # a box overlapping another person's by this much (of the smaller box) holds two shirts
CROWD_WEIGHT = 0.25  # ... so its kit reading counts this much in a track's team vote
KIT_SHARE = 0.7      # a team needs this share of the weighted votes, else the kit is ambiguous (null)


def crowded(boxes):
    """Per box (xyxy): does it overlap another by CROWD_OVERLAP of the smaller one? Its shirt crop then shows two people."""
    boxes = np.asarray(boxes, float).reshape(-1, 4)
    out = []
    for i, a in enumerate(boxes):
        hit = False
        for j, b in enumerate(boxes):
            w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
            hit = hit or (j != i and w > 0 and h > 0 and w * h > CROWD_OVERLAP * max(small, 1e-6))
        out.append(hit)
    return out


def decisive(votes):
    """(team or None, vote share) from weighted votes {"A": w, "B": w}: a team only when it holds KIT_SHARE of them,
    so a track whose kit reads both ways (hidden behind another player, motion blur) gets no team, not a coin flip."""
    total = sum(votes.values())
    if not total:
        return None, 0.0
    team, w = max(votes.items(), key=lambda kv: kv[1])
    return (team if w >= KIT_SHARE * total else None), w / total


OUTLIER_MIN_TRACKS = 4  # tracks a team needs before one can be called unlike the rest
OUTLIER_MIN_CROPS = 12  # a keeper stays in view; a short fragment of a blurred or half-hidden outfielder does not
OUTLIER_FLOOR = 0.4     # a track's mean kit signature must be at least this far (Hellinger) from its team's median ...
OUTLIER_SPREAD = 3.0    # ... this many times the usual distance of the team's tracks ...
OUTLIER_LONE = 1.5      # ... and this many times the next-furthest track's: one clear exception, not several odd ones


def kit_outliers(track_features, team_of):
    """Tracks whose kit is unlike the rest of their team's, at most one per team: {track id}. A goalkeeper in a black or
    neon shirt is nearer one team's colours than the other's, so no single crop looks 'odd', yet his shirt is far from
    every outfield player's on that team. track_features: {track id: [signature, ...]}; team_of: {track id: 'A'/'B'/None}."""
    mean = {t: np.mean(fs, axis=0) for t, fs in track_features.items() if len(fs) >= OUTLIER_MIN_CROPS and team_of.get(t)}
    out = set()
    for team in "AB":
        ids = [t for t in mean if team_of[t] == team]
        if len(ids) < OUTLIER_MIN_TRACKS:
            continue
        centre = np.median([mean[t] for t in ids], axis=0)
        gap = sorted(((float(np.linalg.norm(mean[t] - centre)), t) for t in ids), reverse=True)
        usual = float(np.median([g for g, _ in gap]))
        top, runner_up = gap[0][0], gap[1][0]
        if top >= OUTLIER_FLOOR and top >= OUTLIER_SPREAD * max(usual, 1e-6) and top >= OUTLIER_LONE * max(runner_up, 1e-6):
            out.add(gap[0][1])
    return out


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

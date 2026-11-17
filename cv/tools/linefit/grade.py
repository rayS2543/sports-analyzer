"""GRADER-SIDE ONLY, run after seeds are saved. Compares seeded H with the relaunch's hand-seeded, gate-verified propagation, up to the line-symmetry group."""
import json, glob, os, numpy as np, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder; pitch = seeder.pitch
HD = os.environ.get("HDIR", "H")
L = os.path.dirname(os.path.abspath(__file__)); R = seeder.B + "/footage-test/relaunch"
ref, okfr = {}, set()
def load(pat, lo, hi):
    for f in sorted(glob.glob(pat)):
        for row in np.load(f):
            n = int(row[0])
            if lo <= n <= hi: ref[n] = row[1:].reshape(3, 3)
load(R + "/h1/H_*.npy", 0, 183000); load(R + "/h2f/H_*.npy", 183000, 10**9); load(R + "/h2b/H_*.npy", 183000, 10**9)
for p in glob.glob(R + "/h*/checkpoints.jsonl"):
    for l in open(p):
        c = json.loads(l)
        if c.get("verification", {}).get("verified"): okfr.add(c["frame"])
okl = np.array(sorted(okfr))
grid = np.array([[u, v] for u in np.linspace(0.1, 0.9, 5) * 1920 for v in np.linspace(0.4, 0.9, 3) * 1080])
SYM = {"id": lambda p: p, "rot180": lambda p: np.c_[105 - p[:, 0], 68 - p[:, 1]], "y-flip": lambda p: np.c_[p[:, 0], 68 - p[:, 1]], "x-flip": lambda p: np.c_[105 - p[:, 0], p[:, 1]]}
def grade(n, H):
    if n not in ref or not len(okl) or np.abs(okl - n).min() > 75: return None
    a = pitch.project(ref[n], grid); b = pitch.project(H, grid)
    d = {k: float(np.nanmean(np.linalg.norm(a - f(b), axis=1))) for k, f in SYM.items()}
    k = min(d, key=d.get); return dict(best_sym=k, dist_m=d[k], dist_id_m=d["id"])
out = {}
for name in ("samples", "molina"):
    res = json.load(open(f"{L}/results_{name}.json")); res = dict(res, **(json.load(open(L + "/results_extra.json")) if name == "samples" and os.path.exists(L + "/results_extra.json") else {})); g = {}
    for k, v in res.items():
        if v["found"]:
            r = grade(int(k), np.load(f"{L}/{HD}/{k}.npy"))
            if r: g[k] = r
    out[name] = g
    ds = np.array([x["dist_m"] for x in g.values()])
    print(name, "graded", len(g), "median %.2f p90 %.2f max %.2f m" % (np.median(ds), np.percentile(ds, 90), ds.max()), "bad(>1m)", int((ds > 1).sum()),
          "syms", {s: sum(x["best_sym"] == s for x in g.values()) for s in SYM})
json.dump(out, open(L + ("/grade.json" if HD == "H" else "/grade_resolved.json"), "w"), indent=1)

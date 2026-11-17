"""End-identity resolution. Lines are 180-deg symmetric, so each seed is labelled arbitrarily. Fix: chain-consistency. The relaunch-style propagated H
from seed A, evaluated at seed B's frame, disagrees with B by either ~0 (same labelling) or by a 180 rotation; flip B accordingly, cumulatively along the half.
Result is self-consistent for the whole half. ONE bit remains that no line can give: which end is x=105. usage: orient.py [anchor_flip 0|1] -> H_resolved/, orient.json"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder; pitch = seeder.pitch
L = os.path.dirname(os.path.abspath(__file__))
anchor = int(sys.argv[1]) if len(sys.argv) > 1 else 0
# 180 rotation of pitch coords as a homography: p -> (105-x, 68-y)
Rm = np.array([[-1, 0, 105.0], [0, -1, 68.0], [0, 0, 1]])
iv = json.load(open(L + "/coverage_intervals.json"))
allres = json.load(open(L + "/results_samples.json"))
if os.path.exists(L + "/results_extra.json"): allres.update(json.load(open(L + "/results_extra.json")))
seeds = sorted(int(k) for k, v in allres.items() if v["found"])
flip = {seeds[0]: anchor}; links = []
for a, b in zip(seeds[:-1], seeds[1:]):
    d = iv.get(f"{a}-{b}", {}).get("orient_dist_m")  # coverage_intervals keys are a-b of consecutive seeds (first/last use half edges)
    if d is None:  # chain did not reach the next seed: cannot resolve, stop and start a new unresolved segment
        flip[b] = None; links.append(dict(a=a, b=b, status="unresolved")); continue
    c = d["rot180"] < d["same"]
    flip[b] = None if flip[a] is None else flip[a] ^ int(c)
    links.append(dict(a=a, b=b, conflict=bool(c), same=d["same"], rot180=d["rot180"], margin=abs(d["same"] - d["rot180"]) / max(min(d["same"], d["rot180"]), 1e-6)))
os.makedirs(L + "/H_resolved", exist_ok=True)
for n, f in flip.items():
    if f is None: continue
    H = np.load(f"{L}/H/{n}.npy"); np.save(f"{L}/H_resolved/{n}.npy", Rm @ H if f else H)
json.dump(dict(anchor=anchor, flips={str(k): v for k, v in flip.items()}, links=links), open(L + "/orient.json", "w"), indent=1)
m = [l["margin"] for l in links if "margin" in l]
print("resolved", sum(v is not None for v in flip.values()), "of", len(flip), "unresolved links", sum(l.get("status") == "unresolved" for l in links),
      "min margin ratio %.1f (same-vs-rot180 distance, larger = clearer)" % min(m), "median %.1f" % np.median(m))

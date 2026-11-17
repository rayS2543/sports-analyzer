"""For weak orientation links (neither labelling agrees within 2 m, or margin ratio < 5), seed every 10 s inside the span (machine seeder) -> results_extra.json.
Then rerun coverage.py and orient.py. usage: densify.py"""
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder
L = os.path.dirname(os.path.abspath(__file__)); V = seeder.B + "/footage-test/argentina_netherlands_tactical.mp4"
o = json.load(open(L + "/orient.json")); ex_p = L + "/results_extra.json"
ex = json.load(open(ex_p)) if os.path.exists(ex_p) else {}
cap = cv2.VideoCapture(V); todo = 0
for l in o["links"]:
    weak = l.get("status") == "unresolved" or min(l["same"], l["rot180"]) > 2.0 or l["margin"] < 5
    if not weak: continue
    a, b = l["a"], l["b"]; span = (b - a) / 60
    for n in range(a + 600, b, 600) if span > 10 else [a + (b - a) // 2 // 2 * 2]:
        if str(n) in ex: continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, n); ok, f = cap.read(); r = seeder.seed(f); H = r.pop("H", None)
        if H is not None: np.save(f"{L}/H/{n}.npy", H)
        r["video_time_s"] = n / 60; ex[str(n)] = r; todo += 1
        json.dump(ex, open(ex_p, "w")); print(n / 60, r["found"], flush=True)
print("new extra seeds", todo, "found", sum(v["found"] for v in ex.values()), "of", len(ex))

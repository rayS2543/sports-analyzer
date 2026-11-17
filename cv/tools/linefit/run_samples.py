"""usage: run_samples.py  -> results_samples.json (every 60 s of H1, 612-3690 s) and results_molina.json (2640-2650 s, every frame). Resumable."""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder, cv2, numpy as np
L = os.path.dirname(os.path.abspath(__file__)); V = seeder.B + "/footage-test/argentina_netherlands_tactical.mp4"
FPS = 60
jobs = {"results_samples.json": [t * FPS for t in range(612, 3691, 60)],
        "results_molina.json": list(range(2640 * FPS, 2650 * FPS + 1))}
os.makedirs(L + "/H", exist_ok=True)
cap = cv2.VideoCapture(V)
for out, frames in jobs.items():
    p = f"{L}/{out}"; done = json.load(open(p)) if os.path.exists(p) else {}
    for i, n in enumerate(frames):
        if str(n) in done: continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, n); ok, f = cap.read()
        if not ok: done[str(n)] = {"found": False, "error": "read fail"}; continue
        r = seeder.seed(f); H = r.pop("H", None)
        if H is not None: np.save(f"{L}/H/{n}.npy", H)
        r["video_time_s"] = n / FPS; done[str(n)] = r
        if i % 10 == 0: json.dump(done, open(p, "w")); print(out, i, len(frames), flush=True)
    json.dump(done, open(p, "w"), indent=1)
    d = list(done.values()); print(out, "found", sum(x["found"] for x in d), "of", len(d), "total secs", round(sum(x.get("secs", 0) for x in d)))

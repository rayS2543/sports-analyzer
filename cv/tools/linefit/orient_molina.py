"""Resolve end identity of the Molina-window seeds: anchor the last window frame (2650 s) to the resolved 2652 s seed by a short LK chain (2 s),
then walk backwards frame to frame (adjacent seeds differ by ~cm, so same-vs-rot180 is unambiguous). Writes H_resolved/<frame>.npy."""
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seeder; pitch = seeder.pitch
L = os.path.dirname(os.path.abspath(__file__)); V = seeder.B + "/footage-test/argentina_netherlands_tactical.mp4"
cv2.setNumThreads(2)
Rm = np.array([[-1, 0, 105.0], [0, -1, 68.0], [0, 0, 1]])
grid = np.array([[u, v] for u in np.linspace(0.1, 0.9, 5) * 1920 for v in np.linspace(0.4, 0.9, 3) * 1080])
def dist(Ha, Hb): return float(np.nanmean(np.linalg.norm(pitch.project(Ha, grid) - pitch.project(Hb, grid), axis=1)))
gray = lambda f: cv2.cvtColor(cv2.resize(f, (960, 540)), cv2.COLOR_BGR2GRAY)
def step(a, b, H):
    p = cv2.goodFeaturesToTrack(a, 500, .01, 10, blockSize=7)
    q, s, _ = cv2.calcOpticalFlowPyrLK(a, b, p, None, winSize=(21, 21), maxLevel=3); z, t, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, winSize=(21, 21), maxLevel=3)
    g = (s[:, 0] > 0) & (t[:, 0] > 0) & (np.linalg.norm((p - z)[:, 0, :], axis=1) < 1)
    M, _ = cv2.findHomography(p[g] * 2, q[g] * 2, cv2.RANSAC, 2.5); return H @ np.linalg.inv(M)
res = json.load(open(L + "/results_molina.json")); fr = sorted(int(k) for k, v in res.items() if v["found"])
end, seed = fr[-1], 2652 * 60
Hs = np.load(f"{L}/H_resolved/{seed}.npy"); Hl = np.load(f"{L}/H/{end}.npy")
cap = cv2.VideoCapture(V); cap.set(cv2.CAP_PROP_POS_FRAMES, end); ok, f = cap.read(); prev = gray(f); H = Hl.copy(); n = end
while n < seed:
    for _ in range(1): cap.grab()
    n += 2; ok, f = cap.read(); cur = gray(f); H = step(prev, cur, H); prev = cur
d0, d1 = dist(H, Hs), dist(H, Rm @ Hs) if False else dist(Rm @ H, Hs)
flip = int(d1 < d0); print("anchor link: same %.2f rot180 %.2f m -> flip %d" % (d0, d1, flip))
cur_flip, prevH = flip, (Rm @ Hl if flip else Hl); np.save(f"{L}/H_resolved/{end}.npy", prevH)
for n in reversed(fr[:-1]):
    H = np.load(f"{L}/H/{n}.npy"); a, b = dist(H, prevH), dist(Rm @ H, prevH)
    H = Rm @ H if b < a else H; np.save(f"{L}/H_resolved/{n}.npy", H); prevH = H
print("resolved", len(fr))

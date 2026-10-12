// Display-only smoothing between sampled frames. Pure (no three.js) so it runs in jsdom.
// Judgments never use this: the assessment always reads a real sampled frame.

const EPS = 1e-6;

// Identity used to pair a person across two frames: re-identified global_id when present, else the per-shot track.
export const personKey = (p) => p.global_id ?? p.track_id;

/**
 * The two sampled frames either side of `time`, when smoothing between them is honest:
 * same shot, both calibrated, no more than 1.5 sample intervals apart, and `frame` (the frame the viewer chose)
 * is one of them. Returns { a, b, k } with k in (0, 1), or null to snap to `frame`.
 * The sample interval is the smallest gap between the shot's frames, so a dropped frame reads as a gap.
 */
export function bracket(frame, shotFrames, time) {
  if (!frame || !shotFrames || shotFrames.length < 2 || !Number.isFinite(time)) return null;
  if (Math.abs(time - frame.t) < EPS) return null; // exactly on a sampled frame
  let interval = Infinity;
  let i = -1;
  for (let j = 1; j < shotFrames.length; j++) {
    const gap = shotFrames[j].t - shotFrames[j - 1].t;
    if (gap > EPS) interval = Math.min(interval, gap);
    if (shotFrames[j - 1].t <= time && time < shotFrames[j].t) i = j - 1;
  }
  if (i < 0) return null;
  const a = shotFrames[i];
  const b = shotFrames[i + 1];
  const ok = (f) => f.shot === frame.shot && f.calibration?.ok !== false;
  if (!ok(a) || !ok(b)) return null;
  if (b.t - a.t > 1.5 * interval + EPS) return null;
  if (Math.abs(frame.t - a.t) > EPS && Math.abs(frame.t - b.t) > EPS) return null;
  return { a, b, k: (time - a.t) / (b.t - a.t) };
}

const lerp = (p, q, k) => p + (q - p) * k;
const has = (o) => o && o.x != null && o.y != null;
const lerpOpt = (p, q, k) => (Number.isFinite(p) && Number.isFinite(q) ? lerp(p, q, k) : null);

/**
 * What to draw at `time`: `frame` itself when snapping (identity preserved), otherwise a copy with each person
 * (paired by personKey) and the ball linearly interpolated between the bracketing frames. A person or ball missing
 * from the other frame is shown where `frame` has them.
 */
export function displayFrame(frame, shotFrames, time) {
  const br = bracket(frame, shotFrames, time);
  if (!br) return frame;
  const { a, b, k } = br;
  const other = Math.abs(frame.t - a.t) < EPS ? b : a;
  const pair = (p, q) => (Math.abs(frame.t - a.t) < EPS ? [p, q] : [q, p]);

  const players = frame.players.map((p) => {
    if (!has(p)) return p;
    const key = personKey(p);
    const q = other.players.find((o) => personKey(o) === key);
    if (!has(q)) return p;
    const [pa, pb] = pair(p, q);
    return {
      ...p,
      x: lerp(pa.x, pb.x, k),
      y: lerp(pa.y, pb.y, k),
      vx: lerpOpt(pa.vx, pb.vx, k) ?? p.vx,
      vy: lerpOpt(pa.vy, pb.vy, k) ?? p.vy,
    };
  });

  let ball = frame.ball;
  if (has(frame.ball) && has(other.ball)) {
    const [ba, bb] = pair(frame.ball, other.ball);
    ball = { ...frame.ball, x: lerp(ba.x, bb.x, k), y: lerp(ba.y, bb.y, k), z: lerpOpt(ba.z, bb.z, k) ?? frame.ball.z };
  }
  return { ...frame, t: time, players, ball };
}

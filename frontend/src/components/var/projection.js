// Pure geometry for drawing pitch-space graphics onto the broadcast frame.
// H is the frame's 3x3 row-major homography: pitch metres [x, y, 1] -> image pixels [u, v, w] (divide by w),
// in full video resolution (analysis.video.width x height).

const EPS = 1e-6;

const wOf = (H, x, y) => H[2][0] * x + H[2][1] * y + H[2][2];

// Homographies are defined up to scale (including sign), so "in front of the camera" is judged
// relative to the pitch centre, which a broadcast calibration always sees in front.
export function frontSign(H, pitch) {
  return Math.sign(wOf(H, pitch.length_m / 2, pitch.width_m / 2)) || 1;
}

// Pitch point -> image pixel, or null if it lies on/behind the camera plane.
export function applyH(H, x, y, sign = 1) {
  const w = wOf(H, x, y);
  if (!(w * sign > EPS)) return null;
  return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w];
}

// Clip a pitch-space polygon (closed) or polyline to the half-plane in front of the camera
// (Sutherland–Hodgman against one plane), then project. Lines stay lines under a homography,
// so clipping first is what keeps a segment from wrapping through infinity.
export function projectPath(H, points, { closed = false, sign = 1 } = {}) {
  const margin = (p) => wOf(H, p[0], p[1]) * sign - 1e-3;
  const out = [];
  const n = points.length;
  const edges = closed ? n : n - 1;
  for (let i = 0; i < n; i++) {
    const a = points[i];
    if (margin(a) > 0) out.push(a);
    if (i >= edges) continue;
    const b = points[(i + 1) % n];
    const ma = margin(a);
    const mb = margin(b);
    if ((ma > 0) !== (mb > 0)) {
      const t = ma / (ma - mb);
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
  }
  return out.map((p) => applyH(H, p[0], p[1], sign)).filter(Boolean);
}

// Liang–Barsky: clip image segment a-b to the rectangle [0,w] x [0,h]; null if fully outside.
export function clipSegmentToRect(a, b, w, h) {
  let t0 = 0;
  let t1 = 1;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  for (const [p, q] of [[-dx, a[0]], [dx, w - a[0]], [-dy, a[1]], [dy, h - a[1]]]) {
    if (Math.abs(p) < EPS) {
      if (q < 0) return null;
      continue;
    }
    const r = q / p;
    if (p < 0) t0 = Math.max(t0, r);
    else t1 = Math.min(t1, r);
    if (t0 > t1) return null;
  }
  return [
    [a[0] + dx * t0, a[1] + dy * t0],
    [a[0] + dx * t1, a[1] + dy * t1],
  ];
}

// Where an object-fit: contain video actually paints inside its box.
export function containRect(srcW, srcH, boxW, boxH) {
  if (!srcW || !srcH || !boxW || !boxH) return { x: 0, y: 0, w: boxW || 0, h: boxH || 0 };
  const scale = Math.min(boxW / srcW, boxH / srcH);
  const w = srcW * scale;
  const h = srcH * scale;
  return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h };
}

// Image pixel (analysis resolution) -> CSS pixel inside the overlay box.
export const toScreen = (p, imageSize, rect) => [rect.x + (p[0] * rect.w) / imageSize[0], rect.y + (p[1] * rect.h) / imageSize[1]];

// Pitch-space shapes for the offside graphic, clipped to the pitch.
export function offsideShapes(pitch, { lineX, uncertainty = 0, attackerX = null }) {
  const L = pitch.length_m;
  const W = pitch.width_m;
  const clampX = (x) => Math.max(0, Math.min(L, x));
  const line = (x) => (x >= 0 && x <= L ? [[x, 0], [x, W]] : null);
  const lo = clampX(lineX - uncertainty);
  const hi = clampX(lineX + uncertainty);
  return {
    line: line(lineX),
    band: uncertainty > 0 && hi > lo ? [[lo, 0], [hi, 0], [hi, W], [lo, W]] : null,
    attacker: attackerX == null ? null : line(attackerX),
  };
}

// A circle of radius r metres on the grass around (x, y), as a closed pitch-space polygon.
export function groundCircle(x, y, r, n = 28) {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2;
    return [x + r * Math.cos(a), y + r * Math.sin(a)];
  });
}

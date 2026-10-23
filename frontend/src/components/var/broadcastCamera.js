// Recover the broadcast camera from a pitch→image homography. Pure maths (no three.js) so it runs in jsdom.
//
// H maps pitch metres [x, y, 1] to image pixels [u, v, w] (divide by w), full video resolution.
// Assumptions: square pixels, zero skew, principal point at the image centre, so K = [[f,0,cx],[0,f,cy],[0,0,1]].
//
// 1. Centre the principal point: H' = T·H with T = [[1,0,-cx],[0,1,-cy],[0,0,1]], so H' ∝ diag(f,f,1)·[r1 r2 t].
// 2. r1 ⟂ r2 and |r1| = |r2| give two linear equations in s = 1/f² (Zhang), with h1, h2 the columns of H':
//      (h1x·h2x + h1y·h2y)·s + h1z·h2z = 0
//      (h1x² + h1y² − h2x² − h2y²)·s + (h1z² − h2z²) = 0
//    solved together in least squares: s = −Σ aᵢbᵢ / Σ aᵢ².
// 3. [r1 r2 t] = λ·K⁻¹H', |λ| = 2 / (|K⁻¹h1| + |K⁻¹h2|), sign chosen so the camera is above the pitch.
//    r1, r2 are re-orthonormalised (Gram–Schmidt) and r3 = r1 × r2.
// 4. Camera centre in pitch coords C = −Rᵀt; the rows of R are the camera's x (right), y (down), z (forward) axes.
//    Pitch (x, y, z) maps to world (x − L/2, −z, y − W/2) (toWorld in varMath; pitch z points into the ground).

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);
const unit = (a) => scale(a, 1 / norm(a));
// Pitch-frame direction -> three.js world direction.
const worldDir = (d) => [d[0], -d[2], d[1]];

/**
 * @param {number[][]|number[]} H 3x3 row-major (nested or flat)
 * @param {[number, number]} imageSize [width, height] px
 * @param {{length_m: number, width_m: number}} pitch
 * @returns {null | {position, target, forward, up, right, fov, focal, aspect}}
 *   world-space vectors; fov = vertical field of view of the image in degrees.
 */
export function cameraFromHomography(H, imageSize, pitch) {
  const m = Array.isArray(H) ? H.flat() : null;
  if (!m || m.length !== 9 || !m.every(Number.isFinite)) return null;
  const [w, h] = imageSize || [];
  if (!(w > 0 && h > 0) || !pitch) return null;
  const cx = w / 2;
  const cy = h / 2;
  const col = (j) => [m[j] - cx * m[6 + j], m[3 + j] - cy * m[6 + j], m[6 + j]];
  const [h1, h2, h3] = [col(0), col(1), col(2)];

  const a1 = h1[0] * h2[0] + h1[1] * h2[1];
  const b1 = h1[2] * h2[2];
  const a2 = h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2;
  const b2 = h1[2] ** 2 - h2[2] ** 2;
  const denom = a1 * a1 + a2 * a2;
  if (!(denom > 0)) return null;
  const s = -(a1 * b1 + a2 * b2) / denom;
  if (!(s > 0)) return null; // affine / top-down / inconsistent H: focal length unobservable
  const f = 1 / Math.sqrt(s);

  // The overall sign of H is arbitrary. The wrong sign mirrors the camera below the pitch, so solve with +1
  // and flip if the camera comes out underground.
  const solve = (sign) => {
    const kinv = (c) => [(sign * c[0]) / f, (sign * c[1]) / f, sign * c[2]];
    const [m1, m2, m3] = [kinv(h1), kinv(h2), kinv(h3)];
    const n1 = norm(m1);
    const n2 = norm(m2);
    const t = scale(m3, 2 / (n1 + n2));
    const r1 = unit(m1);
    const r2 = unit(m2.map((v, i) => v - dot(r1, m2) * r1[i]));
    const r3 = cross(r1, r2);
    // C = −Rᵀt with R = [r1 r2 r3] as columns; camera axes are the rows of R.
    const C = [-dot(r1, t), -dot(r2, t), -dot(r3, t)];
    return {
      position: [C[0] - pitch.length_m / 2, -C[2], C[1] - pitch.width_m / 2],
      right: worldDir([r1[0], r2[0], r3[0]]),
      up: scale(worldDir([r1[1], r2[1], r3[1]]), -1),
      forward: worldDir([r1[2], r2[2], r3[2]]),
    };
  };
  let pose = solve(1);
  if (!(pose.position[1] > 0)) pose = solve(-1);
  const { position, right, up, forward } = pose;
  if (!position.every(Number.isFinite)) return null;
  if (!(position[1] > 0.5) || !(forward[1] < 0)) return null; // below the pitch or looking at the sky
  const fov = (2 * Math.atan(h / 2 / f) * 180) / Math.PI;
  if (!(fov > 1 && fov < 120)) return null;

  // Orbit pivot: where the optical axis meets the pitch.
  const k = -position[1] / forward[1];
  const target = [position[0] + forward[0] * k, 0, position[2] + forward[2] * k];
  return { position, target, forward, up, right, fov, focal: f, aspect: w / h };
}

// Vertical fov that shows the whole image (object-fit: contain) in a viewport of a different aspect.
export function fitFov(fov, imageAspect, viewAspect) {
  if (!(viewAspect > 0) || viewAspect >= imageAspect) return fov;
  const half = (fov * Math.PI) / 360;
  return (Math.atan((Math.tan(half) * imageAspect) / viewAspect) * 360) / Math.PI;
}

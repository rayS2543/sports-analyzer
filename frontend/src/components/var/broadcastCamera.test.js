import { describe, expect, it } from "vitest";
import { cameraFromHomography, fitFov } from "./broadcastCamera";

const pitch = { length_m: 105, width_m: 68 };
const size = [1280, 720];
const sub = (a, b) => a.map((v, i) => v - b[i]);
const add = (a, b) => a.map((v, i) => v + b[i]);
const mul = (a, k) => a.map((v) => v * k);
const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a) => mul(a, 1 / Math.hypot(...a));

// Build H = K [r1 r2 t] for a camera defined in three.js world space (the inverse of what's under test).
function synth({ position, target, fov, roll = 0, scale = 1 }) {
  const fwd = unit(sub(target, position));
  let right = unit(cross(fwd, [0, 1, 0]));
  let up = cross(right, fwd);
  [right, up] = [add(mul(right, Math.cos(roll)), mul(up, Math.sin(roll))), add(mul(up, Math.cos(roll)), mul(right, -Math.sin(roll)))];
  const toPitch = (d) => [d[0], d[2], -d[1]]; // world direction -> pitch direction
  const C = [position[0] + pitch.length_m / 2, position[2] + pitch.width_m / 2, -position[1]];
  const R = [toPitch(right), mul(toPitch(up), -1), toPitch(fwd)]; // rows: camera x (right), y (down), z (forward)
  const t = R.map((row) => -dot(row, C));
  const f = size[1] / 2 / Math.tan((fov * Math.PI) / 360);
  const cols = [R.map((row) => row[0]), R.map((row) => row[1]), t];
  const K = (v) => [f * v[0] + (size[0] / 2) * v[2], f * v[1] + (size[1] / 2) * v[2], v[2]];
  const Kc = cols.map(K);
  return { H: [0, 1, 2].map((i) => Kc.map((c) => c[i] * scale)), fwd, up, f };
}

const project = (H, x, y) => {
  const [u, v, w] = H.map((r) => r[0] * x + r[1] * y + r[2]);
  return [u / w, v / w];
};

const cameras = {
  "main camera, wide": { position: [0, 22, 75], target: [10, 0, 0], fov: 24 },
  "main camera, tight zoom with roll": { position: [-5, 28, 90], target: [30, 0, 5], fov: 7, roll: 0.03 },
  "low 18-yard camera": { position: [-36, 9, 50], target: [-45, 0, -5], fov: 35, roll: -0.02 },
};

describe("cameraFromHomography", () => {
  for (const [name, cam] of Object.entries(cameras)) {
    it(`round-trips pose and fov: ${name}`, () => {
      const { H, fwd, up } = synth(cam);
      const rec = cameraFromHomography(H, size, pitch);
      expect(rec).not.toBeNull();
      rec.position.forEach((v, i) => expect(v).toBeCloseTo(cam.position[i], 4));
      rec.forward.forEach((v, i) => expect(v).toBeCloseTo(fwd[i], 6));
      rec.up.forEach((v, i) => expect(v).toBeCloseTo(up[i], 6));
      expect(rec.fov).toBeCloseTo(cam.fov, 6);
      expect(rec.aspect).toBeCloseTo(16 / 9, 9);
      expect(rec.target[1]).toBe(0);
    });
  }

  it("reprojects pitch points onto the same pixels as H", () => {
    const { H } = synth(cameras["main camera, wide"]);
    const rec = cameraFromHomography(H, size, pitch);
    for (const [x, y] of [[52.5, 34], [88.5, 34], [105, 0], [16.5, 13.84], [70, 60]]) {
      const d = sub([x - 52.5, 0, y - 34], rec.position);
      const zc = dot(d, rec.forward);
      const u = 640 + (rec.focal * dot(d, rec.right)) / zc;
      const v = 360 - (rec.focal * dot(d, rec.up)) / zc;
      const [eu, ev] = project(H, x, y);
      expect(Math.hypot(u - eu, v - ev)).toBeLessThan(1e-6);
    }
  });

  it("ignores the homography's overall scale and sign, and accepts a flat list", () => {
    const cam = cameras["main camera, tight zoom with roll"];
    const ref = cameraFromHomography(synth(cam).H, size, pitch);
    for (const scale of [-3.7, 1e-4, 250]) {
      const rec = cameraFromHomography(synth({ ...cam, scale }).H.flat(), size, pitch);
      rec.position.forEach((v, i) => expect(v).toBeCloseTo(ref.position[i], 5));
      expect(rec.fov).toBeCloseTo(ref.fov, 8);
    }
  });

  it("survives a slightly noisy homography", () => {
    const cam = cameras["main camera, wide"];
    const { H } = synth(cam);
    const noisy = H.map((r, i) => r.map((v, j) => v * (1 + 1e-4 * Math.sin(3 * i + j + 1))));
    const rec = cameraFromHomography(noisy, size, pitch);
    expect(Math.hypot(...sub(rec.position, cam.position))).toBeLessThan(1.5);
    expect(Math.abs(rec.fov - cam.fov)).toBeLessThan(0.5);
  });

  it("returns null for missing or degenerate input", () => {
    expect(cameraFromHomography(null, size, pitch)).toBeNull();
    expect(cameraFromHomography([[1, 0], [0, 1]], size, pitch)).toBeNull();
    expect(cameraFromHomography([[1, 0, 0], [0, 1, 0], [0, 0, NaN]], size, pitch)).toBeNull();
    expect(cameraFromHomography(synth(cameras["main camera, wide"]).H, null, pitch)).toBeNull();
    // Affine map (no perspective): the focal length is unobservable.
    expect(cameraFromHomography([[12, 0, 10], [0, 12, 20], [0, 0, 1]], size, pitch)).toBeNull();
    expect(cameraFromHomography([[0, 0, 0], [0, 0, 0], [0, 0, 0]], size, pitch)).toBeNull();
  });
});

describe("fitFov", () => {
  it("keeps the image fov when the viewport is at least as wide", () => {
    expect(fitFov(20, 16 / 9, 16 / 9)).toBe(20);
    expect(fitFov(20, 16 / 9, 2.4)).toBe(20);
  });

  it("widens the vertical fov so a narrower viewport still shows the full image width", () => {
    const fov = fitFov(20, 16 / 9, 1);
    const hfov = (a, fv) => 2 * Math.atan(Math.tan((fv * Math.PI) / 360) * a);
    expect(hfov(1, fov)).toBeCloseTo(hfov(16 / 9, 20), 9);
  });
});

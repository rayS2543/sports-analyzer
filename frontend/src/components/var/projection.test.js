import { describe, expect, it } from "vitest";
import sample from "./fixtures/sampleAnalysis.json";
import { applyH, clipSegmentToRect, containRect, frontSign, groundCircle, offsideShapes, projectPath, toScreen } from "./projection";

const pitch = sample.pitch;
const frame = sample.frames.find((f) => f.t === 13.2);
const H = frame.calibration.homography;

describe("homography projection", () => {
  it("puts every tracked player's ground position on their detected foot pixel", () => {
    for (const p of frame.players) {
      const [u, v] = applyH(H, p.x, p.y, frontSign(H, pitch));
      // Fixture positions are rounded to 1 cm and pixels to 1 px.
      expect(Math.abs(u - p.foot[0])).toBeLessThan(2);
      expect(Math.abs(v - p.foot[1])).toBeLessThan(2);
    }
  });

  it("maps the offside line to a straight segment between the two touchlines", () => {
    const { line } = offsideShapes(pitch, { lineX: 81.29 });
    const [far, near] = projectPath(H, line, { sign: frontSign(H, pitch) });
    expect(far[1]).toBeLessThan(near[1]); // far touchline is higher in the broadcast image
    const mid = applyH(H, 81.29, pitch.width_m / 2);
    // Homographies keep lines straight: the midpoint lies on the projected segment.
    const cross = (near[0] - far[0]) * (mid[1] - far[1]) - (near[1] - far[1]) * (mid[0] - far[0]);
    expect(Math.abs(cross) / Math.hypot(near[0] - far[0], near[1] - far[1])).toBeLessThan(1e-6);
  });

  it("clips geometry behind the camera instead of wrapping it through infinity", () => {
    // Camera plane at y = 50: w = 50 - y, so only y < 50 is in front.
    const Hc = [[1, 0, 0], [0, 1, 0], [0, -1, 50]];
    expect(applyH(Hc, 0, 60)).toBeNull();
    const pts = projectPath(Hc, [[0, 0], [0, 100]]);
    expect(pts).toHaveLength(2);
    expect(pts[1][1]).toBeGreaterThan(1000); // clipped just in front of the plane: far away but finite
    expect(Number.isFinite(pts[1][1])).toBe(true);
  });

  it("builds the uncertainty band clipped to the pitch and a ground circle", () => {
    const { band, attacker } = offsideShapes(pitch, { lineX: 104.8, uncertainty: 0.5, attackerX: 103 });
    expect(band.map((p) => p[0])).toEqual([104.3, 105, 105, 104.3]);
    expect(attacker).toEqual([[103, 0], [103, 68]]);
    expect(offsideShapes(pitch, { lineX: 50 }).band).toBeNull();
    expect(groundCircle(10, 10, 1, 4)[1][1]).toBeCloseTo(11);
  });
});

describe("screen mapping", () => {
  it("letterboxes a 16:9 video inside a square box", () => {
    expect(containRect(1280, 720, 400, 400)).toEqual({ x: 0, y: 87.5, w: 400, h: 225 });
    expect(toScreen([640, 360], [1280, 720], containRect(1280, 720, 400, 400))).toEqual([200, 200]);
  });

  it("clips image segments to the viewport", () => {
    expect(clipSegmentToRect([-100, 50], [200, 50], 100, 100)).toEqual([[0, 50], [100, 50]]);
    expect(clipSegmentToRect([-10, -10], [-5, -1], 100, 100)).toBeNull();
  });
});

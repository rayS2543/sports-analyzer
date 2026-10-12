import { describe, expect, it } from "vitest";
import { bracket, displayFrame } from "./displayFrame";

const P = (track_id, x, y, extra = {}) => ({ track_id, role: "player", team: "A", x, y, ...extra });
const F = (t, players, { shot = 0, ok = true, ball = null } = {}) => ({ t, shot, calibration: { ok }, players, ball });

const f0 = F(1.0, [P(1, 10, 20, { vx: 2, vy: 0 }), P(2, 30, 30)], { ball: { x: 50, y: 30, z: 0 } });
const f1 = F(1.1, [P(1, 11, 21, { vx: 4, vy: 2 }), P(2, 30, 31), P(3, 5, 5)], { ball: { x: 52, y: 30, z: 1 } });
const f2 = F(1.2, [P(1, 12, 22)]);
const shot = [f0, f1, f2];

describe("displayFrame", () => {
  it("is exactly the sampled frame when time sits on it", () => {
    expect(displayFrame(f1, shot, 1.1)).toBe(f1);
    expect(displayFrame(f0, shot, 1.0)).toBe(f0);
  });

  it("interpolates people and the ball between the bracketing frames", () => {
    const d = displayFrame(f0, shot, 1.025);
    const p1 = d.players.find((p) => p.track_id === 1);
    expect(p1.x).toBeCloseTo(10.25, 9);
    expect(p1.y).toBeCloseTo(20.25, 9);
    expect(p1.vx).toBeCloseTo(2.5, 9);
    expect(d.ball.x).toBeCloseTo(50.5, 9);
    expect(d.ball.z).toBeCloseTo(0.25, 9);
    expect(d.t).toBe(1.025);
  });

  it("gives the same position whichever bracketing frame the viewer is showing", () => {
    const fromA = displayFrame(f0, shot, 1.06).players[0];
    const fromB = displayFrame(f1, shot, 1.06).players.find((p) => p.track_id === 1);
    expect(fromA.x).toBeCloseTo(fromB.x, 9);
    expect(fromA.y).toBeCloseTo(fromB.y, 9);
  });

  it("pairs people by global_id when present, not the per-shot track id", () => {
    const a = F(0, [P(1, 0, 0, { global_id: 9 })]);
    const b = F(0.1, [P(1, 50, 50, { global_id: 4 }), P(2, 2, 0, { global_id: 9 })]);
    expect(displayFrame(a, [a, b], 0.05).players[0].x).toBeCloseTo(1, 9);
  });

  it("snaps a person missing from the other frame", () => {
    const d = displayFrame(f1, shot, 1.09);
    expect(d.players.find((p) => p.track_id === 3)).toBe(f1.players[2]);
  });

  it("snaps across gaps wider than 1.5 sample intervals (e.g. a dropped uncalibrated frame)", () => {
    const gappy = [f0, f2, F(1.3, [P(1, 13, 23)])];
    expect(bracket(f0, gappy, 1.05)).toBeNull();
    expect(displayFrame(f0, gappy, 1.05)).toBe(f0);
  });

  it("never interpolates across shots or into an uncalibrated frame", () => {
    const cut = F(1.1, [P(1, 90, 10)], { shot: 1 });
    expect(displayFrame(f0, [f0, cut, F(1.2, [], { shot: 1 })], 1.05)).toBe(f0);
    const bad = F(1.1, [P(1, 90, 10)], { ok: false });
    expect(displayFrame(f0, [f0, bad, f2], 1.05)).toBe(f0);
  });

  it("snaps when the viewer's frame isn't one of the bracketing frames, or data is missing", () => {
    expect(displayFrame(f2, shot, 1.05)).toBe(f2);
    expect(displayFrame(f0, null, 1.05)).toBe(f0);
    expect(displayFrame(f0, [f0], 1.05)).toBe(f0);
    expect(displayFrame(null, shot, 1.05)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import sample from "./fixtures/sampleAnalysis.json";
import { cameraPreset, frameAt, legible, nearestCalibratedTime, parseWindow, pitchMarkings, personColors, shotAt, stepFrameTime, toWorld, windowAround } from "./varMath";

const shots = [
  { id: 0, start: 0, end: 2 },
  { id: 1, start: 2, end: 4 },
];
const frame = (t, shot, ok = true) => ({ t, shot, calibration: { ok }, players: [] });
const analysis = (frames) => ({ shots, frames, video: { sampled_fps: 5 } });

describe("frameAt", () => {
  it("picks the nearest sampled frame in the current shot", () => {
    const a = analysis([frame(0.2, 0), frame(0.4, 0), frame(0.6, 0)]);
    expect(frameAt(a, 0.45)).toMatchObject({ status: "ok", frame: { t: 0.4 } });
    expect(frameAt(a, 0.55).frame.t).toBe(0.6);
  });

  it("never reaches across a shot cut, even when the other shot's frame is nearer", () => {
    const a = analysis([frame(1.9, 0), frame(2.3, 1)]);
    // t=2.05 is 0.15s from the shot-0 frame but belongs to shot 1.
    expect(frameAt(a, 2.05)).toMatchObject({ status: "ok", frame: { t: 2.3 }, shot: { id: 1 } });
  });

  it("reports uncalibrated frames instead of showing positions", () => {
    const a = analysis([frame(2.2, 1, false)]);
    expect(frameAt(a, 2.2)).toMatchObject({ status: "uncalibrated", frame: { t: 2.2 } });
  });

  it("treats a frame more than two sample intervals away as missing", () => {
    const a = analysis([frame(0.2, 0)]);
    expect(frameAt(a, 0.55).status).toBe("ok");
    expect(frameAt(a, 1.5)).toMatchObject({ status: "no-frame", frame: null, shot: { id: 0 } });
  });

  it("gives window edges to the edge shots when shots start on real video frames", () => {
    const a = { ...analysis([frame(1.001, 0)]), shots: [{ id: 0, start: 1.001, end: 6.006 }], window: { start: 1, end: 6 } };
    expect(frameAt(a, 1)).toMatchObject({ status: "ok", frame: { t: 1.001 } });
  });

  it("returns no frame outside every shot", () => {
    expect(frameAt(analysis([frame(0.2, 0)]), 9).status).toBe("no-frame");
    expect(shotAt(shots, 4).id).toBe(1); // last shot owns its end instant
  });

  it("works on the sample fixture: shot 0 calibrated, shot 1 not, nothing outside the window", () => {
    expect(frameAt(sample, 13.21)).toMatchObject({ status: "ok", frame: { t: 13.2 } });
    expect(frameAt(sample, 13.21).frame.players).toHaveLength(20); // only people the camera sees
    expect(frameAt(sample, 13.21).frame.calibration.homography).toHaveLength(3);
    expect(frameAt(sample, 15).status).toBe("uncalibrated");
    expect(nearestCalibratedTime(sample.frames, 15)).toBe(14.1);
    expect(frameAt(sample, 11.9)).toMatchObject({ status: "outside", frame: null });
    expect(frameAt(sample, 30).status).toBe("outside");
  });
});

describe("analysis window", () => {
  it("takes 3 s before and 2 s after the paused moment, rounded to 0.1 s", () => {
    expect(windowAround(20.04, { duration: 74 })).toEqual({ start: 17, end: 22 });
  });

  it("clamps to the clip and caps the window at 10 s", () => {
    expect(windowAround(1, { duration: 74 })).toEqual({ start: 0, end: 3 });
    expect(windowAround(73.5, { duration: 74 })).toEqual({ start: 70.5, end: 74 });
    expect(windowAround(30, { before: 8, after: 8, duration: 74 })).toEqual({ start: 22, end: 32 });
  });

  it("parses deep-link windows and rejects bad ones", () => {
    expect(parseWindow("12.0", "17.0")).toEqual({ start: 12, end: 17 });
    expect(parseWindow("17", "12")).toBeNull();
    expect(parseWindow("0", "11")).toBeNull();
    expect(parseWindow(null, "5")).toBeNull();
  });
});

describe("stepFrameTime", () => {
  const frames = [frame(0.2, 0), frame(0.4, 0), frame(2.2, 1)];
  it("steps to neighbouring sampled frames", () => {
    expect(stepFrameTime(frames, 0.4, 1)).toBe(2.2);
    expect(stepFrameTime(frames, 0.4, -1)).toBe(0.2);
    expect(stepFrameTime(frames, 0.2, -1)).toBeNull();
  });
});

describe("pitch geometry", () => {
  const pitch = { length_m: 105, width_m: 68 };

  it("centres the pitch with broadcast-down mapped to +z", () => {
    expect(toWorld(0, 0, pitch)).toEqual([-52.5, 0, -34]);
    expect(toWorld(105, 68, pitch)).toEqual([52.5, 0, 34]);
  });

  it("draws IFAB-sized boxes at both ends", () => {
    const rects = pitchMarkings(pitch).filter((m) => m.kind === "rect");
    expect(rects).toContainEqual({ kind: "rect", x: 88.5, y: 13.84, w: 16.5, h: 40.32 });
    expect(rects.filter((r) => r.w === 5.5)).toHaveLength(2);
  });

  it("looks along the offside line in the behind-the-line preset", () => {
    const { position, target } = cameraPreset("line", pitch, { focusX: 80 });
    expect(position[0]).toBeCloseTo(27.5);
    expect(target[0]).toBeCloseTo(27.5);
  });

  it("colours referees neutrally and keepers distinct from their team", () => {
    const teams = { A: { color: "#c8102e" } };
    expect(personColors({ role: "referee", team: null }, teams).body).not.toBe("#c8102e");
    const gk = personColors({ role: "goalkeeper", team: "A" }, teams);
    expect(gk.ring).toBe(legible("#c8102e"));
    expect(gk.body).not.toBe(gk.ring);
  });

  it("keeps measured hue but lifts muddy kit colours to legible ones", () => {
    expect(legible("#ffffff")).toBe("#ffffff");
    expect(legible("#1d3c8f")).toBe("#406ad8"); // still blue, brighter
    expect(legible("#5b4e5f")).toBe("#ae4dcb"); // Barça's measured mud → clearly not referee grey
  });
});

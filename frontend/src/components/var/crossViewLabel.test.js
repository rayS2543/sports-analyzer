import { describe, expect, it } from "vitest";
import { crossViewLabel } from "./VarViewer";

const frame = (calibration, live_t) => ({ calibration, live_t });

describe("crossViewLabel", () => {
  it("names a calibrated replay sync, and nothing else", () => {
    const synced = frame({ ok: true, source: "cross_view", cross_view: { speed: 0.4 } }, 3.27);
    expect(crossViewLabel(synced, null)).toBe("Replay ×0.4 · synced to live 0:03.3");
    expect(crossViewLabel(frame({ ok: true, source: "detected" }, 3.27), { playback_speed: 0.4 })).toBeNull();
    expect(crossViewLabel(frame({ ok: true, source: "propagated" }, 3.27), { playback_speed: 0.4 })).toBeNull();
    expect(crossViewLabel(frame({ ok: false, source: "cross_view", cross_view: { speed: 0.4 } }, 3.27), null)).toBeNull();
  });

  it("borrows the shot speed, and drops a multiplier or a clock that is not a number", () => {
    expect(crossViewLabel(frame({ ok: true, source: "cross_view" }, 3.27), { playback_speed: 0.25 })).toBe(
      "Replay ×0.25 · synced to live 0:03.3",
    );
    expect(crossViewLabel(frame({ ok: true, source: "cross_view" }, Number.NaN), {})).toBe("Replay");
  });
});

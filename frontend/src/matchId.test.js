import { describe, expect, it } from "vitest";
import { decodeMatchId, encodeMatchId } from "./matchId";

describe("match id", () => {
  it("round-trips the fixture, including accented club names", () => {
    const fixture = {
      league: "CL",
      date: "2026-10-21",
      home: "FC Bayern München",
      away: "Atlético Madrid",
    };
    const id = encodeMatchId(fixture);
    expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeMatchId(id)).toEqual(fixture);
  });

  it("keeps a slash or non-latin letter in the club name out of the url", () => {
    const fixture = {
      league: "CL",
      date: "2026-10-21",
      home: "Bodø/Glimt",
      away: "ŠK Slovan Bratislava",
    };
    const id = encodeMatchId(fixture);
    expect(id).not.toMatch(/[+/=]/);
    expect(decodeMatchId(id)).toEqual(fixture);
  });
});

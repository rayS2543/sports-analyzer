import { describe, expect, it } from "vitest";
import { decodeMatchId, encodeMatchId } from "./matchId";

describe("encodeMatchId", () => {
  it("round-trips accented club names into a url-safe id", () => {
    const match = {
      league: "PD",
      date: "2026-10-21",
      home: "Atlético Madrid",
      away: "Real Sociedad de Fútbol",
    };

    const id = encodeMatchId(match);

    expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeMatchId(id)).toEqual(match);
  });
});

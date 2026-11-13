import { describe, expect, it } from "vitest";
import { decodeMatchId, encodeMatchId } from "./matchId";

describe("match ids", () => {
  it("round-trips league, date, and club names, including accents and slashes", () => {
    const fixture = { league: "CL", date: "2026-10-21", home: "Bodø/Glimt", away: "Atlético Madrid" };

    const id = encodeMatchId(fixture);

    expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeMatchId(id)).toEqual(fixture);
  });

  it("gives two fixtures different ids when only the away club changes", () => {
    const home = { league: "PD", date: "2026-09-12", home: "Real Madrid", away: "Barcelona" };
    const away = { ...home, away: "Getafe" };

    expect(encodeMatchId(home)).not.toBe(encodeMatchId(away));
    expect(decodeMatchId(encodeMatchId(away)).away).toBe("Getafe");
  });
});

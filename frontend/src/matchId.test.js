import { describe, expect, it } from "vitest";
import { decodeMatchId, encodeMatchId } from "./matchId";

describe("matchId", () => {
  it("round-trips club names that are not Latin-1 and stays safe in a path", () => {
    const match = {
      league: "CL",
      date: "2026-10-21",
      home: "ŠK Slovan Bratislava",
      away: "FK Bodø/Glimt",
    };
    const id = encodeMatchId(match);
    expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeMatchId(id)).toEqual(match);
  });

  it("rewrites base64 characters that would break a URL path", () => {
    const candidates = [
      { league: "PD", date: "2026-01-01", home: "???", away: "A" },
      { league: "PD", date: "2026-01-01", home: ">>>", away: "A" },
      { league: "PD", date: "2026-01-01", home: "subjects", away: "data" },
    ];
    const standard = (match) => {
      const raw = `${match.league}|${match.date}|${match.home}|${match.away}`;
      return btoa(unescape(encodeURIComponent(raw)));
    };
    const tricky = candidates.find((match) => /[+/=]/.test(standard(match)));
    expect(tricky).toBeTruthy();
    const id = encodeMatchId(tricky);
    expect(id).not.toMatch(/[+/=]/);
    expect(decodeMatchId(id)).toEqual(tricky);
  });
});

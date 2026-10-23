import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "../apiBase";
import TodayGames from "./TodayGames";

const uclMatch = {
  id: 1,
  league_code: "CL",
  league_name: "Champions League",
  home: "Arsenal",
  away: "Bayern Munich",
  home_score: 1,
  away_score: 0,
  status: "IN_PLAY",
  kickoff: "2026-10-21T19:00:00Z",
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const body = String(url).includes("/leagues")
      ? [{ code: "CL", name: "Champions League", country: "Europe" }]
      : [uclMatch];
    return Promise.resolve({ json: async () => body });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TodayGames", () => {
  it("asks for the viewer's local day and shows Champions League fixtures", async () => {
    render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );

    expect(await screen.findByText("Arsenal")).toBeInTheDocument();
    expect(screen.getByText("Bayern Munich")).toBeInTheDocument();
    expect(screen.getAllByText("Champions League").length).toBeGreaterThan(0);
    expect(screen.getByText("Live")).toBeInTheDocument();

    const matchUrl = global.fetch.mock.calls.map((call) => String(call[0])).find((url) => url.includes("/matches/today"));
    expect(matchUrl).toMatch(new RegExp(`^${API_BASE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/matches/today\\?date=\\d{4}-\\d{2}-\\d{2}$`));
  });
});

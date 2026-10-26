import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard";

const mockOverview = {
  league: "PD",
  league_name: "La Liga",
  date: "2026-10-23",
  leagues: [{ code: "PD", name: "La Liga", country: "Spain" }],
  today_matches: [
    {
      id: 901,
      league_code: "PD",
      league_name: "La Liga",
      home: "Real Madrid",
      away: "Barcelona",
      home_score: 2,
      away_score: 1,
      status: "IN_PLAY",
      kickoff: "2026-10-23T20:00:00Z",
    },
  ],
  standings: [
    {
      position: 1,
      team_name: "Real Madrid",
      tla: "RMA",
      crest: null,
      playedGames: 10,
      won: 8,
      draw: 1,
      lost: 1,
      points: 25,
      goalsFor: 22,
      goalsAgainst: 8,
      goalDifference: 14,
    },
  ],
  matches: [
    {
      id: 801,
      home: "Real Madrid",
      away: "Sevilla",
      score: "3 - 0",
      winner: "Real Madrid",
      date: "2026-10-18",
    },
  ],
  teams: [
    {
      id: 1,
      name: "Real Madrid CF",
      shortName: "Real Madrid",
      tla: "RMA",
      crest: null,
    },
  ],
  predictions: [
    {
      home: "Real Madrid",
      away: "Valencia",
      date: "2026-10-28",
      predicted_winner: "Real Madrid",
      predicted_result: "home",
      home_win_pct: 65,
      draw_pct: 20,
      away_win_pct: 15,
      home_elo: 1650,
      away_elo: 1450,
    },
  ],
  ratings: {
    league: "PD",
    window_days: 90,
    matches_used: 50,
    ratings: [
      {
        rank: 1,
        team: "Real Madrid",
        crest: null,
        rating: 1650.0,
        played: 10,
        delta: 120.0,
      },
    ],
  },
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/dashboard-overview")) {
      return Promise.resolve({ json: async () => mockOverview });
    }
    return Promise.resolve({ json: async () => [] });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard fast hydration", () => {
  it("fetches /dashboard-overview and hydrates all child widgets in one request pass", async () => {
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    );

    // Verify /dashboard-overview was requested
    await waitFor(() => {
      const calls = global.fetch.mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("/dashboard-overview?league=PD"))).toBe(true);
    });

    // Verify widgets are hydrated from the single overview response
    expect(await screen.findByText("Today’s games")).toBeInTheDocument();
    expect(screen.getAllByText("Real Madrid").length).toBeGreaterThan(0);
    expect(screen.getByText("3 - 0")).toBeInTheDocument();
    expect(screen.getByText("Valencia")).toBeInTheDocument();
    expect(screen.getByText("1650")).toBeInTheDocument();

    // Verify child components did NOT fire separate redundant network requests
    const calls = global.fetch.mock.calls.map((c) => String(c[0]));
    const redundantCalls = calls.filter(
      (u) =>
        u.includes("/standings?league=PD") ||
        u.includes("/matches?league=PD") ||
        u.includes("/predictions?league=PD") ||
        u.includes("/ratings?league=PD") ||
        u.includes("/teams?league=PD")
    );
    expect(redundantCalls).toHaveLength(0);
  });
});

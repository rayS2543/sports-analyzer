import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "../apiBase";
import { encodeMatchId } from "../matchId";
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

  it("labels each status, links only a finished match, and dims the side that is behind", async () => {
    const kickoff = "2026-10-30T23:30:00Z";
    const scheduled = "2026-10-30T16:00:00Z";
    global.fetch = vi.fn((url) => {
      const body = String(url).includes("/leagues")
        ? [{ code: "PD", name: "La Liga" }, { code: "CL", name: "Champions League" }]
        : [
            { id: 1, league_code: "CL", home: "Arsenal", away: "Bayern Munich", home_score: 1, away_score: 0, status: "IN_PLAY", kickoff },
            { id: 2, league_code: "PD", home: "Real Madrid", away: "Getafe", home_score: 0, away_score: 0, status: "PAUSED", kickoff },
            { id: 3, league_code: "PD", home: "Barcelona", away: "Atlético de Madrid", home_score: 2, away_score: 1, status: "FINISHED", kickoff },
            { id: 4, league_code: "PD", home: "Sevilla", away: "Betis", home_score: null, away_score: null, status: "POSTPONED", kickoff },
            { id: 5, league_code: "PL", home: "Liverpool", away: "Everton", home_score: null, away_score: null, status: "SUSPENDED", kickoff },
            { id: 6, league_code: "SA", home: "Milan", away: "Roma", home_score: null, away_score: null, status: "CANCELLED", kickoff },
            { id: 7, league_code: "BL1", home: "Dortmund", away: "Leipzig", home_score: null, away_score: null, status: "SCHEDULED", kickoff: scheduled },
            { id: 8, league_code: "FL1", home: "Lyon", away: "Marseille", home_score: 0, away_score: 1, status: "LIVE", kickoff },
          ];
      return Promise.resolve({ json: async () => body });
    });

    render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );

    expect(await screen.findByText("Half-time")).toBeInTheDocument();
    expect(screen.getAllByText("Live")).toHaveLength(2);
    expect(screen.getByText(/3 live now/)).toBeInTheDocument();
    expect(screen.getByText("Full-time")).toBeInTheDocument();
    expect(screen.getByText("Postponed")).toBeInTheDocument();
    expect(screen.getByText("Suspended")).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText(new Date(scheduled).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))).toBeInTheDocument();

    const finished = `/match/${encodeMatchId({ league: "PD", date: "2026-10-30", home: "Barcelona", away: "Atlético de Madrid" })}`;
    expect(screen.getByRole("link", { name: /Barcelona/ })).toHaveAttribute("href", finished);
    expect(screen.getAllByRole("link")).toHaveLength(1);

    const level = screen.getByText("Real Madrid").closest("li");
    expect(within(level).getByText("Real Madrid")).not.toHaveClass("text-muted");
    expect(within(level).getByText("Getafe")).not.toHaveClass("text-muted");
    const live = screen.getByText("Arsenal").closest("li");
    expect(within(live).getByText("Bayern Munich")).toHaveClass("text-muted");
    expect(within(live).getByText("Arsenal")).not.toHaveClass("text-muted");
  });

  it("filters to the selected leagues and restores the full list", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn((url) => {
      const body = String(url).includes("/leagues")
        ? [{ code: "PD", name: "La Liga" }, { code: "CL", name: "Champions League" }]
        : [
            { id: 1, league_code: "CL", home: "Arsenal", away: "Bayern Munich", home_score: 1, away_score: 0, status: "IN_PLAY", kickoff: "2026-10-30T19:00:00Z" },
            { id: 2, league_code: "PD", home: "Real Madrid", away: "Getafe", home_score: null, away_score: null, status: "SCHEDULED", kickoff: "2026-10-30T20:00:00Z" },
          ];
      return Promise.resolve({ json: async () => body });
    });

    render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );

    expect(await screen.findByText("Arsenal")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "La Liga" }));
    expect(screen.queryByText("Arsenal")).not.toBeInTheDocument();
    expect(screen.getByText("Real Madrid")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "La Liga" }));
    expect(screen.getByText("Arsenal")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Champions League" }));
    expect(screen.queryByText("Real Madrid")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Real Madrid")).toBeInTheDocument();
    expect(screen.getByText("Arsenal")).toBeInTheDocument();
  });

  it("shows an empty selection and an upstream error without inventing fixtures", async () => {
    const user = userEvent.setup();
    global.fetch = vi.fn((url) => {
      const body = String(url).includes("/leagues")
        ? [{ code: "PD", name: "La Liga" }]
        : [{ id: 1, league_code: "CL", home: "Arsenal", away: "Bayern Munich", home_score: 1, away_score: 0, status: "FINISHED", kickoff: "2026-10-30T19:00:00Z" }];
      return Promise.resolve({ json: async () => body });
    });

    const { unmount } = render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );
    expect(await screen.findByText("Arsenal")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "La Liga" }));
    expect(screen.getByText("No matches for the selected leagues today.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    unmount();

    global.fetch = vi.fn((url) => {
      if (String(url).includes("/leagues")) return Promise.resolve({ json: async () => [] });
      return Promise.resolve({ json: async () => ({ error: "football-data.org rate limit hit, please try again shortly." }) });
    });
    const failed = render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("football-data.org rate limit hit, please try again shortly.");
    expect(screen.queryByText("Arsenal")).not.toBeInTheDocument();
    failed.unmount();

    global.fetch = vi.fn((url) => {
      if (String(url).includes("/leagues")) return Promise.resolve({ json: async () => [] });
      return Promise.reject(new Error("offline"));
    });
    render(
      <MemoryRouter>
        <TodayGames />
      </MemoryRouter>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend");
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import EloRatingsTable from "./EloRatingsTable";

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EloRatingsTable", () => {
  it("renders ranked Elo rows with deltas", async () => {
    global.fetch.mockResolvedValue({
      json: async () => ({
        league: "PD",
        window_days: 90,
        matches_used: 42,
        ratings: [
          { rank: 1, team: "Real Madrid", crest: null, rating: 1682.4, played: 12, delta: 182.4 },
          { rank: 2, team: "Barcelona", crest: null, rating: 1640.1, played: 12, delta: 140.1 },
        ],
      }),
    });

    render(
      <MemoryRouter>
        <EloRatingsTable league="PD" />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Real Madrid")).toBeInTheDocument();
    });

    expect(screen.getByText("1682.4")).toBeInTheDocument();
    expect(screen.getByText("+182.4")).toBeInTheDocument();
    expect(screen.getByText(/42 matches/i)).toBeInTheDocument();
  });

  it("shows the top of a long table and signs the rating change", async () => {
    const ratings = Array.from({ length: 10 }, (_, index) => ({
      rank: index + 1,
      team: `Club ${index + 1}`,
      crest: null,
      rating: 1600 - index,
      played: 3,
      delta: index === 0 ? -12.5 : index === 1 ? 0 : 4.2,
    }));
    global.fetch.mockResolvedValue({
      json: async () => ({ league: "PD", window_days: 90, matches_used: 80, ratings }),
    });

    render(
      <MemoryRouter>
        <EloRatingsTable league="PD" compact />
      </MemoryRouter>
    );

    expect(await screen.findByText("Club 1")).toBeInTheDocument();
    expect(screen.getByText("Club 8")).toBeInTheDocument();
    expect(screen.queryByText("Club 9")).not.toBeInTheDocument();
    expect(screen.queryByText("Club 10")).not.toBeInTheDocument();
    expect(screen.getByText(/Showing top 8 of 10/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Full Elo table" })).toHaveAttribute("href", "/elo?league=PD");
    expect(screen.getByText("-12.5")).toHaveClass("text-loss");
    expect(screen.getByText("0")).toHaveClass("text-faint");
    expect(screen.getAllByText("+4.2").length).toBeGreaterThan(0);
  });
});

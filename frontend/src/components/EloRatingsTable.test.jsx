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
});

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PredictionsPanel from "./PredictionsPanel";

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PredictionsPanel", () => {
  it("renders three-way probabilities and Elo ratings", async () => {
    global.fetch.mockResolvedValue({
      json: async () => [
        {
          home: "Real Madrid",
          away: "Girona",
          home_crest: null,
          away_crest: null,
          date: "2026-10-22",
          home_elo: 1620.4,
          away_elo: 1488.2,
          home_win_pct: 52.1,
          draw_pct: 24.0,
          away_win_pct: 23.9,
          predicted_result: "home",
          predicted_winner: "Real Madrid",
        },
      ],
    });

    render(<PredictionsPanel league="PD" />);

    await waitFor(() => {
      expect(screen.getByText("Real Madrid")).toBeInTheDocument();
    });

    expect(screen.getByText("Draw 24%")).toBeInTheDocument();
    expect(screen.getByText("52.1%")).toBeInTheDocument();
    expect(screen.getByText("23.9%")).toBeInTheDocument();
    expect(screen.getByText("Elo 1620.4")).toBeInTheDocument();
    expect(screen.getByText("Elo 1488.2")).toBeInTheDocument();
    expect(screen.getByText(/Real Madrid lean/i)).toBeInTheDocument();
  });
});

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

  it("names a draw and an away lean, and drops the previous league's tips", async () => {
    global.fetch.mockImplementation(async (url) => {
      const league = new URL(url, "http://localhost").searchParams.get("league");
      const row = league === "PL"
        ? { home: "Arsenal", away: "Everton", date: "2026-10-23", home_elo: 1700, away_elo: 1500, home_win_pct: 40, draw_pct: 28, away_win_pct: 32, predicted_result: "draw", predicted_winner: "Draw" }
        : { home: "Girona", away: "Sevilla", date: "2026-10-23", home_elo: 1490, away_elo: 1560, home_win_pct: 30, draw_pct: 25, away_win_pct: 45, predicted_result: "away", predicted_winner: "Sevilla" };
      return { json: async () => [row] };
    });

    const { rerender } = render(<PredictionsPanel league="PD" />);
    expect(await screen.findByText("Sevilla lean")).toBeInTheDocument();
    expect(screen.getByText("Draw 25%")).toBeInTheDocument();

    rerender(<PredictionsPanel league="PL" />);
    expect(await screen.findByText("Draw most likely")).toBeInTheDocument();
    expect(screen.queryByText("Sevilla lean")).not.toBeInTheDocument();
    expect(screen.getByText("Draw 28%")).toBeInTheDocument();
  });

  it("shows an empty list, an API error, and a network failure as distinct states", async () => {
    global.fetch.mockResolvedValue({ json: async () => [] });
    const empty = render(<PredictionsPanel league="PD" />);
    expect(await screen.findByText("No upcoming fixtures found.")).toBeInTheDocument();
    empty.unmount();

    global.fetch.mockResolvedValue({ json: async () => ({ error: "Unknown league code 'ZZ'" }) });
    const failed = render(<PredictionsPanel league="ZZ" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown league code 'ZZ'");
    expect(screen.queryByText("No upcoming fixtures found.")).not.toBeInTheDocument();
    failed.unmount();

    global.fetch.mockRejectedValue(new Error("offline"));
    render(<PredictionsPanel league="PL" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the predictions service.");
  });
});

import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MatchesTable from "./MatchesTable";

const sampleMatches = [
  {
    date: "2024-01-05",
    home: "Real Madrid",
    away: "Barcelona",
    score: "3 - 1",
    winner: "Real Madrid",
  },
  {
    date: "2024-01-06",
    home: "Sevilla",
    away: "Valencia",
    score: "0 - 2",
    winner: "Valencia",
  },
  {
    date: "2024-01-07",
    home: "Betis",
    away: "Getafe",
    score: "1 - 1",
    winner: "Draw",
  },
];

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MatchesTable", () => {
  it("requests matches from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    render(<MatchesTable />);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/matches")
    );
  });

  it("renders a row for each match with its date, teams and score", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleMatches });

    render(<MatchesTable />);

    await screen.findByText(sampleMatches[0].date);

    for (const match of sampleMatches) {
      const row = screen.getByText(match.date).closest("tr");
      const teamCells = within(row).getAllByText((_, el) =>
        el.matches("td.font-semibold")
      );
      expect(teamCells.map((cell) => cell.textContent)).toEqual([
        match.home,
        match.away,
      ]);
      expect(within(row).getByText(match.score)).toBeInTheDocument();
    }
  });

  it("styles a home win, an away win and a draw differently", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleMatches });

    render(<MatchesTable />);

    const homeWin = await screen.findByText("Real Madrid", {
      selector: "td.text-green-400",
    });
    const awayWin = screen.getByText("Valencia", {
      selector: "td.text-red-400",
    });
    const draw = screen.getByText("Draw", { selector: "td.text-yellow-300" });

    expect(homeWin).toBeInTheDocument();
    expect(awayWin).toBeInTheDocument();
    expect(draw).toBeInTheDocument();
  });

  it("renders no rows and logs an error when the fetch fails", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    fetch.mockRejectedValueOnce(new Error("network down"));

    render(<MatchesTable />);

    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    expect(screen.queryAllByRole("row")).toHaveLength(1); // header row only
  });
});

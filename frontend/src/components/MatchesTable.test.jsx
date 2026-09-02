import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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

function renderMatchesTable(props = {}) {
  // MatchesTable calls useNavigate() (match rows link to /match/:id), so it
  // needs a Router context even outside the real App.
  return render(
    <MemoryRouter>
      <MatchesTable league="PD" {...props} />
    </MemoryRouter>
  );
}

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MatchesTable", () => {
  it("requests matches from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    renderMatchesTable();

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/matches?league=PD")
    );
  });

  it("renders a row for each match with its date, teams and score", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleMatches });

    renderMatchesTable();

    await screen.findByText(sampleMatches[0].date);

    for (const match of sampleMatches) {
      const row = screen.getByText(match.date).closest("tr");
      // Team cells now include a TeamBadge avatar alongside the name, so
      // check containment rather than exact cell text.
      expect(row.textContent).toContain(match.home);
      expect(row.textContent).toContain(match.away);
      expect(within(row).getByText(match.score)).toBeInTheDocument();
    }
  });

  it("styles a home win, an away win and a draw differently", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleMatches });

    renderMatchesTable();

    const homeWin = await screen.findByText("Real Madrid", {
      selector: "td.text-emerald-400",
    });
    const awayWin = screen.getByText("Valencia", {
      selector: "td.text-rose-400",
    });
    const draw = screen.getByText("Draw", { selector: "td.text-amber-400" });

    expect(homeWin).toBeInTheDocument();
    expect(awayWin).toBeInTheDocument();
    expect(draw).toBeInTheDocument();
  });

  it("shows an error message instead of the table when the fetch fails", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    fetch.mockRejectedValueOnce(new Error("network down"));

    renderMatchesTable();

    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    // On error the table is replaced entirely by an error message, so no
    // rows (not even the header) render.
    expect(screen.queryAllByRole("row")).toHaveLength(0);
    expect(screen.getByText("Could not reach the backend")).toBeInTheDocument();
  });
});

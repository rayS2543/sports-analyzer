import { render, screen, waitFor } from "@testing-library/react";
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

    await screen.findByText(sampleMatches[0].score);

    for (const match of sampleMatches) {
      const row = screen.getByText(match.score).closest("tr");
      // Team cells include a TeamBadge alongside the name, so check
      // containment rather than exact cell text.
      expect(row.querySelector("time").getAttribute("datetime")).toBe(match.date);
      expect(row.textContent).toContain(match.home);
      expect(row.textContent).toContain(match.away);
    }
  });

  it("marks each row as a home win, an away win or a draw", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleMatches });

    renderMatchesTable();

    await screen.findByText(sampleMatches[0].score);

    const resultOf = (score) => screen.getByText(score).closest("tr").dataset.result;
    expect(resultOf("3 - 1")).toBe("home");
    expect(resultOf("0 - 2")).toBe("away");
    expect(resultOf("1 - 1")).toBe("draw");

    // The winning side is emphasised; the other side is muted.
    expect(screen.getByText("Real Madrid")).toHaveClass("font-semibold");
    expect(screen.getByText("Barcelona")).toHaveClass("text-muted");
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

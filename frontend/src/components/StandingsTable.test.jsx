import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StandingsTable from "./StandingsTable";

const sampleStandings = [
  {
    position: 1,
    team_name: "Real Madrid",
    playedGames: 20,
    won: 15,
    draw: 3,
    lost: 2,
    goalDifference: 30,
    points: 48,
  },
];

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StandingsTable", () => {
  it("requests standings from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    render(<StandingsTable />);

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/standings");
  });

  it("renders a row per team with position and points", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleStandings });

    render(<StandingsTable />);

    await screen.findByText("Real Madrid");
    expect(screen.getByText("48")).toBeInTheDocument();
  });
});

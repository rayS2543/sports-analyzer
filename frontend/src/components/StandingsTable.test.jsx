import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StandingsTable from "./StandingsTable";

const sampleStandings = [
  {
    position: 1,
    team_name: "Real Madrid",
    tla: "RMA",
    crest: "https://crests.example/rma.png",
    playedGames: 20,
    won: 15,
    draw: 3,
    lost: 2,
    points: 48,
    goalDifference: 30,
  },
];

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StandingsTable", () => {
  it("renders a row per team with position and points", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleStandings });

    render(<StandingsTable />);

    await screen.findByText("Real Madrid");
    expect(screen.getByText("48")).toBeInTheDocument();
  });

  it("shows an error message when the backend returns one", async () => {
    fetch.mockResolvedValueOnce({
      json: async () => ({ error: "Unexpected API response" }),
    });

    render(<StandingsTable />);

    expect(await screen.findByText("Unexpected API response")).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StandingsTable from "./StandingsTable";

const row = (position, team_name, goalDifference, points) => ({
  position,
  team_name,
  tla: team_name.slice(0, 3).toUpperCase(),
  crest: null,
  playedGames: 10,
  won: 6,
  draw: 2,
  lost: 2,
  goalsFor: 18,
  goalsAgainst: 9,
  goalDifference,
  points,
});

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("StandingsTable", () => {
  it("links each club and signs only a positive goal difference", async () => {
    global.fetch.mockResolvedValue({
      json: async () => [
        row(1, "Real Madrid CF", 12, 30),
        row(2, "Getafe CF", -4, 20),
        row(3, "Girona FC", 0, 15),
      ],
    });

    render(
      <MemoryRouter>
        <StandingsTable league="PD" />
      </MemoryRouter>
    );

    expect(await screen.findByRole("link", { name: /Real Madrid CF/ })).toHaveAttribute("href", "/team/PD/Real%20Madrid%20CF");
    expect(screen.getByRole("link", { name: /Getafe CF/ })).toHaveAttribute("href", "/team/PD/Getafe%20CF");

    const leader = screen.getByRole("row", { name: /Real Madrid CF/ });
    const mid = screen.getByRole("row", { name: /Getafe CF/ });
    const level = screen.getByRole("row", { name: /Girona FC/ });
    expect(leader).toHaveTextContent("+12");
    expect(mid).toHaveTextContent("-4");
    expect(mid).not.toHaveTextContent("+");
    expect(level).toHaveTextContent("0");
    expect(level).not.toHaveTextContent("+0");
    expect(global.fetch).toHaveBeenCalledWith("http://127.0.0.1:5001/standings?league=PD");
  });

  it("reports an unexpected payload and a network failure instead of an empty table", async () => {
    global.fetch.mockResolvedValue({ json: async () => ({ error: "Unknown league code 'ZZ'" }) });
    const { unmount } = render(
      <MemoryRouter>
        <StandingsTable league="ZZ" />
      </MemoryRouter>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Unknown league code 'ZZ'");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    unmount();

    global.fetch.mockResolvedValue({ json: async () => ({ standings: [] }) });
    const unexpected = render(
      <MemoryRouter>
        <StandingsTable league="PD" />
      </MemoryRouter>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Unexpected response from server");
    unexpected.unmount();

    global.fetch.mockRejectedValue(new Error("offline"));
    render(
      <MemoryRouter>
        <StandingsTable league="PL" />
      </MemoryRouter>
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend");
  });
});

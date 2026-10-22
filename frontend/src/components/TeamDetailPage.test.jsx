import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./FollowButton", () => ({
  default: () => <button type="button">Follow</button>,
}));

vi.mock("./NewsFeed", () => ({
  default: () => <div>News feed</div>,
}));

let TeamDetailPage;

const sampleTeam = {
  id: 86,
  name: "Real Madrid CF",
  shortName: "Real Madrid",
  tla: "RMA",
  crest: "rma.png",
  founded: 1902,
  venue: "Santiago Bernabéu",
  coach: { name: "Carlo Ancelotti", nationality: "Italy" },
  league: "PD",
  standing: {
    position: 1,
    playedGames: 18,
    won: 14,
    draw: 3,
    lost: 1,
    points: 45,
    goalsFor: 40,
    goalsAgainst: 12,
    goalDifference: 28,
  },
  form: "WWDLW",
  form_points: 10,
  matches_considered: 5,
  squad: [
    { id: 1, name: "Courtois", position: "Goalkeeper", nationality: "Belgium", shirtNumber: 1 },
    { id: 2, name: "Vinicius Junior", position: "Offence", nationality: "Brazil", shirtNumber: 7 },
  ],
  recent_matches: [
    {
      home: "Real Madrid CF",
      away: "Barcelona",
      score: "2 - 1",
      winner: "Real Madrid CF",
      date: "2024-01-10",
    },
  ],
  upcoming_matches: [
    {
      home: "Sevilla",
      away: "Real Madrid CF",
      date: "2024-01-20",
      kickoff: "2024-01-20T18:00:00Z",
    },
  ],
};

beforeEach(async () => {
  vi.resetModules();
  global.fetch = vi.fn((url) => {
    if (String(url).includes("/teams/detail")) {
      return Promise.resolve({ json: async () => sampleTeam });
    }
    if (String(url).includes("/matches/detail")) {
      return Promise.resolve({
        json: async () => ({
          available: true,
          home: {
            team_name: "Real Madrid CF",
            formation: "4-3-3",
            starters: [{ id: 1, name: "Courtois", number: 1, position: "GK" }],
            bench: [],
          },
          away: { team_name: "Barcelona", formation: "4-4-2", starters: [], bench: [] },
        }),
      });
    }
    return Promise.resolve({ json: async () => ({}) });
  });
  TeamDetailPage = (await import("./TeamDetailPage")).default;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/team/PD/Real%20Madrid%20CF"]}>
      <Routes>
        <Route path="/team/:league/:name" element={<TeamDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("TeamDetailPage", () => {
  it("loads club detail and shows squad, form, and fixtures", async () => {
    renderPage();

    await waitFor(() => {
      expect(fetch.mock.calls.some(([url]) => String(url).includes("/teams/detail?"))).toBe(true);
    });

    expect(await screen.findByRole("heading", { name: "Real Madrid CF" })).toBeInTheDocument();
    expect(screen.getByText("Santiago Bernabéu · Coach Carlo Ancelotti · Est. 1902")).toBeInTheDocument();
    expect(screen.getAllByText("Courtois").length).toBeGreaterThan(0);
    expect(screen.getByText("Vinicius Junior")).toBeInTheDocument();
    expect(screen.getByText("2 - 1")).toBeInTheDocument();
    expect(screen.getByText("Sevilla")).toBeInTheDocument();
    expect(screen.getByText(/Last XI vs/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url]) => /name=Real(\+|%20)Madrid(\+|%20)CF/.test(String(url)))).toBe(true);
  });

  it("shows an error when the backend returns one", async () => {
    fetch.mockImplementation(() => Promise.resolve({ json: async () => ({ error: "Team not found" }) }));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Team not found");
  });
});

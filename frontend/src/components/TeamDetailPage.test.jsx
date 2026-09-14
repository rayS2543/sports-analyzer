import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TeamDetailPage from "./TeamDetailPage";

const formResponse = {
  team: "Real Madrid CF",
  league: "PD",
  matches_considered: 2,
  points: 4,
  form: "WD",
  matches: [
    { date: "2024-01-01", home: "Real Madrid CF", away: "Barcelona", score: "2 - 2", winner: "Draw" },
    { date: "2024-01-08", home: "Sevilla", away: "Real Madrid CF", score: "0 - 1", winner: "Real Madrid CF" },
  ],
};

const teamsResponse = [{ name: "Real Madrid CF", shortName: "Real Madrid", tla: "RMA", crest: "rma.png" }];

const standingsResponse = [
  {
    position: 1,
    team_name: "Real Madrid CF",
    tla: "RMA",
    crest: "rma.png",
    playedGames: 20,
    won: 15,
    draw: 3,
    lost: 2,
    points: 48,
    goalsFor: 40,
    goalsAgainst: 15,
    goalDifference: 25,
  },
  {
    position: 2,
    team_name: "Barcelona",
    tla: "BAR",
    crest: "bar.png",
    playedGames: 20,
    won: 13,
    draw: 4,
    lost: 3,
    points: 43,
    goalsFor: 35,
    goalsAgainst: 18,
    goalDifference: 17,
  },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/team/PD/Real%20Madrid%20CF"]}>
      <Routes>
        <Route path="/team/:league/:name" element={<TeamDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url.includes("/analytics/form/")) {
      return Promise.resolve({ json: async () => formResponse });
    }
    if (url.includes("/teams")) {
      return Promise.resolve({ json: async () => teamsResponse });
    }
    if (url.includes("/standings")) {
      return Promise.resolve({ json: async () => standingsResponse });
    }
    if (url.includes("/predictions")) {
      return Promise.resolve({ json: async () => [] });
    }
    if (url.includes("/news")) {
      return Promise.resolve({ json: async () => ({ items: [] }) });
    }
    return Promise.resolve({ json: async () => ({}) });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamDetailPage", () => {
  it("renders the team name and season stats from standings", async () => {
    renderPage();

    await screen.findByText("Real Madrid CF");
    expect(screen.getByText("League Position")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.tagName.toLowerCase() === "p" && element.textContent === "1/2")
    ).toBeInTheDocument();
    expect(screen.getAllByText("48").length).toBeGreaterThan(0);
  });

  it("renders recent form and match history", async () => {
    renderPage();

    await screen.findByText("Recent Results");
    expect(screen.getByText("4 points from last 2 matches")).toBeInTheDocument();
    expect(screen.getByText("Sevilla 0 - 1 Real Madrid CF")).toBeInTheDocument();
  });

  it("shows a form error message when the backend reports one", async () => {
    global.fetch = vi.fn((url) => {
      if (url.includes("/analytics/form/")) {
        return Promise.resolve({ json: async () => ({ error: "No cached match history" }) });
      }
      if (url.includes("/teams")) {
        return Promise.resolve({ json: async () => teamsResponse });
      }
      if (url.includes("/standings")) {
        return Promise.resolve({ json: async () => standingsResponse });
      }
      if (url.includes("/predictions")) {
        return Promise.resolve({ json: async () => [] });
      }
      if (url.includes("/news")) {
        return Promise.resolve({ json: async () => ({ items: [] }) });
      }
      return Promise.resolve({ json: async () => ({}) });
    });

    renderPage();

    await screen.findByText("No cached match history");
  });
});

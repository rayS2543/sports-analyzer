import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "../apiBase";
import PlayerDetailPage from "./PlayerDetailPage";

vi.mock("./NewsList", () => ({
  default: ({ query }) => <div>Headlines for {query}</div>,
}));

const pedri = {
  id: 99,
  name: "Pedri",
  photo: "https://media.example/pedri.jpg",
  nationality: "Spain",
  position: "Midfielder",
  current_team: "FC Barcelona",
  season: "2026",
  appearances: 20,
  goals: 4,
  assists: 6,
  yellow_cards: 2,
  red_cards: 1,
  rating: "7.40",
};

function renderPlayer() {
  return render(
    <MemoryRouter initialEntries={["/player/99"]}>
      <Routes>
        <Route path="/player/:id" element={<PlayerDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PlayerDetailPage", () => {
  it("shows the season numbers and only the fields that exist", async () => {
    fetch.mockResolvedValueOnce({ json: async () => pedri });
    renderPlayer();

    expect(await screen.findByRole("heading", { name: "Pedri" })).toBeInTheDocument();
    expect(screen.getByText("Midfielder, FC Barcelona, Spain")).toBeInTheDocument();
    expect(screen.getByText("2026 season")).toBeInTheDocument();
    expect(screen.getByText("Appearances").nextElementSibling).toHaveTextContent("20");
    expect(screen.getByText("Goals").nextElementSibling).toHaveTextContent("4");
    const reds = screen.getByText("Red cards").nextElementSibling;
    expect(reds).toHaveTextContent("1");
    expect(reds).toHaveClass("text-loss");
    expect(screen.getByText("Headlines for Pedri")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/players/99`);
  });

  it("does not treat a missing stat as zero and does not mark a clean record as a red", async () => {
    fetch.mockResolvedValueOnce({ json: async () => ({ ...pedri, photo: null, nationality: null, assists: null, red_cards: 0 }) });
    renderPlayer();

    expect(await screen.findByText("Midfielder, FC Barcelona")).toBeInTheDocument();
    expect(screen.getByText("Assists").nextElementSibling).toHaveTextContent("-");
    expect(screen.getByText("Red cards").nextElementSibling).toHaveClass("text-fg");
    expect(screen.getByTitle("Pedri: crest unavailable")).toBeInTheDocument();
  });

  it("shows an API error instead of an empty player, and a broken photo falls back to the badge", async () => {
    fetch.mockResolvedValueOnce({ json: async () => ({ error: "Player not found for that season" }) });
    const { unmount } = renderPlayer();
    expect(await screen.findByText("Player not found for that season")).toBeInTheDocument();
    expect(screen.queryByText("Appearances")).not.toBeInTheDocument();
    expect(screen.queryByText(/Headlines/)).not.toBeInTheDocument();
    unmount();

    fetch.mockResolvedValueOnce({ json: async () => pedri });
    renderPlayer();
    fireEvent.error(await screen.findByRole("img", { name: "Pedri" }));
    expect(screen.getByTitle("Pedri: crest unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Pedri" })).not.toBeInTheDocument();
  });

  it("says when the backend cannot be reached", async () => {
    fetch.mockRejectedValueOnce(new Error("offline"));
    renderPlayer();
    expect(await screen.findByText("Could not reach the backend")).toBeInTheDocument();
    expect(screen.queryByText("Appearances")).not.toBeInTheDocument();
  });
});

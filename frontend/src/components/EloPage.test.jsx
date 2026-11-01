import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "../apiBase";
import EloPage from "./EloPage";

function Location() {
  const { pathname, search } = useLocation();
  return <div data-testid="loc">{pathname}{search}</div>;
}

const leagues = [
  { code: "PD", name: "La Liga", country: "Spain" },
  { code: "PL", name: "Premier League", country: "England" },
  { code: "BL1", name: "Bundesliga", country: "Germany" },
];

function json(body) {
  return Promise.resolve({ json: async () => body });
}

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes("/leagues")) return json(leagues);
    if (u.includes("/ratings")) return json({ ratings: [] });
    if (u.includes("/predictions")) return json([]);
    return json([]);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/elo" element={<><EloPage /><Location /></>} />
      </Routes>
    </MemoryRouter>
  );
}

describe("EloPage", () => {
  it("opens the league in the link and loads that league's ratings and tips", async () => {
    renderAt("/elo?league=PL");

    expect(await screen.findByText(/Live club strength for Premier League/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Premier League" })).toHaveAttribute("aria-current", "true");
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/ratings?league=PL`);
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/predictions?league=PL`);
    expect(fetch).not.toHaveBeenCalledWith(`${API_BASE}/ratings?league=PD`);
  });

  it("writes the chosen league into the link and drops it for La Liga", async () => {
    const user = userEvent.setup();
    renderAt("/elo?league=PL");
    await screen.findByRole("button", { name: "Bundesliga" });

    await user.click(screen.getByRole("button", { name: "Bundesliga" }));
    expect(await screen.findByText(/Live club strength for Bundesliga/)).toBeInTheDocument();
    expect(screen.getByTestId("loc")).toHaveTextContent("/elo?league=BL1");
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/ratings?league=BL1`);
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/predictions?league=BL1`);

    await user.click(screen.getByRole("button", { name: "La Liga" }));
    expect(await screen.findByText(/Live club strength for La Liga/)).toBeInTheDocument();
    expect(screen.getByTestId("loc")).toHaveTextContent("/elo");
    expect(screen.getByTestId("loc").textContent).not.toContain("league=");
    expect(screen.getByRole("button", { name: "La Liga" })).toHaveAttribute("aria-current", "true");
    expect(fetch).toHaveBeenCalledWith(`${API_BASE}/ratings?league=PD`);
  });
});

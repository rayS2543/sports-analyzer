import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
let TeamsList;

const sampleTeams = [
  { name: "Real Madrid CF", shortName: "Real Madrid", tla: "RMA", crest: "rma.png" },
];

beforeEach(async () => {
  vi.resetModules();
  global.fetch = vi.fn();
  TeamsList = (await import("./TeamsList")).default;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamsList", () => {
  it("requests teams for the given league from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    render(<TeamsList league="PD" />, { wrapper: MemoryRouter });

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/teams?league=PD");
  });

  it("renders a card per team", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleTeams });

    render(<TeamsList league="PD" />, { wrapper: MemoryRouter });

    await screen.findByText("Real Madrid");
    expect(screen.getByText("RMA")).toBeInTheDocument();
  });

  it("shows an error message on an unexpected response", async () => {
    fetch.mockResolvedValueOnce({ json: async () => ({ error: "Unknown league code 'ZZ'" }) });

    render(<TeamsList league="ZZ" />, { wrapper: MemoryRouter });

    await screen.findByText("Unknown league code 'ZZ'");
  });

  it("re-fetches when the league prop changes", async () => {
    fetch.mockResolvedValue({ json: async () => [] });

    const { rerender } = render(<TeamsList league="PD" />, { wrapper: MemoryRouter });
    rerender(<TeamsList league="PL" />);

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/teams?league=PL");
  });
});

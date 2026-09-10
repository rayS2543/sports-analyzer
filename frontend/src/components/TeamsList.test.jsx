import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TeamsList from "./TeamsList";

const sampleTeams = [
  { name: "Real Madrid CF", shortName: "Real Madrid", tla: "RMA", crest: "rma.png" },
];

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamsList", () => {
  it("requests teams for the given league from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    render(<TeamsList league="PD" />);

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/teams?league=PD");
  });

  it("renders a card per team", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleTeams });

    render(<TeamsList league="PD" />);

    await screen.findByText("Real Madrid");
    expect(screen.getByText("RMA")).toBeInTheDocument();
  });

  it("shows an error message on an unexpected response", async () => {
    fetch.mockResolvedValueOnce({ json: async () => ({ error: "Unknown league code 'ZZ'" }) });

    render(<TeamsList league="ZZ" />);

    await screen.findByText("Unknown league code 'ZZ'");
  });

  it("re-fetches when the league prop changes", async () => {
    fetch.mockResolvedValue({ json: async () => [] });

    const { rerender } = render(<TeamsList league="PD" />);
    rerender(<TeamsList league="PL" />);

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/teams?league=PL");
  });
});

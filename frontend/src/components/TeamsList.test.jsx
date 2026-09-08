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
  it("requests teams from the backend on mount", async () => {
    fetch.mockResolvedValueOnce({ json: async () => [] });

    render(<TeamsList />);

    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:5000/teams");
  });

  it("renders a card per team", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleTeams });

    render(<TeamsList />);

    await screen.findByText("Real Madrid");
    expect(screen.getByText("RMA")).toBeInTheDocument();
  });
});

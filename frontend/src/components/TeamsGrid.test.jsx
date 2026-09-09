import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TeamsGrid from "./TeamsGrid";

const sampleTeams = [
  { name: "Real Madrid CF", shortName: "Real Madrid", tla: "RMA", crest: "https://crests.example/rma.png" },
];

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamsGrid", () => {
  it("renders a card per team", async () => {
    fetch.mockResolvedValueOnce({ json: async () => sampleTeams });

    render(<TeamsGrid />);

    expect(await screen.findByText("Real Madrid")).toBeInTheDocument();
    expect(screen.getByText("RMA")).toBeInTheDocument();
  });
});

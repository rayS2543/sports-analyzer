import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({ json: async () => [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("renders the Sports Analyzer heading", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    expect(
      screen.getByRole("heading", { name: /sports analyzer/i })
    ).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({ json: async () => [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("renders the match tracker heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /la liga match tracker/i })
    ).toBeInTheDocument();
  });
});

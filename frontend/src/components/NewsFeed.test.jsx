import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { API_BASE } from "../apiBase";
import NewsFeed from "./NewsFeed";

afterEach(() => {
  vi.restoreAllMocks();
});

it("does not ask for news when nobody is followed", async () => {
  const fetchMock = vi.spyOn(global, "fetch");
  render(<NewsFeed teams={[]} />);
  expect(await screen.findByText("No recent news found.")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
});

it("shows an error when the feed has no articles", async () => {
  vi.spyOn(global, "fetch").mockResolvedValue({
    json: async () => ({ items: [], error: "teams parameter is required" }),
  });
  render(<NewsFeed teams={["Real Madrid CF"]} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("teams parameter is required");
});

it("lists each club's headlines and names the club when several are followed", async () => {
  const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue({
    json: async () => ({
      error: "one club failed",
      items: [
        { title: "Madrid story", link: "https://example.com/m", team_name: "Real Madrid CF" },
        { title: "Barca story", link: "https://example.com/b", team_name: "FC Barcelona" },
      ],
    }),
  });

  render(<NewsFeed teams={["Real Madrid CF", "FC Barcelona"]} />);

  expect(await screen.findByText("Madrid story")).toBeInTheDocument();
  expect(screen.getByText("Barca story")).toBeInTheDocument();
  expect(screen.getByText("Real Madrid CF")).toBeInTheDocument();
  expect(screen.getByText("FC Barcelona")).toBeInTheDocument();
  expect(screen.queryByText("one club failed")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    `${API_BASE}/news/teams?teams=${encodeURIComponent("Real Madrid CF,FC Barcelona")}`
  );
});

it("says the backend was unreachable when the request fails", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(global, "fetch").mockRejectedValue(new Error("offline"));
  render(<NewsFeed teams={["Sevilla FC"]} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the backend");
});

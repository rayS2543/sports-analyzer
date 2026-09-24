import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import TeamBadge from "./TeamBadge";
import { getTeams, cachedCrest } from "../teamAssets";

it("reuses a loaded crest on the next page and tries the supplied official fallback", () => {
  const { rerender } = render(<TeamBadge name="Crest test club" crest="https://example.com/official.svg" />);
  fireEvent.load(screen.getByTitle("Crest test club"));
  rerender(<TeamBadge name="Crest test club" />);
  expect(screen.getByTitle("Crest test club")).toHaveAttribute("src", "https://example.com/official.svg");
  rerender(<TeamBadge name="Crest test club" crest="https://example.com/official.png" />);
  fireEvent.error(screen.getByTitle("Crest test club"));
  expect(screen.getByTitle("Crest test club")).toHaveAttribute("src", "https://example.com/official.png");
});

it("shares one club lookup and remembers both official and short names", async () => {
  const fetchMock = vi.spyOn(global, "fetch").mockResolvedValue({ json: async () => [{ name: "Cache FC", shortName: "Cache", crest: "cache.svg" }] });
  await Promise.all([getTeams("badge-test"), getTeams("badge-test")]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(cachedCrest("Cache FC")).toBe("cache.svg");
  expect(cachedCrest("Cache")).toBe("cache.svg");
  fetchMock.mockRestore();
});

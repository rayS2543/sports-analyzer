import { afterEach, expect, it, vi } from "vitest";
import { cachedCrest, getTeams, rememberCrest } from "./teamAssets";

afterEach(() => {
  vi.restoreAllMocks();
});

it("shares one failed club lookup, then tries the provider again", async () => {
  let calls = 0;
  vi.spyOn(global, "fetch").mockImplementation(() => {
    calls += 1;
    if (calls === 1) return Promise.reject(new Error("offline"));
    return Promise.resolve({
      json: async () => [{ name: "Retry FC", shortName: "Retry", crest: "retry.svg" }],
    });
  });

  await expect(Promise.all([getTeams("retry-league"), getTeams("retry-league")])).rejects.toThrow("offline");
  expect(calls).toBe(1);

  await expect(getTeams("retry-league")).resolves.toEqual([
    { name: "Retry FC", shortName: "Retry", crest: "retry.svg" },
  ]);
  expect(calls).toBe(2);
  expect(cachedCrest("Retry FC")).toBe("retry.svg");
  expect(cachedCrest("Retry")).toBe("retry.svg");
});

it("does not keep a non-list club payload", async () => {
  const fetchMock = vi.spyOn(global, "fetch")
    .mockResolvedValueOnce({ json: async () => ({ error: "rate limit" }) })
    .mockResolvedValueOnce({ json: async () => [] });

  await expect(getTeams("bad-league")).rejects.toThrow("rate limit");
  await expect(getTeams("bad-league")).resolves.toEqual([]);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("stores a crest only when both the club and the url are new", () => {
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  rememberCrest("", "https://example.com/blank.svg");
  rememberCrest("Blank crest", "");
  expect(cachedCrest("Blank crest")).toBeUndefined();
  expect(setItem).not.toHaveBeenCalled();

  rememberCrest("Kept crest", "https://example.com/kept.svg");
  expect(cachedCrest("Kept crest")).toBe("https://example.com/kept.svg");
  setItem.mockClear();
  rememberCrest("Kept crest", "https://example.com/kept.svg");
  expect(setItem).not.toHaveBeenCalled();
});

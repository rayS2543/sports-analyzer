import { expect, it } from "vitest";
import { formatDay } from "./ui";

it("formats the calendar date written in the string", () => {
  // 02:00 at UTC+5 is the previous evening in UTC. The label stays 6 Jan.
  const iso = "2026-01-06T02:00:00+05:00";
  const calendar = new Date(2026, 0, 6);
  const options = { weekday: "short", day: "numeric", month: "short" };

  expect(formatDay(iso)).toBe(calendar.toLocaleDateString(undefined, options));
  expect(formatDay("2026-09-20")).toBe(
    new Date(2026, 8, 20).toLocaleDateString(undefined, options)
  );
  expect(formatDay(iso, { weekday: false })).toBe(
    calendar.toLocaleDateString(undefined, { day: "numeric", month: "short" })
  );
});

it("returns a value that is not a calendar date unchanged", () => {
  expect(formatDay("not-a-date")).toBe("not-a-date");
  expect(formatDay("2026-01")).toBe("2026-01");
});

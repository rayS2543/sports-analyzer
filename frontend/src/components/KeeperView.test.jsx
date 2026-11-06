import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it } from "vitest";
import KeeperView, { keeperSummary } from "./KeeperView";

const gk = (id, name, starter = true) => ({ id, name, position: "GK", starter });
const home = { id: 1, team_name: "Home", starters: [gk(100, "Home GK")], bench: [gk(101, "Sub GK", false)] };
const away = { id: 2, team_name: "Away", starters: [gk(200, "Away GK")], bench: [] };
const shot = (id, eventType, keeperId, extra = {}) => ({ id, teamId: 2, playerId: id, playerName: `S${id}`, x: 95, y: 34, eventType, isOnTarget: true, keeperId, expectedGoalsOnTarget: 0.5, goalCrossedY: 33, goalCrossedZ: 1, ...extra });
const shots = [shot(1, "Goal", 100), shot(2, "AttemptSaved", 100), shot(3, "AttemptSaved", 101), shot(4, "Goal", 200, { teamId: 1 })];

it("summarises saves, conceded and goals prevented", () => {
  expect(keeperSummary(shots.slice(0, 2))).toEqual({ faced: 2, saves: 1, conceded: 1, xgot: 1, prevented: 0 });
});

it("treats a missing xGOT as zero, so goals prevented can be negative", () => {
  expect(keeperSummary([{ eventType: "Goal" }, { eventType: "AttemptSaved", expectedGoalsOnTarget: 0.25 }])).toEqual({
    faced: 2, saves: 1, conceded: 1, xgot: 0.25, prevented: -0.75,
  });
});

it("shows only the picked keeper's shots, and subs who faced shots", () => {
  render(<KeeperView home={home} away={away} shots={shots} />);
  expect(screen.getByLabelText("Goalkeeper")).toHaveTextContent("Sub GK");
  expect(screen.getAllByRole("button", { name: /^S\d/ })).toHaveLength(2);
  fireEvent.change(screen.getByLabelText("Goalkeeper"), { target: { value: "101" } });
  expect(screen.getAllByRole("button", { name: /^S\d/ })).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("Keeper team"), { target: { value: "away" } });
  expect(screen.getAllByRole("button", { name: /^S4/ })).toHaveLength(1);
});

it("rounds the save percentage, signs goals prevented, and leaves out a substitute who faced nothing", () => {
  const side = { id: 1, team_name: "Home", starters: [gk(100, "Home GK")], bench: [gk(101, "Unused", false)] };
  const faced = [
    shot(1, "Goal", 100, { expectedGoalsOnTarget: 0.4 }),
    shot(2, "AttemptSaved", 100, { expectedGoalsOnTarget: 0.9 }),
    shot(3, "AttemptSaved", 100, { expectedGoalsOnTarget: 0.1 }),
  ];
  render(<KeeperView home={side} away={away} shots={faced} />);
  expect(screen.getByLabelText("Goalkeeper")).not.toHaveTextContent("Unused");
  expect(screen.getByText("67%")).toBeInTheDocument();
  expect(screen.getByText("+0.40")).toBeInTheDocument();
  render(<KeeperView home={{ ...side, starters: [], bench: [] }} away={away} shots={[]} />);
  expect(screen.getByText("No goalkeeper data for this match yet.")).toBeInTheDocument();
});

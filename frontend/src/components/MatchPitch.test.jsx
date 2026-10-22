import { act, render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ShotMap, { FormationPitch, shotEnd, shotOutcome } from "./MatchPitch";

const home = { id: 1, team_name: "Home" };
const away = { id: 2, team_name: "Away" };
const shots = [
  { id: 1, playerId: 10, playerName: "Home striker", teamId: 1, x: 90, y: 34, min: 12, expectedGoals: 0.3, eventType: "Goal", isOnTarget: true, goalCrossedY: 32, goalCrossedZ: 1, period: "FirstHalf" },
  { id: 2, playerId: 20, playerName: "Away striker", teamId: 2, x: 90, y: 34, min: 60, expectedGoals: 0, eventType: "AttemptSaved", isBlocked: true, blockedX: 95, blockedY: 30, period: "SecondHalf" },
];

it("filters shots, clears hidden selections, and mirrors away coordinates", () => {
  render(<ShotMap shots={shots} home={home} away={away} />);
  const awayShot = screen.getByRole("button", { name: /Away striker/ });
  expect(parseFloat(awayShot.style.left)).toBeLessThan(50);
  fireEvent.click(awayShot);
  expect(screen.getByRole("tooltip")).toHaveTextContent("0.00");
  fireEvent.change(screen.getByLabelText("Period"), { target: { value: "FirstHalf" } });
  expect(screen.queryByRole("button", { name: /Away striker/ })).not.toBeInTheDocument();
  expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: "2" } });
  expect(screen.getByText("No shots match these filters.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Period"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("Player"), { target: { value: "20" } });
  expect(screen.getByRole("button", { name: /Away striker/ })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: "1" } });
  expect(screen.getByLabelText("Player")).toHaveValue("all");
  expect(screen.getByRole("button", { name: /Home striker/ })).toBeInTheDocument();
});

it("distinguishes unavailable shot data from an empty match", () => {
  const { rerender } = render(<ShotMap shots={null} home={home} away={away} />);
  expect(screen.getByText(/not available/)).toBeInTheDocument();
  rerender(<ShotMap shots={[]} home={home} away={away} />);
  expect(screen.getByText(/No shots recorded/)).toBeInTheDocument();
  expect(shotOutcome(shots[1])).toBe("Blocked");
});

it("shows details after a hover dwell and draws the shot path on click", () => {
  vi.useFakeTimers();
  const { container } = render(<ShotMap shots={shots} home={home} away={away} />);
  const homeShot = screen.getByRole("button", { name: /Home striker/ });
  fireEvent.mouseEnter(homeShot);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(400));
  expect(screen.getByRole("tooltip")).toHaveTextContent("Home striker");
  fireEvent.mouseLeave(homeShot);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  vi.useRealTimers();

  fireEvent.click(homeShot);
  const line = screen.getByTestId("shot-line");
  expect([line.getAttribute("x2"), line.getAttribute("y2")]).toEqual(["105", "32"]);
  expect(container.querySelector('[data-shot="1"]').getAttribute("cx")).toBe("32");
  // Blocked away shot ends at the block, mirrored toward the left goal.
  fireEvent.click(screen.getByRole("button", { name: /Away striker/ }));
  const awayLine = screen.getByTestId("shot-line");
  expect([awayLine.getAttribute("x2"), awayLine.getAttribute("y2")]).toEqual(["10", "38"]);
  expect(container.querySelector('[data-shot="2"]')).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Away striker/ }));
  expect(screen.queryByTestId("shot-line")).not.toBeInTheDocument();
});

it("toggle shows every shot path without needing a click", () => {
  render(<ShotMap shots={shots} home={home} away={away} />);
  expect(screen.queryAllByTestId("shot-line")).toHaveLength(0);
  fireEvent.click(screen.getByLabelText("Show all shot paths"));
  expect(screen.getAllByTestId("shot-line")).toHaveLength(2);
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: "1" } });
  expect(screen.getAllByTestId("shot-line")).toHaveLength(1);
});

it("declines to invent an end point the feed doesn't have", () => {
  expect(shotEnd({ isBlocked: true })).toBeNull();
  expect(shotEnd({ goalCrossedY: 90 })).toEqual({ x: 105, y: 68 });
  expect(shotEnd({})).toBeNull();
});

describe("formation", () => {
  it("selects a starter and declines to invent missing positions", () => {
    const onSelect = vi.fn();
    const starters = Array.from({ length: 11 }, (_, id) => ({ id, name: `Player ${id}`, number: id, pitch_position: { x: 0.5, y: 0.1 } }));
    const { rerender } = render(<FormationPitch team={{ ...home, starters }} side="home" onSelect={onSelect} />);
    const keeper = screen.getByRole("button", { name: /Player 0,/ });
    expect(keeper.style.top).toBe("90%");
    fireEvent.click(keeper);
    expect(onSelect).toHaveBeenCalledWith(0);
    rerender(<FormationPitch team={{ ...home, starters: [{ id: 1 }] }} side="home" onSelect={onSelect} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

it("selects a requested goal and clears filters that would hide it", () => {
  const { rerender } = render(<ShotMap shots={shots} home={home} away={away} />);
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: "2" } });
  rerender(<ShotMap shots={shots} home={home} away={away} focus={{ id: 1, n: 1 }} />);
  expect(screen.getByLabelText("Team")).toHaveValue("all");
  expect(screen.getByRole("button", { name: /Home striker/ })).toHaveAttribute("aria-pressed", "true");
});

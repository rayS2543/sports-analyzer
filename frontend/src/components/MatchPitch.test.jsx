import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ShotMap, { FormationPitch, shotOutcome } from "./MatchPitch";

const home = { id: 1, team_name: "Home" };
const away = { id: 2, team_name: "Away" };
const shots = [
  { id: 1, playerId: 10, playerName: "Home striker", teamId: 1, x: 90, y: 34, min: 12, expectedGoals: 0.3, eventType: "Goal", period: "FirstHalf" },
  { id: 2, playerId: 20, playerName: "Away striker", teamId: 2, x: 90, y: 34, min: 60, expectedGoals: 0, eventType: "AttemptSaved", isBlocked: true, period: "SecondHalf" },
];

it("filters shots, clears hidden selections, and mirrors away coordinates", () => {
  render(<ShotMap shots={shots} home={home} away={away} />);
  const awayShot = screen.getByRole("button", { name: /Away striker/ });
  expect(parseFloat(awayShot.style.left)).toBeLessThan(50);
  fireEvent.click(awayShot);
  expect(screen.getByText("0.00")).toBeInTheDocument();
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

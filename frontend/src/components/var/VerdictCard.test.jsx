import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OfficialRecord, VerdictCard } from "./VerdictCard";

const base = { uncertainty_m: 0.35, offside_line_x: 81.44, attacker_track_id: 10, frame_t: 1.2, attack_direction: "right" };

describe("VerdictCard", () => {
  it("shows an offside verdict with margin and uncertainty", () => {
    render(<VerdictCard result={{ ...base, verdict: "offside", margin_m: 1.4, reasons: ["Attacker beyond the second-last defender."] }} />);
    expect(screen.getByRole("article")).toHaveAttribute("data-verdict", "offside");
    expect(screen.getByText("Offside")).toHaveClass("text-loss");
    expect(screen.getByText("+1.40 m")).toBeInTheDocument();
    expect(screen.getByText(/± 0.35 m/)).toBeInTheDocument();
    expect(screen.getByText("Attacker beyond the second-last defender.")).toBeInTheDocument();
  });

  it("shows an onside verdict with a negative margin", () => {
    render(<VerdictCard result={{ ...base, verdict: "onside", margin_m: -1.0, reasons: [] }} />);
    expect(screen.getByText("Onside")).toHaveClass("text-win");
    expect(screen.getByText("−1.00 m")).toBeInTheDocument();
  });

  it("treats inconclusive as a first-class result, even with no measurement", () => {
    render(
      <VerdictCard
        result={{ verdict: "inconclusive", margin_m: null, uncertainty_m: null, offside_line_x: null, frame_t: 1.2, reasons: ["Fewer than two defenders visible."] }}
      />
    );
    expect(screen.getByText("Inconclusive")).toHaveClass("text-accent");
    expect(screen.queryByText(/ m$/)).not.toBeInTheDocument();
    expect(screen.getByText("Fewer than two defenders visible.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System assessment" })).toBeInTheDocument();
  });
});

describe("OfficialRecord", () => {
  it("lists ESPN events under its own heading, tolerating a missing clock", () => {
    render(<OfficialRecord state={{ events: [{ type: "offside", clock: null, team: "Getafe", text: "Mayoral is offside." }] }} />);
    expect(screen.getByRole("heading", { name: "Official record (ESPN)" })).toBeInTheDocument();
    expect(screen.getByText("Mayoral is offside.")).toBeInTheDocument();
    expect(screen.getByText("–")).toBeInTheDocument();
  });
});

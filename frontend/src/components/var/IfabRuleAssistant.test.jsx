import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import IfabRuleAssistant, { Law11Card, Law12Card } from "./IfabRuleAssistant";

describe("IfabRuleAssistant", () => {
  it("renders Law 11 offside evaluation with margin and tolerance", () => {
    const assessment = {
      verdict: "offside",
      margin_m: 0.18,
      uncertainty_m: 0.05,
    };

    render(<IfabRuleAssistant mode="law11" assessment={assessment} />);

    expect(screen.getByText("IFAB Law 11")).toBeInTheDocument();
    expect(screen.getByText("Offside Evaluation")).toBeInTheDocument();
    expect(screen.getByText("Infringement Detected")).toBeInTheDocument();
    expect(screen.getByText(/Attacker is 0.18m ahead/i)).toBeInTheDocument();
    expect(screen.getByText(/±0.05m optical tolerance/i)).toBeInTheDocument();
  });

  it("expands official IFAB clause text on click", () => {
    const assessment = { verdict: "onside", margin_m: -0.4, uncertainty_m: 0.05 };
    render(<Law11Card assessment={assessment} />);

    const button = screen.getByRole("button", { name: /show official ifab clause text/i });
    expect(screen.queryByText(/IFAB Law 11.1:/i)).not.toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.getByText(/IFAB Law 11.1:/i)).toBeInTheDocument();
    expect(screen.getByText(/Active Involvement:/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /hide official ifab clause text/i }));
    expect(screen.queryByText(/IFAB Law 11.1:/i)).not.toBeInTheDocument();
  });

  it("renders Law 12 DOGSO and excessive force evaluation for red card", () => {
    const incident = {
      sanction: "red",
      verdict: "red",
    };

    render(<IfabRuleAssistant mode="law12" incident={incident} />);

    expect(screen.getByText("IFAB Law 12")).toBeInTheDocument();
    expect(screen.getByText("Foul & Misconduct (DOGSO)")).toBeInTheDocument();
    expect(screen.getByText("Red Card Sanction")).toBeInTheDocument();
    expect(screen.getByText(/DOGSO 4-D Criteria Checklist/i)).toBeInTheDocument();
    expect(screen.getByText(/Excessive force \/ studs above the ankle/i)).toBeInTheDocument();

    const button = screen.getByRole("button", { name: /show ifab law 12 guidance/i });
    fireEvent.click(button);
    expect(screen.getByText(/Serious Foul Play:/i)).toBeInTheDocument();
    expect(screen.getByText(/DOGSO in Penalty Area:/i)).toBeInTheDocument();
  });
});

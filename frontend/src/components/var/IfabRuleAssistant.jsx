import React, { useState } from "react";

export function Law11Card({ assessment }) {
  const [expanded, setExpanded] = useState(false);
  const isOffside = assessment?.verdict === "offside";
  const isOnside = assessment?.verdict === "onside";
  const margin = Number.isFinite(assessment?.margin_m) ? assessment.margin_m : 0;
  const uncertainty = Number.isFinite(assessment?.uncertainty_m) ? assessment.uncertainty_m : 0.05;
  const isToleranceOverlap = Math.abs(margin) <= uncertainty;

  return (
    <section
      aria-label="IFAB Law 11 AI Rule Breakdown"
      className="rounded-xl border border-line bg-surface p-4 sm:p-5 flex flex-col gap-3.5 text-sm"
    >
      <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-accent/15 text-accent border border-accent/30">
            IFAB Law 11
          </span>
          <h4 className="font-semibold text-fg">Offside Evaluation</h4>
        </div>
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            isOffside
              ? "bg-loss/15 text-loss border border-loss/30"
              : isOnside
              ? "bg-win/15 text-win border border-win/30"
              : "bg-accent/15 text-accent border border-accent/30"
          }`}
        >
          {isOffside ? "Infringement Detected" : isOnside ? "Legal Play" : "Under Review"}
        </span>
      </div>

      <div className="flex flex-col gap-2.5 text-xs text-muted">
        <div className="flex items-start gap-2">
          <span className="text-accent font-mono shrink-0">11.1</span>
          <div>
            <span className="font-medium text-fg">Position at Pass Release: </span>
            {isOffside
              ? `Attacker is ${Math.abs(margin).toFixed(2)}m ahead of the 2nd-to-last defender line.`
              : `Attacker is ${Math.abs(margin).toFixed(2)}m onside behind the defensive line.`}
          </div>
        </div>

        <div className="flex items-start gap-2">
          <span className="text-accent font-mono shrink-0">11.2</span>
          <div>
            <span className="font-medium text-fg">Permitted Scoring Anatomy: </span>
            <span>Measured at tracked foot/torso plane. Hands and arms excluded per Law 11 definition.</span>
          </div>
        </div>

        <div className="flex items-start gap-2">
          <span className="text-accent font-mono shrink-0">Tol.</span>
          <div>
            <span className="font-medium text-fg">Hawk-Eye Calibration Margin: </span>
            <span>
              ±{uncertainty.toFixed(2)}m optical tolerance.{" "}
              {isToleranceOverlap
                ? "Margin is within tolerance threshold (benefit of the doubt applies under strict guidance)."
                : "Margin exceeds optical uncertainty threshold."}
            </span>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="pressable text-xs font-medium text-accent self-start hover:underline flex items-center gap-1 mt-1"
      >
        <span>{expanded ? "Hide official IFAB clause text" : "Show official IFAB clause text"}</span>
        <span aria-hidden="true">{expanded ? "↑" : "↓"}</span>
      </button>

      {expanded && (
        <div className="rounded-lg bg-raised/60 p-3 text-xs text-muted leading-relaxed flex flex-col gap-2 border border-line/60">
          <p>
            <strong className="text-fg">IFAB Law 11.1:</strong> A player is in an offside position if:
            any part of the head, body or feet is in the opponents&apos; half (excluding the halfway line) and
            nearer to the opponents&apos; goal line than both the ball and the second-last opponent.
          </p>
          <p>
            <strong className="text-fg">Active Involvement:</strong> Interfering with play, interfering with an
            opponent, or gaining an advantage by being in that position.
          </p>
        </div>
      )}
    </section>
  );
}

export function Law12Card({ incident }) {
  const [expanded, setExpanded] = useState(false);
  const isRed = incident?.sanction === "red" || incident?.verdict === "red";
  const isYellow = incident?.sanction === "yellow";

  return (
    <section
      aria-label="IFAB Law 12 AI Rule Breakdown"
      className="rounded-xl border border-line bg-surface p-4 sm:p-5 flex flex-col gap-3.5 text-sm"
    >
      <div className="flex items-center justify-between gap-2 border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-loss/15 text-loss border border-loss/30">
            IFAB Law 12
          </span>
          <h4 className="font-semibold text-fg">Foul & Misconduct (DOGSO)</h4>
        </div>
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
            isRed
              ? "bg-loss/15 text-loss border border-loss/30"
              : isYellow
              ? "bg-accent/15 text-accent border border-accent/30"
              : "bg-win/15 text-win border border-win/30"
          }`}
        >
          {isRed ? "Red Card Sanction" : isYellow ? "Yellow Card Caution" : "Careless / No Card"}
        </span>
      </div>

      <div className="flex flex-col gap-2.5 text-xs text-muted">
        <div className="flex items-start gap-2">
          <span className="text-loss font-mono shrink-0">12.3</span>
          <div>
            <span className="font-medium text-fg">DOGSO 4-D Criteria Checklist:</span>
            <ul className="mt-1 list-disc list-inside space-y-0.5">
              <li><strong className="text-fg">Distance:</strong> Inside attacking final third</li>
              <li><strong className="text-fg">Direction:</strong> Attacking velocity oriented directly toward goal</li>
              <li><strong className="text-fg">Defenders:</strong> No covering defender in position to intervene</li>
              <li><strong className="text-fg">Control:</strong> High probability of maintaining / gaining control</li>
            </ul>
          </div>
        </div>

        <div className="flex items-start gap-2">
          <span className="text-loss font-mono shrink-0">Force</span>
          <div>
            <span className="font-medium text-fg">Point & Severity of Contact: </span>
            <span>
              {isRed
                ? "Excessive force / studs above the ankle endangering opponent's safety."
                : "Reckless challenge with disregard to the consequence to opponent."}
            </span>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="pressable text-xs font-medium text-accent self-start hover:underline flex items-center gap-1 mt-1"
      >
        <span>{expanded ? "Hide IFAB Law 12 guidance" : "Show IFAB Law 12 guidance"}</span>
        <span aria-hidden="true">{expanded ? "↑" : "↓"}</span>
      </button>

      {expanded && (
        <div className="rounded-lg bg-raised/60 p-3 text-xs text-muted leading-relaxed flex flex-col gap-2 border border-line/60">
          <p>
            <strong className="text-fg">Serious Foul Play:</strong> A tackle or challenge that endangers the safety
            of an opponent or uses excessive force or brutality must be sanctioned as serious foul play (Direct Red).
          </p>
          <p>
            <strong className="text-fg">DOGSO in Penalty Area:</strong> Where a player commits an offence against an
            opponent which denies an obvious goal-scoring opportunity and the referee awards a penalty kick, the offender
            is cautioned if the offence was an attempt to play the ball. In all other circumstances (holding, pulling, no attempt),
            the offender is sent off.
          </p>
        </div>
      )}
    </section>
  );
}

export default function IfabRuleAssistant({ mode = "law11", assessment, incident }) {
  if (mode === "law12") {
    return <Law12Card incident={incident} />;
  }
  return <Law11Card assessment={assessment} />;
}

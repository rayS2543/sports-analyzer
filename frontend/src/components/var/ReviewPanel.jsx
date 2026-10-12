import React from "react";
import { VERDICT_STYLE } from "./VerdictCard";
import { formatClock } from "./varMath";

const signed = (m) => (Number.isFinite(m) ? `${m > 0 ? "+" : m < 0 ? "−" : ""}${Math.abs(m).toFixed(2)} m` : "no margin");

/**
 * One-click review: every detected pass, and every attacker checked at that moment.
 * Pure presentation; VarViewer owns the data and what "open" means (seek, lines, camera).
 */
export default function ReviewPanel({ state, active, onOpen, onCandidate, labelFor, onManual }) {
  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="Reviewing detected passes">
        <p className="text-sm text-muted">Finding the moments the ball was played and checking every attacker…</p>
        {[80, 64].map((w) => (
          <div key={w} className="skeleton h-9 rounded-lg" style={{ width: `${w}%` }} />
        ))}
      </div>
    );
  }
  if (state.status === "error" || !state.reviews?.length) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">
          {state.status === "error"
            ? `Automatic review isn't available: ${state.error}`
            : state.message || "No pass was detected in these seconds, so there's nothing to check automatically."}
        </p>
        <button type="button" onClick={onManual} className="pressable self-start h-9 px-4 rounded-lg border border-line text-sm font-medium hover:border-faint">
          Check a moment yourself
        </button>
      </div>
    );
  }

  const review = state.reviews[active.review];
  const keyId = review.key?.attacker_track_id;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-medium text-faint">Passes detected ({state.reviews.length})</h4>
        <div role="tablist" aria-label="Detected passes" className="flex flex-wrap gap-1.5">
          {state.reviews.map((r, i) => {
            const on = i === active.review;
            const tone = VERDICT_STYLE[r.key?.verdict] || VERDICT_STYLE.inconclusive;
            return (
              <button
                key={`${r.event.t}-${i}`}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => onOpen(i)}
                className={`pressable inline-flex items-center gap-2 h-8 px-3 rounded-lg border text-xs font-medium ${
                  on ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg hover:border-faint"
                }`}
              >
                <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${tone.bar}`} />
                <span className="font-mono tabular-nums">{formatClock(r.event.t)}</span>
                <span>Team {r.event.team}</span>
              </button>
            );
          })}
        </div>
        <p className="text-xs text-faint">
          {review.event.reason}
          {Number.isFinite(review.event.confidence) && ` · detection confidence ${Math.round(review.event.confidence * 100)}%`}
        </p>
      </div>

      {review.candidates?.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="text-xs font-medium text-faint">Attackers at this pass</h4>
          <ul className="flex flex-col gap-1">
            {[...review.candidates]
              .sort((a, b) => (b.margin_m ?? -Infinity) - (a.margin_m ?? -Infinity))
              .map((c) => {
                const on = c.track_id === active.attacker;
                const tone = VERDICT_STYLE[c.verdict] || VERDICT_STYLE.inconclusive;
                return (
                  <li key={c.track_id}>
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => onCandidate(c.track_id)}
                      className={`pressable w-full flex items-center gap-3 rounded-lg px-3 h-10 text-left text-sm ${on ? "bg-raised" : "hover:bg-raised/60"}`}
                    >
                      <span aria-hidden="true" className={`w-2 h-2 rounded-full ${tone.bar}`} />
                      <span className="font-medium tabular-nums">{labelFor(c.track_id)}</span>
                      {c.track_id === keyId && <span className="hidden sm:inline text-[11px] text-faint whitespace-nowrap">most advanced</span>}
                      <span className={`ml-auto text-xs font-medium ${tone.text}`}>{tone.label}</span>
                      <span className="w-20 text-right font-mono text-xs tabular-nums text-muted">{signed(c.margin_m)}</span>
                    </button>
                  </li>
                );
              })}
          </ul>
        </div>
      )}

      <button type="button" onClick={onManual} className="pressable self-start text-sm font-medium text-accent hover:underline">
        Check a different moment or player
      </button>
    </div>
  );
}

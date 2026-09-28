import React from "react";
import { formatClock } from "./varMath";

export const VERDICT_STYLE = {
  offside: { label: "Offside", text: "text-loss", bar: "bg-loss", border: "border-loss/40" },
  onside: { label: "Onside", text: "text-win", bar: "bg-win", border: "border-win/40" },
  inconclusive: { label: "Inconclusive", text: "text-accent", bar: "bg-accent", border: "border-accent/40" },
};

const fmt = (m) => `${m > 0 ? "+" : m < 0 ? "−" : ""}${Math.abs(m).toFixed(2)} m`;

// Where the attacker sits relative to the offside line, with the ± uncertainty band drawn to scale.
function MarginRuler({ margin, uncertainty, verdict }) {
  const span = Math.max(1.5, Math.abs(margin) + uncertainty + 0.5);
  const pos = (v) => `${50 + (v / span) * 50}%`;
  return (
    <figure className="flex flex-col gap-1.5" aria-label={`Attacker ${fmt(margin)} from the offside line, uncertainty ±${uncertainty.toFixed(2)} m`}>
      <div className="relative h-8" aria-hidden="true">
        <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
        <div
          className="absolute top-1 bottom-1 rounded-sm bg-accent/20 border-x border-accent/50"
          style={{ left: pos(-uncertainty), width: `${(uncertainty / span) * 100}%` }}
        />
        <div className="absolute top-0 bottom-0 w-0.5 -ml-px bg-accent" style={{ left: pos(0) }} />
        <div
          className={`absolute top-1/2 w-3 h-3 -ml-1.5 -mt-1.5 rounded-full ring-2 ring-canvas ${VERDICT_STYLE[verdict].bar}`}
          style={{ left: pos(margin) }}
        />
      </div>
      <figcaption className="flex justify-between text-[11px] text-faint">
        <span>← Onside side</span>
        <span className="text-accent/80">Offside line</span>
        <span>Offside side →</span>
      </figcaption>
    </figure>
  );
}

/** The system's own evidence-based call. Deliberately never shows or references the official call. */
export function VerdictCard({ result }) {
  const style = VERDICT_STYLE[result.verdict] || VERDICT_STYLE.inconclusive;
  const hasMargin = Number.isFinite(result.margin_m);
  const u = Number.isFinite(result.uncertainty_m) ? result.uncertainty_m : null;
  return (
    <article
      aria-labelledby="verdict-heading"
      data-verdict={result.verdict}
      className={`relative overflow-hidden rounded-xl border bg-surface p-5 flex flex-col gap-4 ${style.border}`}
    >
      <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-0.5 ${style.bar}`} />
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="verdict-heading" className="text-xs font-medium uppercase tracking-[0.14em] text-muted">
          System assessment
        </h3>
        {Number.isFinite(result.frame_t) && <span className="font-mono text-xs text-faint tabular-nums">frame {formatClock(result.frame_t)}</span>}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <p className={`text-4xl font-semibold tracking-tight ${style.text}`}>{style.label}</p>
        {hasMargin && (
          <p className="font-mono text-sm tabular-nums text-fg">
            {fmt(result.margin_m)}
            {u != null && <span className="text-muted"> ± {u.toFixed(2)} m</span>}
          </p>
        )}
      </div>
      {hasMargin && u != null && <MarginRuler margin={result.margin_m} uncertainty={u} verdict={result.verdict in VERDICT_STYLE ? result.verdict : "inconclusive"} />}
      {result.reasons?.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium text-faint">Why</h4>
          <ul className="flex flex-col gap-1.5 text-sm text-muted">
            {result.reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <span aria-hidden="true" className="mt-2 w-1 h-1 rounded-full bg-faint shrink-0" />
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-faint border-t border-line pt-3">
        Measured between tracked foot positions, not limbs. Worked out from the footage alone, without looking at the official
        decision.
      </p>
    </article>
  );
}

const TYPE_LABEL = {
  offside: "Offside",
  red_card: "Red card",
  yellow_card: "Yellow card",
  penalty: "Penalty",
  goal: "Goal",
  var: "VAR",
};
const TYPE_TONE = {
  red_card: "bg-loss",
  yellow_card: "bg-accent",
  offside: "bg-fg",
  var: "bg-fg",
  penalty: "bg-fg",
  goal: "bg-win",
};

/** What the match officials decided, as recorded by ESPN. Visually a plain log, never a verdict. */
export function OfficialRecord({ state }) {
  return (
    <section aria-labelledby="official-heading" className="rounded-xl border border-dashed border-line p-5 flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="official-heading" className="text-xs font-medium uppercase tracking-[0.14em] text-muted">
          Official record (ESPN)
        </h3>
        <span className="text-xs text-faint">Match clock, not clip time</span>
      </div>
      {state.error && <p className="text-sm text-muted">{state.error}</p>}
      {!state.error && !state.events && (
        <div className="flex flex-col gap-2.5" aria-busy="true" aria-label="Loading official record">
          {[70, 55, 62].map((w) => (
            <div key={w} className="skeleton h-3.5" style={{ width: `${w}%` }} />
          ))}
        </div>
      )}
      {state.events?.length === 0 && (
        <p className="text-sm text-muted">ESPN lists no offsides, cards, penalties or VAR checks for this match.</p>
      )}
      {state.events?.length > 0 && (
        <ol className="flex flex-col divide-y divide-line/70 -my-2">
          {state.events.map((e, i) => (
            <li key={`${e.clock}-${i}`} className="grid grid-cols-[3rem_1fr] gap-3 py-2.5 text-sm">
              <span className="font-mono text-xs text-faint tabular-nums pt-0.5">{e.clock ?? "–"}</span>
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="flex items-center gap-2 font-medium">
                  <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${TYPE_TONE[e.type] || "bg-faint"}`} />
                  {TYPE_LABEL[e.type] || e.type}
                  {e.team && <span className="text-muted font-normal truncate">· {e.team}</span>}
                </span>
                {e.text && <span className="text-muted">{e.text}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="text-xs text-faint border-t border-line pt-3">For reference only. The system assessment is never adjusted to agree with it.</p>
    </section>
  );
}

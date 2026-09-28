import React, { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { API_BASE } from "../../apiBase";
import { formatClock } from "./varMath";

// Same visual language as VerdictCard: red = loss, cleared = win, inconclusive = accent.
const VERDICT = {
  red: { label: "Red", text: "text-loss", bar: "bg-loss", border: "border-loss/40" },
  not_red: { label: "Not red", text: "text-win", bar: "bg-win", border: "border-win/40" },
  inconclusive: { label: "Inconclusive", text: "text-accent", bar: "bg-accent", border: "border-accent/40" },
};
const SANCTION = {
  red: { label: "Red card", text: "text-loss", card: "bg-loss" },
  yellow: { label: "Yellow card", text: "text-accent", card: "bg-accent" },
  none: { label: "No red-card ground", text: "text-win", card: null },
  inconclusive: { label: "Inconclusive", text: "text-accent", card: null },
};
const VALUE_LABEL = { towards_goal: "Towards goal", away_from_goal: "Away from goal", across: "Across the pitch" };
const RELY = 0.6;

const apiError = (err, fallback) => err?.response?.data?.error || fallback;

function formatValue(ind) {
  if (!ind.observable || ind.value == null) return "Not observable";
  if (ind.value === true) return "Yes";
  if (ind.value === false) return "No";
  if (typeof ind.value === "number") return `${ind.value}${ind.unit ? ` ${ind.unit}` : ""}`;
  return VALUE_LABEL[ind.value] || String(ind.value);
}

function Confidence({ value, label }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <span className="flex items-center gap-2 shrink-0" title={`Confidence ${pct}% (relied on at ${RELY * 100}% or more)`}>
      <span
        role="meter"
        aria-label={`${label} confidence`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="relative w-16 h-1.5 rounded-full bg-line overflow-hidden"
      >
        <span className={`absolute inset-y-0 left-0 rounded-full ${value >= RELY ? "bg-fg/70" : "bg-faint"}`} style={{ width: `${pct}%` }} />
        <span aria-hidden="true" className="absolute inset-y-0 w-px bg-canvas" style={{ left: `${RELY * 100}%` }} />
      </span>
      <span className="font-mono text-[11px] tabular-nums text-faint w-8 text-right">{pct}%</span>
    </span>
  );
}

function Indicator({ ind }) {
  const hidden = !ind.observable;
  return (
    <li className="flex flex-col gap-0.5 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted min-w-0">{ind.label}</span>
        <span className="flex items-baseline gap-3">
          <span className={`text-sm font-medium tabular-nums ${hidden ? "text-faint italic" : "text-fg"}`}>{formatValue(ind)}</span>
          <Confidence value={ind.confidence} label={ind.label} />
        </span>
      </div>
      {ind.detail && <p className="text-xs text-faint">{ind.detail}</p>}
    </li>
  );
}

function GroundCard({ ground, id }) {
  const style = VERDICT[ground.verdict] || VERDICT.inconclusive;
  const headingId = `${id}-${ground.ground}`;
  return (
    <article
      aria-labelledby={headingId}
      data-verdict={ground.verdict}
      className={`relative overflow-hidden rounded-xl border bg-surface p-4 flex flex-col gap-3 ${style.border}`}
    >
      <span aria-hidden="true" className={`absolute inset-x-0 top-0 h-0.5 ${style.bar}`} />
      <h4 id={headingId} className="text-xs font-medium uppercase tracking-[0.14em] text-muted">
        {ground.label}
      </h4>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className={`text-2xl font-semibold tracking-tight ${style.text}`}>{style.label}</p>
        {ground.downgraded_to === "yellow" && <p className="text-sm text-accent">Downgraded to a caution (penalty area)</p>}
      </div>
      {ground.reasons?.length > 0 && (
        <ul className="flex flex-col gap-1.5 text-sm text-muted">
          {ground.reasons.map((r) => (
            <li key={r} className="flex gap-2">
              <span aria-hidden="true" className="mt-2 w-1 h-1 rounded-full bg-faint shrink-0" />
              {r}
            </li>
          ))}
        </ul>
      )}
      {ground.indicators?.length > 0 && (
        <details className="group border-t border-line pt-2">
          <summary className="cursor-pointer text-xs font-medium text-faint hover:text-fg">
            Evidence ({ground.indicators.filter((i) => i.observable).length}/{ground.indicators.length} observable)
          </summary>
          <ul className="flex flex-col divide-y divide-line/60 mt-1">
            {ground.indicators.map((ind) => (
              <Indicator key={ind.key} ind={ind} />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function who(p) {
  if (!p) return "?";
  const num = p.jersey_number != null ? `#${p.jersey_number}` : `track ${p.track_id}`;
  return `Team ${p.team ?? "?"} ${num}`;
}

function SanctionBadge({ sanction }) {
  const s = SANCTION[sanction] || SANCTION.inconclusive;
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${s.text}`}>
      {s.card && <span aria-hidden="true" className={`w-2.5 h-3.5 rounded-[2px] rotate-6 ${s.card}`} />}
      {s.label}
    </span>
  );
}

function Incident({ inc, open, active, onSelect }) {
  const id = `foul-${inc.id}`;
  const players = inc.players?.challenger
    ? `${who(inc.players.challenger)} on ${who(inc.players.victim)}`
    : (inc.players?.involved || []).map(who).join(" and ");
  return (
    <li className={`rounded-xl border ${active ? "border-accent/60" : "border-line"} bg-canvas/40`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-body`}
        onClick={onSelect}
        className="pressable w-full flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left rounded-xl hover:bg-raised/60"
      >
        <span className="font-mono text-sm tabular-nums text-fg">{formatClock(inc.t)}</span>
        <span className="text-sm text-muted min-w-0 truncate flex-1">{players || "Players not identified"}</span>
        <SanctionBadge sanction={inc.sanction} />
      </button>
      {open && (
        <div id={`${id}-body`} className="px-4 pb-4 flex flex-col gap-3">
          <p className="text-sm text-muted">{inc.sanction_note}</p>
          <div className="grid gap-3 lg:grid-cols-3">
            {inc.grounds.map((g) => (
              <GroundCard key={g.ground} ground={g} id={id} />
            ))}
          </div>
          {inc.notes?.length > 0 && (
            <ul className="flex flex-col gap-1 text-xs text-faint">
              {inc.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * Law 12 sending-off review of an analysed window. The system's own assessment only; the official
 * decision lives in OfficialRecord and is never read here.
 */
export default function FoulReview({ clip, start, end, time, onSeek, pollMs = 1500 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/var/fouls/${clip}`, { params: { start, end } });
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(apiError(err, "Could not load the foul review."));
    }
  }, [clip, start, end]);

  useEffect(() => {
    setData(null);
    setOpenId(null);
    load();
  }, [load]);

  const running = data?.status === "running" || data?.status === "queued";
  useEffect(() => {
    if (!running) return undefined;
    const id = setTimeout(load, pollMs);
    return () => clearTimeout(id);
  }, [running, data, load, pollMs]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await axios.post(`${API_BASE}/var/fouls`, { clip, start, end });
      if (res.data.status === "done") await load();
      else setData((d) => ({ ...d, status: "running", progress: null }));
    } catch (err) {
      setError(apiError(err, "Could not start the foul review."));
    } finally {
      setBusy(false);
    }
  };

  const select = (inc) => {
    setOpenId((id) => (id === inc.id ? null : inc.id));
    onSeek?.(inc.t);
  };

  const progress = data?.progress?.progress;
  return (
    <section aria-labelledby="foul-review-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="foul-review-heading" className="text-xs font-medium uppercase tracking-[0.14em] text-muted">
          Foul / red-card review
        </h3>
        <span className="text-xs text-faint">
          IFAB Law 12 · analysed {formatClock(start)}–{formatClock(end)}
        </span>
      </div>

      {error && (
        <p role="alert" className="text-sm text-loss">
          {error}
        </p>
      )}

      {!data && !error && (
        <div className="flex flex-col gap-2.5" aria-busy="true" aria-label="Loading foul review">
          {[65, 48].map((w) => (
            <div key={w} className="skeleton h-3.5" style={{ width: `${w}%` }} />
          ))}
        </div>
      )}

      {(data?.status === "none" || data?.status === "failed") && (
        <div className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-3">
          {data.status === "failed" ? (
            <p className="text-sm text-muted">The last review failed: {data.error}</p>
          ) : (
            <p className="text-sm text-muted">
              Finds challenges between opponents in these seconds, runs pose estimation around each contact and checks the three
              sending-off grounds. Takes a few minutes.
            </p>
          )}
          <button
            type="button"
            onClick={run}
            disabled={busy}
            className="pressable self-start rounded-lg bg-accent text-accent-fg px-3 h-9 text-sm font-medium disabled:opacity-60"
          >
            {data.status === "failed" ? "Try again" : "Review challenges"}
          </button>
        </div>
      )}

      {running && (
        <div className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-2" aria-live="polite">
          <p className="text-sm text-muted">{data.progress?.message || "Starting the foul review…"}</p>
          <div
            role="progressbar"
            aria-label="Foul review progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Number.isFinite(progress) ? Math.round(progress * 100) : undefined}
            className="h-1.5 rounded-full bg-line overflow-hidden"
          >
            <div className="h-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.round((progress || 0.02) * 100)}%` }} />
          </div>
        </div>
      )}

      {data?.status === "done" && (
        <>
          {data.message && <p className="text-sm text-muted">{data.message}</p>}
          {data.incidents?.length > 0 && (
            <ol className="flex flex-col gap-2" aria-label="Examined challenges">
              {data.incidents.map((inc) => (
                <Incident
                  key={inc.id}
                  inc={inc}
                  open={openId === inc.id}
                  active={Number.isFinite(time) && Math.abs(time - inc.t) < 0.15}
                  onSelect={() => select(inc)}
                />
              ))}
            </ol>
          )}
          {data.assumptions?.length > 0 && (
            <details className="text-xs text-faint">
              <summary className="cursor-pointer hover:text-fg">What the measurements assume</summary>
              <ul className="mt-2 flex flex-col gap-1 list-disc pl-4">
                {data.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      <p className="text-xs text-faint border-t border-line pt-3">
        Measured from one broadcast angle: limbs are 2D pose keypoints, force and intent are not measurable, and anything the camera
        cannot see is reported as not observable rather than guessed. Worked out without looking at the official decision.
      </p>
    </section>
  );
}

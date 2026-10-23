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
const SAME_T = 0.3; // s: the same contact found again after a re-run of the foul review

// "1.0-7.0" or {start, end} → "0:01.0–0:07.0".
function windowLabel(w) {
  const [a, b] = typeof w === "string" ? w.split("-").map(Number) : [w?.start, w?.end];
  return Number.isFinite(a) && Number.isFinite(b) ? `${formatClock(a)}–${formatClock(b)}` : null;
}
const speedLabel = (s) => (Number.isFinite(s) ? `×${Number(s.toFixed(2))}` : "");
const nearest = (items, t, of = (x) => x.t) =>
  items.filter((x) => Math.abs(of(x) - t) <= SAME_T).sort((a, b) => Math.abs(of(a) - t) - Math.abs(of(b) - t))[0] ?? null;

function ProgressBar({ label, value }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Number.isFinite(value) ? Math.round(value * 100) : undefined}
      className="h-1.5 rounded-full bg-line overflow-hidden"
    >
      <div className="h-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.round((value || 0.02) * 100)}%` }} />
    </div>
  );
}

/** The cross-view job of a replay window: running, honestly failed, or done (with what it rests on). */
function CrossViewStatus({ xv, current }) {
  if (!xv || xv.status === "none") return null;
  if (xv.status === "error")
    return (
      <p role="alert" className="text-sm text-loss">
        {xv.error}
      </p>
    );
  const where = current ? "this replay" : `the replay ${formatClock(xv.start)}–${formatClock(xv.end)}`;
  const r = xv.report || {};
  if (xv.status === "running")
    return (
      <div className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-2" aria-live="polite">
        <p className="text-sm text-muted">
          Calibrating {where} from the live camera: {xv.progress?.message || "starting…"}
        </p>
        <ProgressBar label="Cross-view calibration progress" value={xv.progress?.progress} />
      </div>
    );
  if (xv.status === "failed")
    return (
      <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm text-muted">
        Couldn&rsquo;t calibrate {where} from the live camera: {xv.error}. Its positions stay unmeasured rather than guessed.
      </p>
    );
  const live = windowLabel(r.live?.window);
  const frames = Number.isFinite(r.calibrated_frames) && Number.isFinite(r.frames) ? ` · ${r.calibrated_frames}/${r.frames} frames calibrated` : "";
  return (
    <p className="rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-muted">
      Positions in {where} are inferred from the live camera{live ? ` (${live})` : ""}, synced {speedLabel(r.speed)}
      {frames}. They come from the live shot&rsquo;s tracked players, not from the replay&rsquo;s own pitch lines.
    </p>
  );
}

/** Offered when the combined angles are an uncalibrated replay plus a calibrated live shot. */
function CalibrateOffer({ req, busy, onCalibrate }) {
  const [liveT, replayT] = req.anchor || [];
  return (
    <div className="rounded-lg border border-line bg-canvas/40 p-3 flex flex-col gap-2">
      <p className="text-sm text-muted">
        The replay ({windowLabel(req)}) has no calibrated frame, so distances, speeds and DOGSO can&rsquo;t be measured from it. Its
        camera can be inferred from the calibrated live camera ({windowLabel(req.live)})
        {req.anchor
          ? `, synced on these two contacts (${formatClock(liveT)} live, ${formatClock(replayT)} replay)`
          : ", synced automatically on contacts both reviews found (not on this pair)"}
        . Then the
        replay&rsquo;s challenges are reviewed again. Takes several minutes.
      </p>
      <button
        type="button"
        onClick={onCalibrate}
        disabled={busy}
        className="pressable self-start rounded-lg bg-accent text-accent-fg px-3 h-9 text-sm font-medium disabled:opacity-60"
      >
        Calibrate this replay from the live camera
      </button>
    </div>
  );
}

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

const LEAN_WORD = { red: "red", not_red: "not red" };

/** The graded reading under an inconclusive verdict: explicitly not a decision, and its % is the geometry's own uncertainty. */
function Lean({ lean, ground }) {
  if (!lean || lean.reading === "no_lean") return null;
  const pct = Math.round(lean.probability * 100);
  return (
    <div data-testid="lean" className="rounded-lg border border-line bg-canvas/40 px-3 py-2 flex flex-col gap-1">
      <p className="text-sm text-fg">
        Leans {LEAN_WORD[lean.reading]}, ~{pct}%<span className="text-muted"> — not a decision</span>
        {ground && <span className="text-muted"> ({ground})</span>}
      </p>
      {lean.basis && <p className="text-xs text-muted">{lean.basis}.</p>}
      {lean.settle?.length > 0 && <p className="text-xs text-faint">Would settle it: {lean.settle.join("; ")}.</p>}
      <p className="text-xs text-faint">
        The % is the measurements&apos; own uncertainty carried through, not a validated hit rate. Only a verdict at {RELY * 100}%+ confidence is a call.
      </p>
    </div>
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
      <Lean lean={ground.lean} />
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

function playersOf(inc) {
  return inc.players?.challenger
    ? `${who(inc.players.challenger)} on ${who(inc.players.victim)}`
    : (inc.players?.involved || []).map(who).join(" and ");
}

/** Same incident from another reviewed window (e.g. a close-up replay): each piece of evidence is
 * taken from the angle that saw it best; the backend refuses contradictory or opposite-kit pairs. */
function CombineAngles({ clip, start, end, inc, others, suggested = [], autoPartner, onAutoDone, xvBusy, onCalibrate }) {
  const [result, setResult] = useState(null);
  const [offer, setOffer] = useState(null); // cross-view job body, also on a refused pairing (then unanchored)
  const [after, setAfter] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState("");
  // Pairs the cross-view time map matched to this challenge: offered first.
  const isThis = (p) => p.clip === clip && p.start === start && p.end === end && p.id === inc.id;
  const partners = suggested.flatMap((s) => (isThis(s.replay) ? [[s.live, s]] : isThis(s.live) ? [[s.replay, s]] : []));
  const options = others.flatMap((w) =>
    w.incidents.map((o) => ({
      w,
      o,
      value: `${w.key}|${o.id}`,
      pair: partners.find(([p]) => p.clip === clip && p.start === w.start && p.end === w.end && p.id === o.id)?.[1],
    })),
  );

  const pick = async (value) => {
    setChosen(value);
    setResult(null);
    setOffer(null);
    setError(null);
    const choice = options.find((opt) => opt.value === value);
    if (!choice) return;
    setBusy(true);
    setAfter({ incT: inc.t, partner: { start: choice.w.start, end: choice.w.end, t: choice.o.t } });
    try {
      const res = await axios.post(`${API_BASE}/var/fouls/${clip}/combine`, {
        parts: [
          { start, end, id: inc.id },
          { start: choice.w.start, end: choice.w.end, id: choice.o.id },
        ],
      });
      setResult(res.data);
      setOffer(res.data?.crossview_available ? res.data.crossview_request : null);
    } catch (err) {
      setError(apiError(err, "Could not combine the angles."));
      const body = err?.response?.data;
      setOffer(body?.crossview_available ? body.crossview_request : null);
    } finally {
      setBusy(false);
    }
  };

  // After a cross-view job the reviews were re-run (ids may change): combine the same pair again, found by time.
  const optionsKey = options.map((o) => o.value).join();
  useEffect(() => {
    if (!autoPartner) return;
    const near = nearest(
      options.filter(({ w }) => w.start === autoPartner.start && w.end === autoPartner.end),
      autoPartner.t,
      (opt) => opt.o.t,
    );
    if (near) {
      onAutoDone?.();
      pick(near.value);
    }
  }, [autoPartner, optionsKey]);

  if (!options.length) return null;
  const label = ({ w, o, pair }) =>
    `${formatClock(w.start)}–${formatClock(w.end)} · ${formatClock(o.t)} · ${playersOf(o) || "players not identified"}` +
    (pair ? ` · synced, ${Math.abs(pair.dt_s).toFixed(2)} s apart` : "");
  const first = options.filter((opt) => opt.pair);
  const rest = options.filter((opt) => !opt.pair);
  const list = (opts) =>
    opts.map((opt) => (
      <option key={opt.value} value={opt.value}>
        {label(opt)}
      </option>
    ));

  const id = `foul-${inc.id}-combined`;
  return (
    <div className="border-t border-line pt-3 flex flex-col gap-3">
      <label className="flex flex-wrap items-center gap-2 text-sm text-muted">
        Same incident from another angle
        <select
          value={chosen}
          disabled={busy}
          onChange={(e) => pick(e.target.value)}
          className="min-w-0 max-w-full rounded-lg border border-line bg-surface px-2 h-9 text-sm text-fg"
        >
          <option value="">Choose a reviewed challenge…</option>
          {first.length ? (
            <>
              <optgroup label="Matched by the cross-view sync">{list(first)}</optgroup>
              <optgroup label="Other reviewed challenges">{list(rest)}</optgroup>
            </>
          ) : (
            list(rest)
          )}
        </select>
      </label>
      {error && (
        <p role="alert" className="text-sm text-loss">
          {error}
        </p>
      )}
      {offer && <CalibrateOffer req={offer} busy={xvBusy} onCalibrate={() => onCalibrate(offer, offer.anchor ? after : null)} />}
      {result && (
        <section aria-label="Combined angles" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-3">
            <SanctionBadge sanction={result.sanction} />
            <span className="text-xs text-faint">
              Combined from {result.angles.map((a) => `${a.angle} at ${formatClock(a.t)}`).join(" and ")}
            </span>
          </div>
          <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(14rem,1fr))]">
            {result.grounds.map((g) => (
              <GroundCard key={g.ground} ground={g} id={id} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Incident({ inc, open, active, onSelect, combine }) {
  const id = `foul-${inc.id}`;
  const players = playersOf(inc);
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
          <Lean lean={inc.lean} ground={inc.lean && inc.grounds.find((g) => g.ground === inc.lean.ground)?.label} />
          <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(14rem,1fr))]">
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
          {combine && <CombineAngles inc={inc} {...combine} />}
        </div>
      )}
    </li>
  );
}

/**
 * Law 12 sending-off review of an analysed window. The system's own assessment only; the official
 * decision lives in OfficialRecord and is never read here.
 */
export default function FoulReview({ clip, start, end, time, onSeek, onRecalibrated, pollMs = 1500 }) {
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

  // Other windows of this clip whose foul review is done: candidate angles of the same incident.
  const [others, setOthers] = useState([]);
  const [othersVersion, setOthersVersion] = useState(0);
  const done = data?.status === "done";
  useEffect(() => {
    if (!done) return undefined;
    let alive = true;
    (async () => {
      try {
        const res = await axios.get(`${API_BASE}/var/windows/${clip}`);
        const wins = (res.data?.windows || []).filter((w) => w.status === "done" && !(w.start === start && w.end === end));
        const reviews = await Promise.all(
          wins.map((w) =>
            axios
              .get(`${API_BASE}/var/fouls/${clip}`, { params: { start: w.start, end: w.end } })
              .then((r) =>
                r.data?.status === "done" && r.data.incidents?.length
                  ? { ...w, incidents: r.data.incidents, suggested: r.data.suggested_pairs || [] }
                  : null,
              )
              .catch(() => null),
          ),
        );
        if (alive) setOthers(reviews.filter(Boolean));
      } catch {
        if (alive) setOthers([]);
      }
    })();
    return () => {
      alive = false;
    };
  }, [done, clip, start, end, othersVersion]);

  // Cross-view calibration of a replay window (this one, or one combined with it), and its job status.
  const [xv, setXv] = useState(null);
  const [rePair, setRePair] = useState(null);
  useEffect(() => {
    let alive = true;
    setXv(null);
    axios
      .get(`${API_BASE}/var/analysis/${clip}/crossview`, { params: { start, end } })
      .then((res) => alive && res.data?.status && setXv({ clip, start, end, ...res.data }))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [clip, start, end]);

  // The job re-ran the replay's foul review: reload both sides, then combine the same pair again.
  const settle = async (job) => {
    const here = job.clip === clip && job.start === start && job.end === end;
    if (here && job.status === "done") onRecalibrated?.();
    await load();
    setOthers([]);
    setOthersVersion((v) => v + 1);
    if (job.status === "done" && job.after) setRePair(job.after);
  };

  useEffect(() => {
    if (xv?.status !== "running") return undefined;
    const id = setTimeout(async () => {
      try {
        const res = await axios.get(`${API_BASE}/var/analysis/${xv.clip}/crossview`, { params: { start: xv.start, end: xv.end } });
        const next = { ...xv, ...res.data };
        setXv(next);
        if (next.status !== "running") settle(next);
      } catch {
        setXv((x) => ({ ...x })); // poll again
      }
    }, pollMs);
    return () => clearTimeout(id);
  }, [xv, pollMs]);

  const calibrate = async (req, after) => {
    const job = { clip: req.clip, start: req.start, end: req.end, after };
    setXv({ ...job, status: "running", progress: null });
    try {
      await axios.post(`${API_BASE}/var/analysis/${req.clip}/crossview`, { start: req.start, end: req.end, live: req.live, anchor: req.anchor });
    } catch (err) {
      setXv({ ...job, status: "error", error: apiError(err, "Could not start the cross-view calibration.") });
    }
  };

  // Reopen the re-reviewed challenge (found by time: ids can change) so it re-combines with its partner.
  const rePairId = rePair && data?.incidents ? nearest(data.incidents, rePair.incT)?.id : undefined;
  useEffect(() => {
    if (rePairId != null) setOpenId(rePairId);
  }, [rePairId]);
  const suggested = [...(data?.suggested_pairs || []), ...others.flatMap((w) => w.suggested || [])];

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

      <CrossViewStatus xv={xv} current={xv?.clip === clip && xv?.start === start && xv?.end === end} />

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
          <ProgressBar label="Foul review progress" value={data.progress?.progress} />
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
                  combine={
                    others.length
                      ? {
                          clip,
                          start,
                          end,
                          others,
                          suggested,
                          autoPartner: inc.id === rePairId ? rePair.partner : null,
                          onAutoDone: () => setRePair(null),
                          xvBusy: xv?.status === "running",
                          onCalibrate: calibrate,
                        }
                      : null
                  }
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

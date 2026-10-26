import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "../../apiBase";
import { PageShell, formatDay } from "../ui";
import { apiError } from "./VarViewer";

const POLL_MS = 5000;
const STATUS = {
  read: ["Read", "text-accent"],
  inconclusive: ["Inconclusive", "text-muted"],
  no_passes: ["No pass found", "text-muted"],
  uncalibrated: ["Pitch not fitted", "text-loss"],
  failed: ["Failed", "text-loss"],
};

const margin = (p) =>
  p.margin_m == null ? "" : `${p.margin_m >= 0 ? "beyond the line by" : "behind the line by"} ${Math.abs(p.margin_m).toFixed(1)} m (±${(p.uncertainty_m ?? 0).toFixed(1)})`;

function Pass({ p }) {
  const text = p.restart ? `${p.restart}: offside does not apply` : p.verdict === "inconclusive" ? `inconclusive ${margin(p)}`.trim() : `${p.verdict === "offside" ? "offside position" : "onside"}, ${margin(p)}`;
  return (
    <li className="text-sm">
      <span className="font-mono text-xs tabular-nums text-faint">{p.t.toFixed(1)} s</span> {text}
      {p.flags.map((f) => (
        <p key={f} className="text-xs text-loss">
          Look at this one: {f}.
        </p>
      ))}
    </li>
  );
}

function Check({ c }) {
  const [label, tone] = STATUS[c.status] || [c.status, "text-muted"];
  const first = c.windows?.find((w) => !w.error) || c.windows?.[0];
  const [start, end] = (first?.key || "0.0-10.0").split("-");
  return (
    <li className="rounded-xl border border-line bg-surface p-4 flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{c.clip.title}</span>
        <span className="text-xs text-faint">
          {c.clip.match} · {c.clip.date ? formatDay(c.clip.date) : ""}
        </span>
        <span className={`ml-auto text-xs font-medium ${tone}`}>{label}</span>
      </div>
      {c.windows?.map((w) => (
        <div key={w.key} className="flex flex-col gap-1">
          {w.error && <p className="text-xs text-loss">{w.error}</p>}
          {!w.error && (
            <p className="text-xs text-faint">
              {w.key.replace("-", "–")} s · pitch fitted in {w.calibrated_frames[0]} of {w.calibrated_frames[1]} frames · {w.players_per_frame} players tracked per frame
            </p>
          )}
          {w.flags.map((f) => (
            <p key={f} className="text-xs text-loss">
              {f}.
            </p>
          ))}
          {w.passes.length > 0 && (
            <ul className="flex flex-col gap-1">
              {w.passes.map((p) => (
                <Pass key={p.t} p={p} />
              ))}
            </ul>
          )}
        </div>
      ))}
      <Link to={`/var?clip=${c.clip.id}&start=${start}&end=${end}`} className="pressable self-start text-sm text-accent font-medium hover:underline" aria-label={`Open ${c.clip.title} in the viewer`}>
        Open in the viewer
      </Link>
    </li>
  );
}

export default function ChecksPage() {
  const [data, setData] = useState({});
  const [lookOnly, setLookOnly] = useState(false);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  const load = () =>
    axios
      .get(`${API_BASE}/var/checks`)
      .then((res) => setData(res.data))
      .catch((err) => setError(apiError(err, "Couldn't load the checks.")));

  useEffect(() => {
    load();
    return () => clearTimeout(timer.current);
  }, []);

  // Keep refreshing while a sweep runs, so results appear as they are done.
  useEffect(() => {
    if (!data.sweep?.running) return;
    timer.current = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer.current);
  }, [data]);

  const start = () => {
    setError(null);
    axios
      .post(`${API_BASE}/var/sweep`, { league: "PD", days: 14, limit: 12 })
      .then(load)
      .catch((err) => setError(apiError(err, "Couldn't start the check.")));
  };

  const checks = (data.checks || []).filter((c) => !lookOnly || c.flagged);
  const sweep = data.sweep || {};
  return (
    <PageShell back>
      <header className="flex flex-col gap-3 max-w-2xl">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-accent">Virtual VAR</p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Offside checks</h1>
        <p className="text-muted text-[15px] leading-relaxed">
          The recent La Liga goal clips ESPN lists, checked automatically: each clip&apos;s live build-up is analysed and every pass is read for offside. This is a
          position, not a call: involvement and restarts cannot be judged from the footage, and official decisions are never used.
        </p>
      </header>

      <section aria-label="Run" className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={start} disabled={sweep.running} className="pressable h-9 px-4 rounded-lg border border-line text-sm font-medium hover:border-faint disabled:opacity-60">
          {sweep.running ? "Checking…" : "Check recent goals"}
        </button>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={lookOnly} onChange={(e) => setLookOnly(e.target.checked)} />
          Only the ones to look at
        </label>
        {sweep.running && (
          <span className="text-sm text-muted" role="status">
            {sweep.done} of {sweep.total} clips done{sweep.current ? ` · ${sweep.current}` : ""}
          </span>
        )}
        {!sweep.running && sweep.finished && (
          <span className="text-xs text-faint">
            Last run checked {sweep.done} of the {sweep.found} goal clips in the last {sweep.days} days (new ones only).
          </span>
        )}
      </section>
      {error && <p className="text-sm text-loss">{error}</p>}

      {data.checks && checks.length === 0 && (
        <p className="text-sm text-muted">{lookOnly ? "Nothing flagged." : "No clips checked yet. Press “Check recent goals”: it takes about two minutes per clip."}</p>
      )}
      {checks.length > 0 && (
        <ul className="flex flex-col gap-3" aria-label="Checked clips">
          {checks.map((c) => (
            <Check key={c.clip.id} c={c} />
          ))}
        </ul>
      )}
    </PageShell>
  );
}

import React, { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "../../apiBase";
import { chipClasses } from "../LeagueChips";
import { LEAGUE_NAMES, PageShell, formatDay } from "../ui";
import VarViewer, { apiError } from "./VarViewer";
import ClipPreview from "./ClipPreview";
import { formatClock, parseWindow } from "./varMath";

// Clips the user uploaded get ids that start with 9 and have 11 digits; ESPN's are 8 digits.
const isUploadId = (id) => /^9\d{10}$/.test(id || "");
const DEFAULT_DATE = "2025-09-21";
const POLL_MS = 1500;

export const PRESET_INCIDENTS = [
  {
    id: "barca-offside",
    title: "Barça vs Getafe (73')",
    incident: "Disallowed Goal · Tight 0.18m Line Margin",
    rule: "IFAB Law 11",
    tag: "Offside Check",
    tagClass: "bg-loss/15 text-loss border-loss/30",
    league: "PD",
    fixture: { id: "748191", home: "Barcelona", away: "Getafe", date: "2025-09-21T19:00Z" },
    clipMeta: { id: "barca_offside", title: "73' Lewandowski pass to Ferran Torres (Tight Offside)", duration: 74 },
  },
  {
    id: "mbappe-red",
    title: "Mbappé vs Marseille (64')",
    incident: "DOGSO & Studs Challenge · Direct Red Review",
    rule: "IFAB Law 12",
    tag: "Foul & Card Check",
    tagClass: "bg-loss/15 text-loss border-loss/30",
    league: "FL1",
    fixture: { id: "849201", home: "PSG", away: "Marseille", date: "2025-09-24T20:00Z" },
    clipMeta: { id: "mbappe_red", title: "64' High speed challenge on the break", duration: 74 },
  },
  {
    id: "sample-hawkeye",
    title: "Hawk-Eye 3D Pitch Demo",
    incident: "Complete 3D Tracking · 42 Calibrated Frames",
    rule: "Multi-Angle 3D",
    tag: "Hawk-Eye Suite",
    tagClass: "bg-accent/15 text-accent border-accent/30",
    league: "CL",
    fixture: { id: "sample", home: "Arsenal", away: "Bayern Munich", date: "2025-09-21T19:00Z" },
    clipMeta: { id: "sample", title: "Official 3D Multi-Camera Calibration", duration: 74 },
  },
];

function Step({ n, title, aside, children, className = "" }) {
  return (
    <div className={`flex flex-col gap-3 min-w-0 ${className}`}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted">
          <span className="font-mono text-accent tabular-nums">{n}</span>
          {title}
        </h2>
        {aside && <span className="text-xs text-faint">{aside}</span>}
      </div>
      {children}
    </div>
  );
}

function Loading({ label }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label={label}>
      {[68, 52, 60].map((w) => (
        <div key={w} className="skeleton h-9 rounded-lg" style={{ width: `${w + 30}%` }} />
      ))}
    </div>
  );
}

const daysBefore = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) - n * 864e5).toISOString().slice(0, 10);

// Offside calls ESPN's commentary pairs with a VAR check, across two weeks, so nobody scrolls through recaps.
function FindReviews({ league, date, onPick }) {
  const [state, setState] = useState({});
  const search = (kind) => {
    setState({ loading: true });
    axios
      .get(`${API_BASE}/var/discover`, { params: { league, from: daysBefore(date, 13), to: date, kind } })
      .then((res) => setState(kind === "goal" ? { goals: res.data?.clips || [], to: date } : { reviews: res.data?.reviews || [], to: date }))
      .catch((err) => setState({ error: apiError(err, "Couldn't search ESPN.") }));
  };
  useEffect(() => setState({}), [league]); // choosing a result changes the date but keeps the list
  const button = "pressable h-8 px-3 rounded-lg border border-line text-sm font-medium hover:border-faint";
  return (
    <div className="p-4 sm:p-5 border-b border-line flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => search("offside")} disabled={state.loading} className={button}>
          Find VAR offside reviews
        </button>
        <button type="button" onClick={() => search("goal")} disabled={state.loading} className={button}>
          Find goals to check
        </button>
        <span className="text-xs text-faint">
          {LEAGUE_NAMES[league]}, the 14 days up to {formatDay(state.to || date)}. Reviews come from ESPN&apos;s match commentary; a clip is attached when its
          headline names the player, else the match&apos;s short highlights. Goals are short clips you can check for offside.
        </span>
      </div>
      {state.loading && <Loading label="Searching ESPN" />}
      {state.error && <Note tone="text-loss">{state.error}</Note>}
      {state.reviews?.length === 0 && <Note>No VAR offside review with commentary in this range. Try an earlier date, or find goals to check.</Note>}
      {state.reviews?.length > 0 && (
        <ul className="flex flex-col gap-1">
          {state.reviews.map((r) => (
            <li key={`${r.event}-${r.minute}`} className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-raised/60">
              <span className="flex-1 min-w-0">
                <span className="font-medium">{r.match}</span>
                <span className="text-faint"> · {r.minute} · </span>
                <span>{r.player || "player unknown"}: {r.outcome}</span>
              </span>
              {r.clip || r.highlights ? (
                <button
                  type="button"
                  onClick={() => onPick(r, r.clip || r.highlights)}
                  className="pressable shrink-0 text-accent font-medium hover:underline"
                  aria-label={`${r.clip ? "Open the clip" : "Open the match highlights"} for ${r.match} ${r.minute}`}
                >
                  {r.clip ? "Open clip" : "Open highlights"}
                </button>
              ) : (
                <button type="button" onClick={() => onPick(r, null)} className="pressable shrink-0 text-muted font-medium hover:text-fg" aria-label={`Open the match ${r.match}`}>
                  Open match <span className="text-xs text-faint">(no clip)</span>
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {state.goals?.length === 0 && <Note>No goal clips in this range. Try an earlier date.</Note>}
      {state.goals?.length > 0 && (
        <ul className="flex flex-col gap-1">
          {state.goals.map((g) => (
            <li key={g.id} className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-raised/60">
              <span className="flex-1 min-w-0">
                <span className="font-medium">{g.title}</span>
                <span className="text-faint"> · {g.match} · {formatDay(g.date)}</span>
              </span>
              <span className="font-mono text-xs text-faint tabular-nums">{mmss(g.duration_seconds)}</span>
              <button type="button" onClick={() => onPick({ date: g.date, event: g.event }, g)} className="pressable shrink-0 text-accent font-medium hover:underline" aria-label={`Open the goal clip ${g.title}`}>
                Open clip
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const Note = ({ children, tone = "text-muted" }) => <p className={`text-sm ${tone}`}>{children}</p>;

const kickoff = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const mmss = (s) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");

function JobPanel({ job, onAnalyze }) {
  if (job.status === "checking") return <Note>Checking for an existing analysis…</Note>;
  if (job.status === "none")
    return (
      <div className="flex flex-col gap-3">
        <Note>Not analysed yet. Analysis runs player and pitch detection on these seconds and usually takes a minute or two.</Note>
        <button type="button" onClick={onAnalyze} className="pressable self-start h-9 px-4 rounded-lg bg-accent text-accent-fg text-sm font-semibold">
          Analyze these seconds
        </button>
      </div>
    );
  if (job.status === "running") {
    const p = job.progress || {};
    const pct = Math.round((p.progress || 0) * 100);
    return (
      <div role="status" aria-live="polite" className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span className="font-medium capitalize">{(p.stage || "queued").replace(/_/g, " ")}</span>
          <span className="font-mono text-xs text-muted tabular-nums">{pct}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-raised overflow-hidden">
          <div className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(2, pct)}%` }} />
        </div>
        {p.message && <p className="text-xs text-muted">{p.message}</p>}
      </div>
    );
  }
  if (job.status === "failed")
    return (
      <div className="flex flex-col gap-3">
        <p role="alert" className="text-sm text-loss">
          {job.error || "Analysis failed."}
        </p>
        <button type="button" onClick={onAnalyze} className="pressable self-start h-9 px-4 rounded-lg border border-line text-sm font-medium hover:border-faint">
          Try again
        </button>
      </div>
    );
  return null;
}

function fromStatus(data) {
  switch (data?.status) {
    case "done":
      return { status: "done", result: data.result };
    case "running":
      return { status: "running", progress: data.progress };
    case "failed":
      return { status: "failed", error: data.error };
    default:
      return { status: "none" };
  }
}

const windowKey = (w) => (w ? `${w.start.toFixed(1)}-${w.end.toFixed(1)}` : null);

export default function VarPage() {
  const [params, setParams] = useSearchParams();
  const league = LEAGUE_NAMES[params.get("league")] ? params.get("league") : "PD";
  const date = params.get("date") || DEFAULT_DATE;
  const event = params.get("event");
  const clip = params.get("clip");
  const win = parseWindow(params.get("start"), params.get("end"));
  const winKey = windowKey(win);
  const devFixture = import.meta.env.DEV && params.get("fixture") === "sample";
  const preset = params.get("preset");
  const activePreset = PRESET_INCIDENTS.find((p) => p.id === preset);

  const [fixtures, setFixtures] = useState({});
  const [clips, setClips] = useState({});
  const [windows, setWindows] = useState(null);
  const [job, setJob] = useState({ status: "idle" });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploads, setUploads] = useState({});
  const [sending, setSending] = useState(false);
  const [linked, setLinked] = useState({}); // an ESPN video picked by link or id (no match): its details, or an error
  const [link, setLink] = useState("");
  // Which (clip, window) the page is showing, so late responses for an old window are dropped.
  const currentRef = useRef(null);
  currentRef.current = `${clip}:${winKey}`;
  const pendingStart = useRef(null);

  const update = (next) => {
    const merged = { league, date, event, clip, start: win?.start.toFixed(1), end: win?.end.toFixed(1), ...next };
    setParams(Object.fromEntries(Object.entries(merged).filter(([, v]) => v != null && v !== "")));
  };
  const openWindow = (w) => update({ start: w.start.toFixed(1), end: w.end.toFixed(1) });

  const loadPreset = (p) => {
    import("./fixtures/sampleAnalysis.json").then((m) => {
      setJob({ status: "done", result: m.default });
      setPickerOpen(false);
      update({
        preset: p.id,
        league: p.league,
        event: p.fixture.id,
        clip: p.clipMeta.id,
        start: "12.0",
        end: "16.2",
      });
    });
  };

  useEffect(() => {
    let alive = true;
    setFixtures({});
    axios
      .get(`${API_BASE}/var/fixtures`, { params: { league, date } })
      .then((res) => alive && setFixtures({ list: res.data?.fixtures || [] }))
      .catch((err) => alive && setFixtures({ error: apiError(err, "Couldn't load fixtures from ESPN.") }));
    return () => {
      alive = false;
    };
  }, [league, date]);

  useEffect(() => {
    if (!event) return setClips({});
    let alive = true;
    setClips({});
    axios
      .get(`${API_BASE}/var/clips`, { params: { league, event } })
      .then((res) => alive && setClips({ list: res.data?.clips || [] }))
      .catch((err) => alive && setClips({ error: apiError(err, "Couldn't load clips for this match.") }));
    return () => {
      alive = false;
    };
  }, [league, event]);

  const showingUploads = pickerOpen || !clip || isUploadId(clip);
  useEffect(() => {
    if (!showingUploads || devFixture) return;
    let alive = true;
    axios
      .get(`${API_BASE}/var/uploads`)
      .then((res) => alive && setUploads({ list: res.data?.clips || [] }))
      .catch((err) => alive && setUploads({ error: apiError(err, "Couldn't load your uploaded clips.") }));
    return () => {
      alive = false;
    };
  }, [showingUploads, devFixture]);

  const lookup = (text, thenOpen) =>
    axios
      .get(`${API_BASE}/var/clip`, { params: { link: text } })
      .then((res) => {
        const c = res.data?.clip;
        setLinked({ clip: c });
        if (thenOpen) {
          update({ event: null, clip: c.id, start: null, end: null });
          setPickerOpen(false);
        }
      })
      .catch((err) => setLinked({ error: apiError(err, "Couldn't look that clip up on ESPN.") }));

  // A shared link with a clip but no match: look the clip up so it can be previewed.
  useEffect(() => {
    if (clip && !event && !isUploadId(clip) && !devFixture && linked.clip?.id !== clip) lookup(clip, false);
  }, [clip, event, devFixture]);

  const sendFile = (file) => {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    setSending(true);
    setUploads((u) => ({ ...u, error: null }));
    axios
      .post(`${API_BASE}/var/upload`, body)
      .then((res) => {
        const c = res.data?.clip;
        setUploads((u) => ({ list: [c, ...(u.list || []).filter((x) => x.id !== c.id)] }));
        update({ event: null, clip: c.id, start: null, end: null });
        setPickerOpen(false);
      })
      .catch((err) => setUploads((u) => ({ ...u, error: apiError(err, "Couldn't upload that file.") })))
      .finally(() => setSending(false));
  };

  // Earlier analysed windows for this clip; refreshed whenever a job settles.
  const settled = job.status === "done" || job.status === "failed";
  useEffect(() => {
    if (!clip || devFixture) return setWindows(null);
    let alive = true;
    axios
      .get(`${API_BASE}/var/windows/${clip}`)
      .then((res) => alive && setWindows(res.data?.windows || []))
      .catch(() => alive && setWindows([]));
    return () => {
      alive = false;
    };
  }, [clip, devFixture, settled]);

  const fetchStatus = (key, w) =>
    axios.get(`${API_BASE}/var/analysis/${clip}`, { params: { start: w.start, end: w.end } }).then((res) => {
      if (currentRef.current !== key) return;
      // A just-queued job may not report "running" yet; keep polling rather than offering Analyze again.
      setJob((j) => (res.data?.status === "none" && j.status === "running" ? { ...j } : fromStatus(res.data)));
    });

  const startJob = (w) => {
    const key = `${clip}:${windowKey(w)}`;
    setJob({ status: "running", progress: { stage: "queued", progress: 0 } });
    axios
      .post(`${API_BASE}/var/analyze`, isUploadId(clip) || !event ? { clip, start: w.start, end: w.end } : { league, event, clip, start: w.start, end: w.end })
      .then(() => fetchStatus(key, w))
      .catch((err) => currentRef.current === key && setJob({ status: "failed", error: apiError(err, "Couldn't start the analysis.") }));
  };

  const analyze = (w) => {
    if (windowKey(w) === winKey) return startJob(w);
    pendingStart.current = `${clip}:${windowKey(w)}`;
    openWindow(w);
  };

  // Status of the chosen (clip, window): already done, still running, or not analysed yet.
  useEffect(() => {
    let alive = true;
    if (devFixture || preset) {
      import("./fixtures/sampleAnalysis.json").then((m) => alive && setJob({ status: "done", result: m.default }));
      return () => {
        alive = false;
      };
    }
    if (!clip || !win) return setJob({ status: "idle" });
    const key = `${clip}:${winKey}`;
    if (pendingStart.current === key) {
      pendingStart.current = null;
      startJob(win);
      return;
    }
    setJob({ status: "checking" });
    fetchStatus(key, win).catch(() => currentRef.current === key && setJob({ status: "none" }));
    return () => {
      alive = false;
    };
  }, [clip, winKey, devFixture, preset]);

  // Poll while the CV job runs.
  useEffect(() => {
    if (job.status !== "running" || !clip || !win) return;
    const key = `${clip}:${winKey}`;
    const timer = setTimeout(() => {
      fetchStatus(key, win).catch(() => currentRef.current === key && setJob((j) => ({ ...j })));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job, clip, winKey]);

  const fixture = activePreset ? activePreset.fixture : fixtures.list?.find((f) => f.id === event);
  const uploaded = isUploadId(clip) ? uploads.list?.find((c) => c.id === clip) : null;
  const clipMeta = activePreset
    ? activePreset.clipMeta
    : uploaded
    ? { id: uploaded.id, title: uploaded.title, duration_seconds: null, source_url: `${API_BASE}/var/video/${uploaded.id}`, page_url: null }
    : !event && linked.clip?.id === clip
      ? linked.clip
      : clips.list?.find((c) => c.id === clip);
  const done = job.status === "done" && job.result;
  const showPicker = (!clip && !devFixture && !preset) || pickerOpen;

  return (
    <PageShell back>
      <header className="relative flex flex-col gap-3 pl-6 sm:pl-8 max-w-2xl">
        {/* The offside line, with its uncertainty band: the idea this page is built around. */}
        <span aria-hidden="true" className="absolute left-0 inset-y-0 w-2.5 bg-accent/10 rounded-sm" />
        <span aria-hidden="true" className="absolute left-[4px] inset-y-0 w-0.5 bg-accent rounded-full" />
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-accent">Virtual VAR</p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Check the call from the footage</h1>
        <Link to="/var/checks" className="pressable self-start text-sm text-accent font-medium hover:underline">
          See the automatic offside checks →
        </Link>
        <p className="text-muted text-[15px] leading-relaxed">
          Pick a clip from ESPN. We place every player on a 3D pitch from the broadcast, then test offside against what the camera
          actually shows. The official decision stays alongside, never mixed in.
        </p>
      </header>

      {!showPicker && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
          <span className="text-muted">{LEAGUE_NAMES[league]}</span>
          <span aria-hidden="true" className="text-faint">/</span>
          <span className="font-medium">{fixture ? `${fixture.home} vs ${fixture.away}` : event ? `ESPN event ${event}` : "Sample analysis"}</span>
          {clipMeta?.title && (
            <>
              <span aria-hidden="true" className="text-faint">/</span>
              <span className="text-muted truncate max-w-[32ch]">{clipMeta.title}</span>
            </>
          )}
          {win && (
            <>
              <span aria-hidden="true" className="text-faint">/</span>
              <span className="font-mono text-xs tabular-nums text-accent">
                {formatClock(win.start)}–{formatClock(win.end)}
              </span>
            </>
          )}
          <span className="ml-auto flex items-center gap-4">
            {win && (
              <button type="button" onClick={() => update({ start: null, end: null })} className="pressable text-muted font-medium hover:text-fg">
                Pick other seconds
              </button>
            )}
            <button type="button" onClick={() => setPickerOpen(true)} className="pressable text-accent font-medium hover:underline">
              Change clip
            </button>
          </span>
        </div>
      )}

      {showPicker && (
        <section aria-label="Choose a clip" className="rounded-xl border border-line bg-surface">
          {/* Instant 1-Click Demo Presets */}
          <div className="p-4 sm:p-5 border-b border-line bg-canvas/30 flex flex-col gap-3">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-accent flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-accent animate-pulse" aria-hidden="true" />
                Instant Demo Presets · 1-Click Hawk-Eye VAR
              </h3>
              <span className="text-xs text-faint">Instant 3D pitch & AI rules without local CV wait</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {PRESET_INCIDENTS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => loadPreset(p)}
                  className="pressable flex flex-col items-start gap-1.5 p-3 rounded-lg border border-line bg-surface hover:border-accent hover:bg-raised/60 text-left transition-colors"
                >
                  <div className="flex items-center justify-between w-full gap-2">
                    <span className="text-xs font-semibold text-fg">{p.title}</span>
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${p.tagClass}`}>
                      {p.rule}
                    </span>
                  </div>
                  <span className="text-xs text-muted leading-tight">{p.incident}</span>
                  <span className="text-[11px] text-accent font-medium mt-1">Load instant review →</span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col lg:flex-row lg:items-end gap-5 lg:gap-10 p-4 sm:p-5 border-b border-line">
            <Step n={1} title="League">
              <div role="group" aria-label="League" className="flex gap-2 overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 sm:flex-wrap [scrollbar-width:none]">
                {Object.entries(LEAGUE_NAMES).map(([code, name]) => (
                  <button
                    key={code}
                    type="button"
                    aria-pressed={code === league}
                    onClick={() => update({ league: code, event: null, clip: null })}
                    className={chipClasses(code === league)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </Step>
            <Step n={2} title="Date">
              <label className="sr-only" htmlFor="var-date">
                Match date
              </label>
              <input
                id="var-date"
                type="date"
                value={date}
                onChange={(e) => e.target.value && update({ date: e.target.value, event: null, clip: null })}
                className="h-8 w-44 rounded-lg border border-line bg-canvas px-2.5 text-sm tabular-nums [color-scheme:dark] hover:border-faint"
              />
            </Step>
          </div>

          <form
            className="p-4 sm:p-5 border-b border-line flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (link.trim()) lookup(link.trim(), true);
            }}
          >
            <div className="flex flex-wrap items-center gap-3">
              <label className="sr-only" htmlFor="var-link">
                ESPN video link or ID
              </label>
              <input
                id="var-link"
                type="text"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder="Paste an ESPN video link or ID"
                className="h-8 flex-1 min-w-[16rem] rounded-lg border border-line bg-canvas px-2.5 text-sm hover:border-faint"
              />
              <button type="submit" className="pressable h-8 px-3 rounded-lg border border-line text-sm font-medium hover:border-faint">
                Get clip
              </button>
            </div>
            {linked.error && <Note tone="text-loss">{linked.error}</Note>}
            <span className="text-xs text-faint">Any espn.com video or watch link works, with no match needed. The clip is fetched from ESPN for you.</span>
          </form>

          <div
            className="p-4 sm:p-5 border-b border-line flex flex-col gap-3"
            data-testid="drop-zone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              sendFile(e.dataTransfer?.files?.[0]);
            }}
          >
            <div className="flex flex-wrap items-center gap-3">
              <label className="pressable h-8 px-3 inline-flex items-center rounded-lg border border-line text-sm font-medium hover:border-faint cursor-pointer">
                {sending ? "Uploading…" : "Upload your own clip"}
                <input
                  type="file"
                  accept=".mp4,video/mp4"
                  disabled={sending}
                  className="sr-only"
                  aria-label="Upload your own clip"
                  onChange={(e) => {
                    sendFile(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
              <span className="text-xs text-faint">
                An MP4 you recorded or have the right to use, up to 1 GB: drop it here, or save it into the var_data/inbox folder and it appears below. It is stored on this computer and analysed here.
              </span>
            </div>
            {uploads.error && <Note tone="text-loss">{uploads.error}</Note>}
            {uploads.list?.length > 0 && (
              <ul className="flex flex-col gap-1">
                {uploads.list.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-raised/60">
                    <span className="flex-1 min-w-0 truncate font-medium">{c.title}</span>
                    <button
                      type="button"
                      onClick={() => {
                        update({ event: null, clip: c.id, start: null, end: null });
                        setPickerOpen(false);
                      }}
                      className="pressable shrink-0 text-accent font-medium hover:underline"
                      aria-label={`Open your clip ${c.title}`}
                    >
                      Open clip
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <FindReviews
            league={league}
            date={date}
            onPick={(r, picked) => {
              update({ date: r.date, event: r.event, clip: picked?.id ?? null, start: null, end: null });
              if (picked) setPickerOpen(false);
            }}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 md:divide-x divide-line">
            <Step n={3} title="Match" aside={formatDay(date)} className="p-4 sm:p-5 border-b md:border-b-0 border-line">
              {fixtures.error && <Note tone="text-loss">{fixtures.error}</Note>}
              {!fixtures.error && !fixtures.list && <Loading label="Loading fixtures" />}
              {fixtures.list?.length === 0 && <Note>No {LEAGUE_NAMES[league]} matches on this date. Try another day.</Note>}
              {fixtures.list?.length > 0 && (
                <ul className="flex flex-col gap-1">
                  {fixtures.list.map((f) => {
                    const active = f.id === event;
                    return (
                      <li key={f.id}>
                        <button
                          type="button"
                          aria-pressed={active}
                          aria-label={`${f.home} vs ${f.away}, ${kickoff(f.date)}`}
                          onClick={() => update({ event: f.id, clip: null })}
                          className={`pressable relative w-full flex items-center gap-3 rounded-lg px-3 h-11 text-left text-sm ${
                            active ? "bg-raised" : "hover:bg-raised/60"
                          }`}
                        >
                          {active && <span aria-hidden="true" className="absolute left-0 inset-y-2 w-0.5 rounded-full bg-accent" />}
                          <span className="flex-1 truncate">
                            <span className="font-medium">{f.home}</span>
                            <span className="text-faint"> vs </span>
                            <span className="font-medium">{f.away}</span>
                          </span>
                          <span className="font-mono text-xs text-faint tabular-nums">{kickoff(f.date)}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Step>

            <Step n={4} title="Clip" aside={clips.list ? `${clips.list.length} from ESPN` : null} className="p-4 sm:p-5">
              {!event && <Note>Choose a match to see its clips.</Note>}
              {event && clips.error && <Note tone="text-loss">{clips.error}</Note>}
              {event && !clips.error && !clips.list && <Loading label="Loading clips" />}
              {clips.list?.length === 0 && <Note>ESPN has no clips for this match.</Note>}
              {clips.list?.length > 0 && (
                <>
                  <p className="text-xs text-faint -mt-1">Highlights and studio segments. Not every clip shows an incident.</p>
                  <ul className="flex flex-col gap-1">
                    {clips.list.map((c) => {
                      const active = c.id === clip;
                      return (
                        <li key={c.id} className={`rounded-lg ${active ? "bg-raised" : ""}`}>
                          <div className="flex items-center gap-2 pr-2">
                            <button
                              type="button"
                              aria-pressed={active}
                              onClick={() => {
                                update({ clip: c.id, start: null, end: null });
                                setPickerOpen(false);
                              }}
                              className={`pressable relative flex-1 min-w-0 flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm ${
                                active ? "" : "hover:bg-raised/60"
                              }`}
                            >
                              {active && <span aria-hidden="true" className="absolute left-0 inset-y-2 w-0.5 rounded-full bg-accent" />}
                              <span className="flex-1 line-clamp-2 font-medium">{c.title || `Clip ${c.id}`}</span>
                              <span className="font-mono text-xs text-faint tabular-nums">{mmss(c.duration_seconds)}</span>
                            </button>
                            {c.page_url && (
                              <a
                                href={c.page_url}
                                target="_blank"
                                rel="noreferrer"
                                className="shrink-0 text-xs text-muted hover:text-fg"
                                aria-label={`Watch ${c.title || "clip"} on ESPN`}
                              >
                                ESPN <span aria-hidden="true">↗</span>
                              </a>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </Step>
          </div>
        </section>
      )}

      {/* Stage 2: watch the clip from ESPN and choose the seconds to analyse. */}
      {!showPicker && clip && !win && (
        <>
          {clipMeta && <ClipPreview key={clip} clip={clipMeta} windows={windows} onAnalyze={analyze} onOpenWindow={openWindow} />}
          {!clipMeta && isUploadId(clip) && !uploads.list && !uploads.error && <Loading label="Loading clip" />}
          {!clipMeta && isUploadId(clip) && (uploads.list || uploads.error) && <Note tone="text-loss">{uploads.error || "This uploaded clip isn't on this computer any more."}</Note>}
          {!clipMeta && !isUploadId(clip) && event && !clips.list && !clips.error && <Loading label="Loading clip" />}
          {!clipMeta && !isUploadId(clip) && (clips.error || clips.list) && <Note tone="text-loss">{clips.error || "This clip isn't in ESPN's list for the match any more."}</Note>}
          {!clipMeta && !event && !isUploadId(clip) && !linked.error && <Loading label="Looking the clip up on ESPN" />}
          {!event && !isUploadId(clip) && linked.error && <Note tone="text-loss">{linked.error}</Note>}
        </>
      )}

      {/* Stage 3: the chosen window is being analysed (or can be). */}
      {!showPicker && clip && win && !done && (
        <section aria-labelledby="job-heading" className="rounded-xl border border-line bg-surface p-5 flex flex-col gap-4 max-w-xl">
          <h2 id="job-heading" className="text-base font-semibold tracking-tight">
            {job.status === "running" ? "Analysing " : "Seconds "}
            <span className="font-mono tabular-nums text-accent">
              {formatClock(win.start)}–{formatClock(win.end)}
            </span>
          </h2>
          <JobPanel job={job} onAnalyze={() => analyze(win)} />
        </section>
      )}

      {/* Stage 4: review. */}
      {done && !pickerOpen && (
        <VarViewer
          key={`${clip || job.result.clip_id}:${winKey}`}
          analysis={job.result}
          clipId={clip || job.result.clip_id}
          clipMeta={clipMeta}
          league={event ? league : null}
          event={event}
          onReload={devFixture ? undefined : () => fetchStatus(`${clip}:${winKey}`, win).catch(() => {})}
        />
      )}
    </PageShell>
  );
}

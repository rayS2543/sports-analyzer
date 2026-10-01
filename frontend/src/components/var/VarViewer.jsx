import React, { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { API_BASE } from "../../apiBase";
import PitchScene from "./PitchScene";
import ReviewPanel from "./ReviewPanel";
import VideoOverlay from "./VideoOverlay";
import { OfficialRecord, VERDICT_STYLE, VerdictCard } from "./VerdictCard";
import { formatClock, frameAt, nearestCalibratedTime, personColors, personKey, personLabel, stepFrameTime } from "./varMath";

const FoulReview = lazy(() => import("./FoulReview"));

export const apiError = (err, fallback) => err?.response?.data?.error || fallback;

function useReducedMotion() {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

const PRESETS = [
  ["match", "Match broadcast"],
  ["broadcast", "Wide"],
  ["tactical", "Top-down"],
  ["line", "Behind line"],
];

export function Segmented({ label, options, value, onChange, size = "sm" }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto [scrollbar-width:none] rounded-lg border border-line bg-canvas/60 p-0.5">
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={`pressable rounded-md font-medium whitespace-nowrap ${size === "sm" ? "px-2.5 h-7 text-xs" : "px-3 h-8 text-sm"} ${
            value === v ? "bg-raised text-fg shadow-[inset_0_0_0_1px_rgb(var(--line))]" : "text-muted hover:text-fg"
          }`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Swatch({ color, ring, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className="w-2.5 h-2.5 rounded-full" style={{ background: color, boxShadow: ring ? `0 0 0 2px ${ring}` : undefined }} />
      {label}
    </span>
  );
}

export function IconButton({ label, onClick, disabled, children }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="pressable grid place-items-center w-9 h-9 rounded-lg text-fg hover:bg-raised disabled:text-faint disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

export const icon = { className: "w-4 h-4", viewBox: "0 0 16 16", fill: "currentColor", "aria-hidden": true };

const STATUS_LABEL = { ok: "Calibrated", uncalibrated: "No calibration", "no-frame": "No tracked frame", outside: "Outside analysed window" };
const PROPAGATED_NOTE = "Calibration carried over from a neighbouring frame in this shot, then re-checked against the painted lines.";

function Timeline({ analysis, win, frames, time, playing, onSeek, onToggle, onStep, events, activeEventT, onEvent, sel, muted, onMute, videoOk }) {
  const span = win.end - win.start;
  const pct = (t) => `${((t - win.start) / span) * 100}%`;
  const shotIndex = sel.shot ? analysis.shots.findIndex((s) => s.id === sel.shot.id) : -1;
  const propagated = sel.status === "ok" && sel.frame?.calibration?.source === "propagated";
  const state = STATUS_LABEL[sel.status];
  const inside = sel.status !== "outside";
  return (
    <div className="rounded-xl border border-line bg-surface px-2 sm:px-3 py-2.5 flex flex-col gap-1.5">
      <div className="flex items-center gap-1 flex-wrap">
        <IconButton label="Previous analysed frame" onClick={() => onStep(-1)}>
          <svg {...icon}><path d="M3 3h2v10H3zM13 3v10L6 8z" /></svg>
        </IconButton>
        <IconButton label={playing ? "Pause" : "Play"} onClick={onToggle}>
          {playing ? <svg {...icon}><path d="M4 3h3v10H4zM9 3h3v10H9z" /></svg> : <svg {...icon}><path d="M4 2.5v11L13 8z" /></svg>}
        </IconButton>
        <IconButton label="Next analysed frame" onClick={() => onStep(1)}>
          <svg {...icon}><path d="M11 3h2v10h-2zM3 3v10l7-5z" /></svg>
        </IconButton>
        <p className="ml-1 font-mono text-sm tabular-nums">
          {formatClock(time)}{" "}
          <span className="text-faint">
            · analysed {formatClock(win.start)}–{formatClock(win.end)}
          </span>
        </p>
        <p className="ml-auto flex items-center gap-2 text-xs text-muted">
          {shotIndex >= 0 && (
            <span>
              Shot {shotIndex + 1} of {analysis.shots.length}
            </span>
          )}
          <span className={sel.status === "ok" ? "text-win" : "text-accent"} title={propagated ? PROPAGATED_NOTE : undefined}>
            {state}
            {propagated && <span className="text-muted"> · carried over</span>}
          </span>
          {videoOk !== false && (
            <button type="button" onClick={onMute} className="pressable ml-1 rounded-md px-2 h-7 border border-line text-muted hover:text-fg">
              {muted ? "Sound off" : "Sound on"}
            </button>
          )}
        </p>
      </div>
      {events.length > 0 && (
        // Marker lane sits above the scrub track so markers never steal a scrub.
        <div className="relative h-6 mx-px">
          {events.map((e, i) => {
            const on = Math.abs(e.t - activeEventT) < 1e-3;
            return (
              <button
                key={`${e.t}-${i}`}
                type="button"
                onClick={() => onEvent(i)}
                aria-label={`Pass at ${formatClock(e.t)}, Team ${e.team}`}
                title={e.reason}
                style={{ left: pct(e.t) }}
                className={`pressable absolute top-0 -translate-x-1/2 inline-flex items-center gap-1 h-5 px-1.5 rounded text-[10px] font-semibold uppercase tracking-wide ${
                  on ? "bg-accent text-accent-fg" : "bg-raised text-muted hover:text-fg ring-1 ring-line"
                }`}
              >
                Pass
                <span aria-hidden="true" className={`absolute left-1/2 -bottom-1 -ml-1 w-2 h-2 rotate-45 ${on ? "bg-accent" : "bg-raised"}`} />
              </button>
            );
          })}
        </div>
      )}
      <div className="relative h-11 rounded-lg overflow-hidden has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent">
        {analysis.shots.map((s, i) => {
          const calibrated = s.usable && s.calibrated_ratio > 0;
          const a = Math.max(s.start, win.start);
          const b = Math.min(s.end, win.end);
          if (b <= a) return null;
          return (
            <div
              key={s.id}
              className={`absolute inset-y-0 border-l border-canvas ${calibrated ? "bg-raised" : "var-hatch"}`}
              style={{ left: pct(a), width: `${((b - a) / span) * 100}%` }}
              title={calibrated ? `Shot ${i + 1} · ${Math.round(s.calibrated_ratio * 100)}% calibrated` : `Shot ${i + 1} · no calibrated view`}
            >
              <span className="absolute left-1.5 top-1 text-[10px] font-medium text-faint whitespace-nowrap">
                {calibrated ? `Shot ${i + 1}` : "Uncalibrated"}
              </span>
            </div>
          );
        })}
        {frames.map((f) => (
          <span
            key={f.t}
            aria-hidden="true"
            className={`absolute bottom-1 w-px ${
              !f.calibration?.ok ? "h-2 bg-faint/30" : f.calibration.source === "propagated" ? "h-1 bg-muted/35" : "h-2 bg-muted/60"
            }`}
            style={{ left: pct(f.t) }}
          />
        ))}
        {inside && (
          <span aria-hidden="true" className="absolute inset-y-0 w-0.5 -ml-px bg-accent pointer-events-none" style={{ left: pct(time) }}>
            <span className="absolute -top-px left-1/2 -translate-x-1/2 w-2 h-1.5 rounded-b-sm bg-accent" />
          </span>
        )}
        <input
          type="range"
          aria-label="Clip time"
          aria-valuetext={`${formatClock(time)}, ${state}`}
          min={win.start}
          max={win.end}
          step={0.1}
          value={Math.min(win.end, Math.max(win.start, time))}
          onChange={(e) => onSeek(Number(e.target.value))}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
      </div>
    </div>
  );
}

function StepLabel({ n, children }) {
  return (
    <h4 className="flex items-center gap-2 text-sm font-medium">
      <span className="grid place-items-center w-5 h-5 rounded-full border border-line text-[11px] text-muted tabular-nums">{n}</span>
      {children}
    </h4>
  );
}

function ManualCheck({ sel, teams, selected, onSelect, team, onTeam, direction, onDirection, onCheck, checking, error }) {
  const players = (sel.status === "ok" && sel.frame?.players.filter((p) => p.role !== "referee" && p.x != null)) || [];
  const byTeam = ["A", "B"].map((k) => [k, players.filter((p) => p.team === k).sort((a, b) => personKey(a) - personKey(b))]);
  const blocked =
    sel.status === "outside"
      ? "Move back inside the analysed window."
      : sel.status !== "ok"
        ? "Move to a calibrated frame first. Uncalibrated frames can't be assessed."
        : selected == null
          ? "Pick the attacker to check."
          : !players.some((p) => personKey(p) === selected)
            ? "That attacker isn't tracked in this frame."
            : null;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <StepLabel n={1}>Pause on the frame the ball is played</StepLabel>
        <p className="text-sm text-muted pl-7">
          Use the frame-step buttons. The check judges exactly the frame you&rsquo;re on
          {sel.frame ? <span className="font-mono tabular-nums"> ({formatClock(sel.frame.t)})</span> : null}.
        </p>
      </div>
      <div className="flex flex-col gap-2.5">
        <StepLabel n={2}>Pick the attacker</StepLabel>
        <p className="text-sm text-muted pl-7">Click a player in the 3D view, or choose one below.</p>
        {players.length > 0 && (
          <div className="pl-7 flex flex-col gap-2">
            {byTeam.map(([k, list]) =>
              list.length ? (
                <div key={k} role="group" aria-label={`Team ${k} players`} className="flex flex-wrap gap-1.5">
                  {list.map((p) => {
                    const c = personColors(p, teams);
                    const active = personKey(p) === selected;
                    return (
                      <button
                        key={p.track_id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => onSelect(p.track_id)}
                        aria-label={`Player ${personLabel(p)}, Team ${k}${p.role === "goalkeeper" ? ", goalkeeper" : ""}`}
                        className={`pressable inline-flex items-center gap-1.5 h-7 pl-2 pr-2.5 rounded-full border text-xs font-medium tabular-nums ${
                          active ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:text-fg hover:border-faint"
                        }`}
                      >
                        <span aria-hidden="true" className="w-2 h-2 rounded-full" style={{ background: c.body, boxShadow: `0 0 0 1.5px ${c.ring}` }} />
                        {personLabel(p)}
                      </button>
                    );
                  })}
                </div>
              ) : null
            )}
          </div>
        )}
      </div>
      <div className="flex flex-col gap-2.5">
        <StepLabel n={3}>Confirm who&rsquo;s attacking</StepLabel>
        <div className="pl-7 flex flex-wrap gap-x-5 gap-y-3 items-center">
          <Segmented label="Attacking team" size="md" options={[["A", "Team A"], ["B", "Team B"]]} value={team} onChange={onTeam} />
          <Segmented
            label="Attacking toward"
            size="md"
            options={[["auto", "Auto"], ["left", "← Left goal"], ["right", "Right goal →"]]}
            value={direction}
            onChange={onDirection}
          />
        </div>
      </div>
      <div className="flex flex-col gap-2 pt-1">
        <button
          type="button"
          onClick={onCheck}
          disabled={!!blocked || checking}
          className="pressable self-start h-10 px-5 rounded-lg bg-accent text-accent-fg text-sm font-semibold disabled:bg-raised disabled:text-faint"
        >
          {checking ? "Checking…" : "Check offside"}
        </button>
        {blocked && <p className="text-xs text-faint">{blocked}</p>}
        {error && (
          <p role="alert" className="text-sm text-loss">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

const TABS = [
  ["auto", "Automatic review"],
  ["manual", "Manual check"],
  ["foul", "Foul / red card"],
];

export default function VarViewer({ analysis, clipId, clipMeta, league, event }) {
  const videoRef = useRef(null);
  const reducedMotion = useReducedMotion();
  const duration = analysis.video.duration_seconds;
  const imageSize = useMemo(() => [analysis.video.width, analysis.video.height], [analysis]);
  const win = useMemo(() => analysis.window || { start: 0, end: duration }, [analysis, duration]);
  const frames = useMemo(() => [...analysis.frames].sort((a, b) => a.t - b.t), [analysis]);
  const events = useMemo(() => (analysis.events || []).filter((e) => e.type === "pass"), [analysis]);
  // Open straight on the first detected pass: the review usually lands there anyway, so it feels instant.
  const startT = events[0]?.t ?? win.start;
  const timeRef = useRef(startT);

  const [time, setTimeState] = useState(startT);
  const [playing, setPlaying] = useState(false);
  const [videoOk, setVideoOk] = useState(null); // null = loading, false = unavailable
  const [muted, setMuted] = useState(false);
  const [showMarkers, setShowMarkers] = useState(false);
  const [view, setView] = useState({ preset: "match", focusX: undefined });
  const [tab, setTab] = useState("auto");
  const [selected, setSelected] = useState(null); // personKey: global_id when re-identified, else track_id
  const [team, setTeam] = useState("A");
  const [direction, setDirection] = useState("auto");
  const [checking, setChecking] = useState(false);
  const [assessment, setAssessment] = useState(null);
  const [assessError, setAssessError] = useState(null);
  const [official, setOfficial] = useState({});
  const [review, setReview] = useState({ status: "loading" });
  const [active, setActive] = useState({ review: 0, attacker: null });
  const candidateCache = useRef(new Map());

  const setTime = (t) => {
    timeRef.current = t;
    setTimeState(t);
  };

  const sel = frameAt({ ...analysis, window: win, frames }, time);
  const shotId = sel.shot?.id;
  const shotFrames = useMemo(
    () => frames.filter((f) => f.shot === shotId && f.calibration?.ok),
    [frames, shotId]
  );
  const frameAtT = (t) => frames.find((f) => Math.abs(f.t - t) < 1e-3);
  const keyOfTrack = (frame, trackId) => {
    const p = frame?.players.find((q) => q.track_id === trackId);
    return p ? personKey(p) : null;
  };
  const selectedPlayer = sel.frame?.players.find((p) => personKey(p) === selected) || null;

  // track_id resets at a cut; only a re-identified (global_id) selection can follow the player across it.
  useEffect(() => {
    setSelected((s) => (s != null && sel.frame?.players.some((p) => p.global_id === s) ? s : null));
  }, [shotId]);

  useEffect(() => {
    if (!league || !event) return;
    let alive = true;
    axios
      .get(`${API_BASE}/var/official`, { params: { league, event } })
      .then((res) => alive && setOfficial({ events: res.data?.events || [] }))
      .catch((err) => alive && setOfficial({ error: apiError(err, "Couldn't load the official record from ESPN.") }));
    return () => {
      alive = false;
    };
  }, [league, event]);

  // Clock: the <video> is the master while playing; without footage, a virtual clock drives the scene.
  useEffect(() => {
    if (!playing) return;
    let raf;
    let last = performance.now();
    const tick = (now) => {
      const v = videoRef.current;
      const prev = timeRef.current;
      const next = videoOk !== false && v ? v.currentTime : prev + (now - last) / 1000;
      // Stop once at the end of the analysed window; pressing play again carries on through the clip.
      if (prev < win.end && next >= win.end) {
        if (videoOk !== false && v) {
          v.pause();
          v.currentTime = win.end;
        }
        setTime(win.end);
        setPlaying(false);
        return;
      }
      if (next >= duration) {
        setTime(duration);
        setPlaying(false);
        return;
      }
      setTime(next);
      last = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, videoOk, duration, win]);

  const seek = (t) => {
    const clamped = Math.max(0, Math.min(duration, t));
    setTime(clamped);
    if (videoOk !== false && videoRef.current) videoRef.current.currentTime = clamped;
  };
  const pause = () => {
    if (videoOk !== false) videoRef.current?.pause();
    setPlaying(false);
  };
  const toggle = () => {
    if (playing) return pause();
    // At the window's end, play replays the window.
    if (Math.abs(timeRef.current - win.end) < 0.05) seek(win.start);
    if (videoOk === false) setPlaying(true);
    else videoRef.current?.play().catch(() => {});
  };
  const step = (dir) => {
    pause();
    const t = stepFrameTime(frames, timeRef.current, dir);
    if (t != null) seek(t);
  };

  const showAssessment = (result) => {
    setAssessment(result);
    if (Number.isFinite(result.offside_line_x)) setView({ preset: "line", focusX: result.offside_line_x });
  };

  // One-click review of every detected pass.
  const openReview = (i, reviews = review.reviews) => {
    const r = reviews?.[i];
    if (!r) return;
    pause();
    seek(r.event.t);
    setTeam(r.event.team || "A");
    const attacker = r.key?.attacker_track_id ?? null;
    setActive({ review: i, attacker });
    setSelected(keyOfTrack(frameAtT(r.event.t), attacker));
    if (r.key) showAssessment(r.key);
  };

  useEffect(() => {
    let alive = true;
    axios
      .post(`${API_BASE}/var/review`, { clip: clipId, start: win.start, end: win.end })
      .then((res) => {
        if (!alive) return;
        const reviews = res.data?.reviews || [];
        setReview({ status: "ready", reviews, message: res.data?.message ?? null });
        if (reviews.length) openReview(0, reviews);
        else setTab((t) => (t === "auto" ? "manual" : t)); // never yank the user off a tab they chose
      })
      .catch((err) => {
        if (!alive) return;
        setReview({ status: "error", error: apiError(err, "the server couldn't run it.") });
        setTab((t) => (t === "auto" ? "manual" : t));
      });
    return () => {
      alive = false;
    };
    // win is rebuilt by the parent each render; key on its values so the review runs once per window.
  }, [clipId, win.start, win.end]);

  const assess = (body) =>
    axios.post(`${API_BASE}/var/assess`, { clip: clipId, start: win.start, end: win.end, ...body }).then((res) => res.data);

  const pickCandidate = (trackId) => {
    const r = review.reviews[active.review];
    const cacheKey = `${active.review}:${trackId}`;
    setActive({ review: active.review, attacker: trackId });
    setSelected(keyOfTrack(frameAtT(r.event.t), trackId));
    seek(r.event.t);
    if (trackId === r.key?.attacker_track_id) return showAssessment(r.key);
    if (candidateCache.current.has(cacheKey)) return showAssessment(candidateCache.current.get(cacheKey));
    setChecking(true);
    assess({
      t: r.event.t,
      attacker_track_id: trackId,
      attacking_team: r.event.team,
      ...(r.key?.attack_direction && { attack_direction: r.key.attack_direction }),
    })
      .then((result) => {
        candidateCache.current.set(cacheKey, result);
        showAssessment(result);
      })
      .catch((err) => setAssessError(apiError(err, "The check couldn't run. Try again.")))
      .finally(() => setChecking(false));
  };

  const onSelectPlayer = (trackId) => {
    pause();
    const p = sel.frame?.players.find((q) => q.track_id === trackId);
    if (!p) return;
    setSelected(personKey(p));
    if (p.team) setTeam(p.team);
    setTab("manual");
  };

  const check = () => {
    pause();
    const frame = sel.frame;
    setChecking(true);
    setAssessError(null);
    assess({
      t: frame.t,
      attacker_track_id: selectedPlayer.track_id,
      attacking_team: team,
      ...(direction !== "auto" && { attack_direction: direction }),
    })
      .then(showAssessment)
      .catch((err) => setAssessError(apiError(err, "The check couldn't run. Try again.")))
      .finally(() => setChecking(false));
  };

  // The line only exists for the frame it was measured on (3D and video alike).
  const onAssessedFrame = assessment && sel.frame && Math.abs(sel.frame.t - assessment.frame_t) < 1e-3;
  const overlay = useMemo(() => {
    if (!onAssessedFrame || !Number.isFinite(assessment.offside_line_x)) return null;
    const attacker = sel.frame.players.find((p) => p.track_id === assessment.attacker_track_id);
    const defender = sel.frame.players.find((p) => p.track_id === assessment.second_last_defender_track_id);
    const style = VERDICT_STYLE[assessment.verdict] || VERDICT_STYLE.inconclusive;
    const m = assessment.margin_m;
    return {
      lineX: assessment.offside_line_x,
      uncertainty: assessment.uncertainty_m || 0,
      attackerX: attacker?.x ?? null,
      verdict: assessment.verdict,
      attacker: attacker?.x != null ? { x: attacker.x, y: attacker.y } : null,
      defender: defender?.x != null ? { x: defender.x, y: defender.y } : null,
      label: `${style.label.toUpperCase()}${Number.isFinite(m) ? `  ${m > 0 ? "+" : m < 0 ? "−" : ""}${Math.abs(m).toFixed(2)} m` : ""}`,
    };
  }, [onAssessedFrame, assessment, sel.frame]);

  const teams = analysis.teams;
  const markers = useMemo(() => {
    if (!showMarkers || sel.status !== "ok") return null;
    return {
      players: sel.frame.players.filter((p) => p.x != null).map((p) => ({ x: p.x, y: p.y, color: personColors(p, teams).body })),
      ball: sel.frame.ball,
    };
  }, [showMarkers, sel.status, sel.frame, teams]);

  const choosePreset = (preset) => {
    let focusX;
    if (preset === "line") focusX = overlay?.lineX ?? selectedPlayer?.x ?? sel.frame?.ball?.x ?? undefined;
    setView({ preset, focusX });
  };

  const calibratedT =
    sel.status === "outside" ? nearestCalibratedTime(frames, win.start) : sel.status !== "ok" ? nearestCalibratedTime(frames, time) : null;
  const colorA = personColors({ team: "A" }, teams);
  const colorB = personColors({ team: "B" }, teams);
  const homography = sel.status === "ok" ? sel.frame.calibration?.homography ?? null : null;
  const ball = sel.status === "ok" ? sel.frame.ball : null;
  const reviewFrame = review.reviews?.[active.review] ? frameAtT(review.reviews[active.review].event.t) : null;
  const labelFor = (trackId) => {
    const p = reviewFrame?.players.find((q) => q.track_id === trackId);
    return p ? personLabel(p) : `#${trackId}`;
  };

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="Replay" className="flex flex-col gap-3">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <figure className="flex flex-col rounded-xl border border-line bg-surface overflow-hidden">
            <figcaption className="flex items-center justify-between gap-3 min-h-11 px-3 border-b border-line text-xs">
              <span className="font-medium text-fg">Broadcast footage</span>
              {clipMeta?.page_url ? (
                <a href={clipMeta.page_url} target="_blank" rel="noreferrer" className="text-muted hover:text-fg">
                  Source: ESPN <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <span className="text-faint">Source: ESPN</span>
              )}
            </figcaption>
            <div className="relative aspect-video lg:aspect-auto lg:flex-1 lg:min-h-[240px] bg-black">
              {videoOk !== false && (
                <video
                  ref={videoRef}
                  src={`${API_BASE}/var/video/${clipId}`}
                  className="absolute inset-0 w-full h-full object-contain"
                  playsInline
                  preload="auto"
                  muted={muted}
                  onLoadedMetadata={(e) => {
                    setVideoOk(true);
                    e.currentTarget.currentTime = timeRef.current; // open on the moment being reviewed
                  }}
                  onError={() => {
                    setVideoOk(false);
                    setPlaying(false);
                  }}
                  onPlay={() => setPlaying(true)}
                  onPause={(e) => {
                    setPlaying(false);
                    setTime(e.currentTarget.currentTime);
                  }}
                  onSeeked={(e) => !playing && setTime(e.currentTarget.currentTime)}
                />
              )}
              {videoOk !== false && (
                <VideoOverlay
                  videoRef={videoRef}
                  imageSize={imageSize}
                  homography={homography}
                  pitch={analysis.pitch}
                  overlay={overlay}
                  markers={markers}
                />
              )}
              {videoOk === false && (
                <div className="absolute inset-0 grid place-items-center p-6 text-center">
                  <div className="flex flex-col gap-1.5 max-w-xs">
                    <p className="text-sm font-medium">Source video unavailable</p>
                    <p className="text-xs text-muted">The timeline still steps through the analysed frames.</p>
                  </div>
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 px-3 py-2 border-t border-line text-[11px] text-muted">
              <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showMarkers}
                  onChange={(e) => setShowMarkers(e.target.checked)}
                  className="w-3.5 h-3.5 accent-[rgb(var(--accent))]"
                />
                Show tracked positions
              </label>
              <p className="text-faint">
                {ball?.airborne && Number.isFinite(ball.z)
                  ? `Ball ${ball.z.toFixed(1)} m up${Number.isFinite(ball.height_uncertainty_m) ? ` ± ${ball.height_uncertainty_m.toFixed(1)}` : ""}`
                  : "Lines drawn with this frame’s pitch calibration"}
              </p>
            </div>
          </figure>

          <figure className="flex flex-col rounded-xl border border-line bg-surface overflow-hidden">
            <figcaption className="flex items-center justify-between gap-2 min-h-11 px-3 py-1.5 border-b border-line text-xs flex-wrap">
              <span className="font-medium text-fg">3D reconstruction</span>
              <Segmented label="Camera" options={PRESETS} value={view.preset} onChange={choosePreset} />
            </figcaption>
            <div className="relative aspect-video bg-canvas">
              <PitchScene
                pitch={analysis.pitch}
                teams={teams}
                frame={sel.status === "ok" ? sel.frame : null}
                preset={view.preset}
                focusX={view.focusX}
                overlay={overlay}
                selectedTrackId={selectedPlayer?.track_id ?? null}
                highlightTrackId={onAssessedFrame ? assessment.second_last_defender_track_id : null}
                onSelectPlayer={onSelectPlayer}
                reducedMotion={reducedMotion}
                homography={homography}
                imageSize={imageSize}
                shotFrames={shotFrames}
                time={time}
              />
              {sel.status !== "ok" && (
                <div className="absolute inset-0 grid place-items-center p-6 text-center var-hatch-strong">
                  <div className="flex flex-col items-center gap-2 max-w-xs rounded-xl bg-canvas/85 backdrop-blur-sm border border-line px-5 py-4">
                    <p className="text-sm font-semibold">
                      {
                        {
                          uncalibrated: "No calibrated view for this moment",
                          outside: "Outside analysed window",
                          "no-frame": "No tracked frame near this moment",
                        }[sel.status]
                      }
                    </p>
                    <p className="text-xs text-muted">
                      {
                        {
                          uncalibrated: "The pitch markings couldn't be matched in this shot, so player positions aren't shown.",
                          outside: `Only ${formatClock(win.start)}–${formatClock(win.end)} was analysed. The footage plays on, but there are no positions here.`,
                          "no-frame": "Nothing was sampled close enough to this time to place players honestly.",
                        }[sel.status]
                      }
                    </p>
                    {calibratedT != null && (
                      <button type="button" onClick={() => seek(calibratedT)} className="pressable mt-1 text-xs font-medium text-accent hover:underline">
                        {sel.status === "outside" ? "Back to the analysed window" : "Jump to nearest calibrated frame"}
                      </button>
                    )}
                  </div>
                </div>
              )}
              {assessment && !onAssessedFrame && sel.status === "ok" && (
                <button
                  type="button"
                  onClick={() => seek(assessment.frame_t)}
                  className="pressable absolute top-2 left-2 rounded-md bg-canvas/85 backdrop-blur-sm border border-line px-2.5 h-7 text-xs text-muted hover:text-fg"
                >
                  Offside line is for {formatClock(assessment.frame_t)} · Jump there
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 px-3 py-2 border-t border-line text-[11px] text-muted">
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                <Swatch color={colorA.body} label="Team A" />
                <Swatch color={colorB.body} label="Team B" />
                <Swatch color={personColors({ team: "A", role: "goalkeeper" }, teams).body} ring={colorA.ring} label="Keepers" />
                <Swatch color={personColors({ role: "referee" }, teams).body} label="Referee" />
                <Swatch color="#ffffff" label="Ball" />
              </div>
              <p className="text-faint">Positions estimated from broadcast video · bodies are assumed geometry</p>
            </div>
          </figure>
        </div>

        <Timeline
          analysis={analysis}
          win={win}
          frames={frames}
          time={time}
          playing={playing}
          onSeek={(t) => {
            pause();
            seek(t);
          }}
          onToggle={toggle}
          onStep={step}
          events={events}
          activeEventT={review.reviews?.[active.review]?.event.t ?? null}
          onEvent={(i) => {
            const idx = review.reviews?.findIndex((r) => Math.abs(r.event.t - events[i].t) < 1e-3) ?? -1;
            if (idx >= 0) {
              setTab("auto");
              openReview(idx);
            } else {
              pause();
              seek(events[i].t);
            }
          }}
          sel={sel}
          muted={muted}
          onMute={() => setMuted((m) => !m)}
          videoOk={videoOk}
        />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        <section aria-label="Review tools" className="rounded-xl border border-line bg-surface flex flex-col">
          <div role="tablist" aria-label="Review tools" className="flex gap-4 sm:gap-5 px-4 sm:px-5 border-b border-line overflow-x-auto [scrollbar-width:none]">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                id={`tab-${id}`}
                type="button"
                role="tab"
                aria-selected={tab === id}
                aria-controls={`panel-${id}`}
                onClick={() => setTab(id)}
                className={`relative h-11 text-sm font-medium whitespace-nowrap transition-colors duration-150 ${
                  tab === id ? "text-fg" : "text-muted hover:text-fg"
                }`}
              >
                {label}
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent transition-transform duration-200 ease-out ${
                    tab === id ? "scale-x-100" : "scale-x-0"
                  }`}
                />
              </button>
            ))}
          </div>
          <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="p-5">
            {tab === "auto" && (
              <ReviewPanel
                state={review}
                active={active}
                onOpen={openReview}
                onCandidate={pickCandidate}
                labelFor={labelFor}
                onManual={() => setTab("manual")}
              />
            )}
            {tab === "manual" && (
              <ManualCheck
                sel={sel}
                teams={teams}
                selected={selected}
                onSelect={onSelectPlayer}
                team={team}
                onTeam={setTeam}
                direction={direction}
                onDirection={setDirection}
                onCheck={check}
                checking={checking}
                error={assessError}
              />
            )}
            {tab === "foul" && (
              <Suspense fallback={<p className="text-sm text-muted">Loading foul review…</p>}>
                <FoulReview clip={clipId} start={win.start} end={win.end} time={time} onSeek={seek} />
              </Suspense>
            )}
          </div>
        </section>
        <div className="flex flex-col gap-6">
          {/* Foul verdicts render inside the foul panel; the offside card would only be noise there. */}
          {tab === "foul" ? null : assessment ? (
            <VerdictCard result={assessment} />
          ) : (
            <section className="rounded-xl border border-line bg-surface p-5 flex flex-col gap-2">
              <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-muted">System assessment</h3>
              <p className="text-sm text-muted">
                {review.status === "loading"
                  ? "Checking the detected passes…"
                  : "No check run yet. The verdict appears here, with its margin and how sure it is."}
              </p>
            </section>
          )}
          <OfficialRecord state={official} />
        </div>
      </div>
    </div>
  );
}

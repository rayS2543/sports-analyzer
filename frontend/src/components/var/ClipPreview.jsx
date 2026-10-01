import React, { useEffect, useRef, useState } from "react";
import { IconButton, icon } from "./VarViewer";
import { MAX_WINDOW_S, formatClock, windowAround } from "./varMath";

const STEP = 0.5;
const WINDOW_TONE = { done: "bg-win", running: "bg-accent", failed: "bg-loss" };

function Nudge({ label, value, onChange, max }) {
  const btn = "pressable grid place-items-center w-8 h-8 rounded-md border border-line text-muted hover:text-fg hover:border-faint disabled:opacity-40 disabled:hover:text-muted";
  return (
    <div className="flex items-center justify-between gap-3" role="group" aria-label={label}>
      <span className="text-sm text-muted">{label}</span>
      <div className="flex items-center gap-1.5">
        <button type="button" className={btn} aria-label={`${label}: less`} disabled={value <= STEP} onClick={() => onChange(value - STEP)}>
          −
        </button>
        <span className="w-12 text-center font-mono text-sm tabular-nums" aria-live="polite">
          {value.toFixed(1)} s
        </span>
        <button type="button" className={btn} aria-label={`${label}: more`} disabled={value + STEP > max} onClick={() => onChange(value + STEP)}>
          +
        </button>
      </div>
    </div>
  );
}

/**
 * Plays the ESPN clip straight from its CDN so the user can find the incident before anything is analysed.
 * The amber band is the window that "Analyze these seconds" will send.
 */
export default function ClipPreview({ clip, windows, onAnalyze, onOpenWindow }) {
  const videoRef = useRef(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(clip.duration_seconds || 0);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(!clip.source_url);
  const [before, setBefore] = useState(3);
  const [after, setAfter] = useState(2);

  useEffect(() => {
    if (!playing) return;
    let raf;
    const tick = () => {
      setTime(videoRef.current?.currentTime ?? 0);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const win = windowAround(time, { before, after, duration: duration || Infinity });
  const pct = (t) => `${duration ? (t / duration) * 100 : 0}%`;
  const seek = (t) => {
    const c = Math.max(0, Math.min(duration || t, t));
    setTime(c);
    if (videoRef.current) videoRef.current.currentTime = c;
  };
  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (playing) v.pause();
    else v.play().catch(() => {});
  };
  const nudge = (dt) => {
    videoRef.current?.pause();
    seek(time + dt);
  };

  return (
    <section aria-labelledby="preview-heading" className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-8 flex flex-col gap-3 min-w-0">
        <figure className="flex flex-col rounded-xl border border-line bg-surface overflow-hidden">
          <figcaption className="flex items-center justify-between gap-3 h-11 px-3 border-b border-line text-xs">
            <span className="font-medium text-fg truncate">{clip.title || `Clip ${clip.id}`}</span>
            {clip.page_url ? (
              <a href={clip.page_url} target="_blank" rel="noreferrer" className="shrink-0 text-muted hover:text-fg">
                Streaming from ESPN <span aria-hidden="true">↗</span>
              </a>
            ) : (
              <span className="shrink-0 text-faint">Streaming from ESPN</span>
            )}
          </figcaption>
          <div className="relative aspect-video bg-black">
            {!failed && (
              <video
                ref={videoRef}
                src={clip.source_url}
                className="absolute inset-0 w-full h-full object-contain"
                playsInline
                preload="metadata"
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || duration)}
                onPlay={() => setPlaying(true)}
                onPause={(e) => {
                  setPlaying(false);
                  setTime(e.currentTarget.currentTime);
                }}
                onSeeked={(e) => setTime(e.currentTarget.currentTime)}
                onError={() => setFailed(true)}
              />
            )}
            {failed && (
              <div className="absolute inset-0 grid place-items-center p-6 text-center">
                <div className="flex flex-col gap-1.5 max-w-xs">
                  <p className="text-sm font-medium">This clip can&rsquo;t be previewed here</p>
                  <p className="text-xs text-muted">
                    ESPN didn&rsquo;t serve a playable file. Watch it on ESPN and set the time with the scrubber below.
                  </p>
                </div>
              </div>
            )}
          </div>
        </figure>

        <div className="rounded-xl border border-line bg-surface px-2 sm:px-3 py-2.5 flex flex-col gap-2">
          <div className="flex items-center gap-1">
            <IconButton label="Back 0.1 seconds" onClick={() => nudge(-0.1)}>
              <svg {...icon}><path d="M3 3h2v10H3zM13 3v10L6 8z" /></svg>
            </IconButton>
            <IconButton label={playing ? "Pause preview" : "Play preview"} onClick={toggle} disabled={failed}>
              {playing ? <svg {...icon}><path d="M4 3h3v10H4zM9 3h3v10H9z" /></svg> : <svg {...icon}><path d="M4 2.5v11L13 8z" /></svg>}
            </IconButton>
            <IconButton label="Forward 0.1 seconds" onClick={() => nudge(0.1)}>
              <svg {...icon}><path d="M11 3h2v10h-2zM3 3v10l7-5z" /></svg>
            </IconButton>
            <p className="ml-1 font-mono text-sm tabular-nums">
              {formatClock(time)} <span className="text-faint">/ {formatClock(duration)}</span>
            </p>
          </div>
          <div className="relative h-11 rounded-lg bg-raised overflow-hidden has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent">
            {windows?.map((w) => (
              <span
                key={w.key}
                aria-hidden="true"
                className={`absolute bottom-0 h-1 opacity-70 ${WINDOW_TONE[w.status] || "bg-faint"}`}
                style={{ left: pct(w.start), width: pct(w.end - w.start) }}
              />
            ))}
            {win && (
              <span
                aria-hidden="true"
                className="absolute inset-y-1 rounded-md bg-accent/15 border border-accent/60 pointer-events-none transition-[left,width] duration-150 ease-out motion-reduce:transition-none"
                style={{ left: pct(win.start), width: pct(win.end - win.start) }}
              />
            )}
            <span aria-hidden="true" className="absolute inset-y-0 w-0.5 -ml-px bg-accent pointer-events-none" style={{ left: pct(time) }}>
              <span className="absolute -top-px left-1/2 -translate-x-1/2 w-2 h-1.5 rounded-b-sm bg-accent" />
            </span>
            <input
              type="range"
              aria-label="Preview time"
              aria-valuetext={formatClock(time)}
              min={0}
              max={duration || 0}
              step={0.1}
              value={time}
              onChange={(e) => {
                videoRef.current?.pause();
                seek(Number(e.target.value));
              }}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
          </div>
        </div>
      </div>

      <aside className="lg:col-span-4 rounded-xl border border-line bg-surface p-5 flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <h2 id="preview-heading" className="text-base font-semibold tracking-tight">
            Find the moment
          </h2>
          <p className="text-sm text-muted">Scrub to where the ball is played and pause. The seconds around it get analysed.</p>
        </div>

        <div className="flex flex-col gap-1 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3">
          <span className="text-xs text-muted">Seconds to analyse</span>
          <p className="font-mono text-xl tabular-nums tracking-tight">
            {win ? (
              <>
                {formatClock(win.start)}
                <span className="text-faint"> → </span>
                {formatClock(win.end)}
              </>
            ) : (
              "—"
            )}
          </p>
          {win && <span className="text-xs text-faint tabular-nums">{(win.end - win.start).toFixed(1)} s window</span>}
        </div>

        <div className="flex flex-col gap-2.5">
          <Nudge label="Before the moment" value={before} onChange={setBefore} max={MAX_WINDOW_S - after} />
          <Nudge label="After the moment" value={after} onChange={setAfter} max={MAX_WINDOW_S - before} />
        </div>

        <div className="flex flex-col gap-2">
          <button
            type="button"
            disabled={!win}
            onClick={() => onAnalyze(win)}
            className="pressable h-11 rounded-lg bg-accent text-accent-fg text-sm font-semibold disabled:bg-raised disabled:text-faint"
          >
            Analyze these seconds
          </button>
          <p className="text-xs text-faint">Up to {MAX_WINDOW_S} s. Usually takes a minute or two.</p>
        </div>

        {windows?.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-line pt-4">
            <h3 className="text-xs font-medium text-faint">Analysed before</h3>
            <div className="flex flex-wrap gap-1.5">
              {windows.map((w) => (
                <button
                  key={w.key}
                  type="button"
                  onClick={() => onOpenWindow(w)}
                  className="pressable inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full border border-line text-xs font-mono tabular-nums text-muted hover:text-fg hover:border-faint"
                >
                  <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full ${WINDOW_TONE[w.status] || "bg-faint"}`} />
                  {formatClock(w.start)}–{formatClock(w.end)}
                  <span className="sr-only">, {w.status}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </aside>
    </section>
  );
}

import React from "react";
import { Link } from "react-router-dom";

export const LEAGUE_NAMES = {
  PD: "La Liga",
  PL: "Premier League",
  SA: "Serie A",
  BL1: "Bundesliga",
  FL1: "Ligue 1",
};

// "2026-09-20" -> "Sat 20 Sep". Parsed as a calendar date so the day never shifts with the viewer's timezone.
export function formatDay(isoDate, { weekday = true } = {}) {
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    ...(weekday && { weekday: "short" }),
    day: "numeric",
    month: "short",
  });
}

function PitchMark() {
  return (
    <svg viewBox="0 0 24 24" className="w-5 h-5 text-accent" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M12 5v14" />
      <circle cx="12" cy="12" r="2.75" />
    </svg>
  );
}

export function SiteHeader({ back = false }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-canvas/85 backdrop-blur supports-[backdrop-filter]:bg-canvas/70">
      <div className="max-w-page mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        {back ? (
          <Link to="/" className="pressable inline-flex items-center gap-2 text-sm font-medium text-muted hover:text-fg">
            <span aria-hidden="true">←</span> Back to Sports Analyzer
          </Link>
        ) : (
          <h1 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
            <PitchMark />
            Sports Analyzer
          </h1>
        )}
        {!back && (
          <Link to="/feed" className="pressable inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-fg">
            <span aria-hidden="true">★</span> For You
          </Link>
        )}
      </div>
    </header>
  );
}

export function PageShell({ back, children }) {
  return (
    <>
      <SiteHeader back={back} />
      <main className="max-w-page mx-auto px-4 sm:px-6 lg:px-8 pt-8 pb-20 flex flex-col gap-14">{children}</main>
    </>
  );
}

export function Section({ title, aside, children, className = "" }) {
  return (
    <section className={`flex flex-col gap-4 min-w-0 ${className}`}>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {aside && <div className="text-sm text-muted">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function ErrorNote({ children }) {
  return (
    <p role="alert" className="text-sm text-loss">
      {children}
    </p>
  );
}

export function EmptyNote({ children }) {
  return <p className="text-sm text-muted py-2">{children}</p>;
}

export function SkeletonRows({ rows = 5, className = "" }) {
  return (
    <div className={`flex flex-col gap-3 ${className}`} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="skeleton w-6 h-6 rounded-md" />
          <div className="skeleton h-3.5" style={{ width: `${55 - ((i * 13) % 25)}%` }} />
          <div className="skeleton h-3.5 w-8 ml-auto" />
        </div>
      ))}
    </div>
  );
}

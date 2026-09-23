import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import LeagueChips from "./LeagueChips";
import TeamBadge from "./TeamBadge";
import { encodeMatchId } from "../matchId";
import { ErrorNote, LEAGUE_NAMES } from "./ui";

const LIVE_STATUSES = new Set(["IN_PLAY", "PAUSED", "LIVE"]);
const NON_TIME_LABEL = {
  POSTPONED: "Postponed",
  SUSPENDED: "Suspended",
  CANCELLED: "Cancelled",
};

function formatKickoff(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function StatusLabel({ match, isLive, isFinished }) {
  if (isLive) {
    return (
      <span className="inline-flex items-center gap-1.5 text-live font-semibold">
        <span className="w-1.5 h-1.5 rounded-full bg-live animate-pulse" aria-hidden="true" />
        {match.status === "PAUSED" ? "Half-time" : "Live"}
      </span>
    );
  }
  if (isFinished) return <span className="font-semibold text-muted">Full-time</span>;
  const off = NON_TIME_LABEL[match.status];
  if (off) return <span className="font-medium text-loss/90">{off}</span>;
  return <span className="font-medium text-fg tabular-nums">{formatKickoff(match.kickoff)}</span>;
}

function TeamLine({ name, crest, score, dim }) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      <TeamBadge name={name} crest={crest} size="sm" />
      <span className={`flex-1 truncate ${dim ? "text-muted" : "font-medium"}`}>{name}</span>
      <span className={`text-lg tabular-nums leading-none ${dim ? "text-muted" : "font-semibold"}`}>{score ?? ""}</span>
    </div>
  );
}

function MatchTile({ m }) {
  const isLive = LIVE_STATUSES.has(m.status);
  const isFinished = m.status === "FINISHED";
  const played = isLive || isFinished;
  const homeDim = played && m.home_score < m.away_score;
  const awayDim = played && m.away_score < m.home_score;

  const body = (
    <>
      <div className="flex items-center justify-between text-xs">
        <StatusLabel match={m} isLive={isLive} isFinished={isFinished} />
        <span className="text-faint">{LEAGUE_NAMES[m.league_code] || m.league_code}</span>
      </div>
      <div className="flex flex-col gap-2.5">
        <TeamLine name={m.home} crest={m.home_crest} score={m.home_score} dim={homeDim} />
        <TeamLine name={m.away} crest={m.away_crest} score={m.away_score} dim={awayDim} />
      </div>
    </>
  );

  const base = `flex flex-col gap-4 rounded-xl border bg-surface p-4 ${isLive ? "border-live/40" : "border-line"}`;

  if (!isFinished) return <li className={base}>{body}</li>;

  const to = `/match/${encodeMatchId({ league: m.league_code, date: m.kickoff.slice(0, 10), home: m.home, away: m.away })}`;
  return (
    <li>
      <Link to={to} className={`${base} pressable h-full hover:border-faint hover:bg-raised/60`}>
        {body}
      </Link>
    </li>
  );
}

function TileSkeleton() {
  return (
    <li className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4" aria-hidden="true">
      <div className="skeleton h-3 w-16" />
      {[0, 1].map((i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="skeleton w-6 h-6 rounded-md" />
          <div className="skeleton h-3.5 w-1/2" />
        </div>
      ))}
    </li>
  );
}

export default function TodayGames() {
  const [matches, setMatches] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedLeagues, setSelectedLeagues] = useState([]);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/matches/today`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setMatches(data);
          setError(null);
        } else {
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching today's matches:", err);
        setError("Could not reach the backend");
      })
      .finally(() => setLoading(false));
  }, []);

  const visible = selectedLeagues.length === 0 ? matches : matches.filter((m) => selectedLeagues.includes(m.league_code));
  const liveCount = matches.filter((m) => LIVE_STATUSES.has(m.status)).length;

  return (
    <section className="flex flex-col gap-5" aria-labelledby="today-heading">
      <div className="flex flex-col gap-1">
        <h2 id="today-heading" className="text-2xl sm:text-3xl font-semibold tracking-tight">
          Today&rsquo;s games
        </h2>
        <p className="text-sm text-muted">
          {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          {liveCount > 0 && <span className="text-live"> &middot; {liveCount} live now</span>}
        </p>
      </div>

      <LeagueChips selected={selectedLeagues} onChange={setSelectedLeagues} />

      {error && <ErrorNote>{error}</ErrorNote>}
      {!error && !loading && visible.length === 0 && (
        <p className="text-sm text-muted rounded-xl border border-dashed border-line px-4 py-8 text-center">
          No matches for the selected leagues today.
        </p>
      )}

      {!error && (loading || visible.length > 0) && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {loading ? [0, 1, 2].map((i) => <TileSkeleton key={i} />) : visible.map((m, idx) => <MatchTile key={idx} m={m} />)}
        </ul>
      )}
    </section>
  );
}

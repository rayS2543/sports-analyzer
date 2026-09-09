import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import LeagueChips from "./LeagueChips";
import TeamBadge from "./TeamBadge";
import { encodeMatchId } from "../matchId";

const LIVE_STATUSES = new Set(["IN_PLAY", "PAUSED", "LIVE"]);
const NON_TIME_LABEL = {
  POSTPONED: "PPD",
  SUSPENDED: "SUSP",
  CANCELLED: "CANC",
};

function formatKickoff(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function TodayGames() {
  const [matches, setMatches] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedLeagues, setSelectedLeagues] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    fetch("http://127.0.0.1:5000/matches/today")
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

  return (
    <section className="max-w-5xl mx-auto w-full bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
      <div className="flex flex-col gap-4 mb-6">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold">Today&rsquo;s Games</h2>
          <span className="text-sm text-slate-400">
            {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
          </span>
        </div>
        <LeagueChips selected={selectedLeagues} onChange={setSelectedLeagues} />
      </div>

      {error && <p className="text-rose-400 font-semibold">{error}</p>}
      {!error && loading && <p className="text-slate-400">Loading today&rsquo;s fixtures...</p>}
      {!error && !loading && visible.length === 0 && (
        <p className="text-slate-400">No matches for the selected leagues today.</p>
      )}

      <div className="flex flex-col divide-y divide-slate-800">
        {visible.map((m, idx) => {
          const isLive = LIVE_STATUSES.has(m.status);
          const isFinished = m.status === "FINISHED";
          return (
            <div
              key={idx}
              onClick={
                isFinished
                  ? () =>
                      navigate(
                        `/match/${encodeMatchId({
                          league: m.league_code,
                          date: m.kickoff.slice(0, 10),
                          home: m.home,
                          away: m.away,
                        })}`
                      )
                  : undefined
              }
              className={`flex items-center gap-4 py-4 ${isFinished ? "cursor-pointer hover:bg-slate-800/40 rounded-lg px-2 -mx-2" : ""}`}
            >
              <span className="text-[11px] font-semibold text-slate-500 w-14 uppercase tracking-wide shrink-0">{m.league_code}</span>

              <div className="flex-1 flex items-center gap-3 min-w-0">
                <TeamBadge name={m.home} size="sm" />
                <span className="font-semibold truncate">{m.home}</span>
              </div>

              <div className="flex flex-col items-center w-16 shrink-0 gap-1">
                <span className="font-bold text-lg tabular-nums">
                  {m.home_score ?? "-"} : {m.away_score ?? "-"}
                </span>
                {isLive && (
                  <span className="flex items-center gap-1 text-rose-400 text-[11px] font-bold">
                    <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" /> LIVE
                  </span>
                )}
                {isFinished && <span className="text-[11px] font-bold text-slate-400">FT</span>}
                {!isLive && !isFinished && (
                  <span className="text-[11px] font-semibold text-slate-400">
                    {NON_TIME_LABEL[m.status] || formatKickoff(m.kickoff)}
                  </span>
                )}
              </div>

              <div className="flex-1 flex items-center gap-3 justify-end min-w-0">
                <span className="font-semibold truncate text-right">{m.away}</span>
                <TeamBadge name={m.away} size="sm" />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

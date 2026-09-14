import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import NewsList from "./NewsList";
import TeamBadge, { hueFor } from "./TeamBadge";

const RESULT_STYLES = {
  W: { bg: "bg-emerald-500", text: "text-emerald-400", label: "won" },
  D: { bg: "bg-amber-500", text: "text-amber-400", label: "drew" },
  L: { bg: "bg-rose-500", text: "text-rose-400", label: "lost" },
};

function FormBadge({ result, title, size = "md" }) {
  const style = RESULT_STYLES[result] || RESULT_STYLES.D;
  const sizeClasses = size === "sm" ? "w-6 h-6 text-[11px]" : "w-8 h-8 text-sm";
  return (
    <span
      title={title}
      className={`${sizeClasses} rounded-full ${style.bg} font-bold flex items-center justify-center text-white shrink-0`}
    >
      {result}
    </span>
  );
}

function StatBlock({ label, value }) {
  return (
    <div className="flex-1 min-w-[4.5rem] text-center px-2 py-3">
      <p className="text-xl sm:text-2xl font-bold">{value ?? "-"}</p>
      <p className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">{label}</p>
    </div>
  );
}

export default function TeamDetailPage() {
  const { league, name } = useParams();
  const decodedName = decodeURIComponent(name);

  const [form, setForm] = useState(null);
  const [formError, setFormError] = useState(null);

  const [teamInfo, setTeamInfo] = useState(null);
  const [standings, setStandings] = useState(null);

  const [fixtures, setFixtures] = useState([]);

  useEffect(() => {
    setForm(null);
    setFormError(null);
    fetch(`${API_BASE}/analytics/form/${encodeURIComponent(decodedName)}?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setFormError(data.error);
        } else {
          setForm(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching team form:", err);
        setFormError("Could not reach the backend");
      });
  }, [league, decodedName]);

  useEffect(() => {
    setTeamInfo(null);
    fetch(`${API_BASE}/teams?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setTeamInfo(data.find((t) => t.name === decodedName) || null);
        }
      })
      .catch((err) => console.error("Error fetching team info:", err));
  }, [league, decodedName]);

  useEffect(() => {
    setStandings(null);
    fetch(`${API_BASE}/standings?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setStandings(data);
        }
      })
      .catch((err) => console.error("Error fetching standings:", err));
  }, [league, decodedName]);

  useEffect(() => {
    setFixtures([]);
    fetch(`${API_BASE}/predictions?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setFixtures(data.filter((p) => p.home === decodedName || p.away === decodedName));
        }
      })
      .catch((err) => console.error("Error fetching predictions:", err));
  }, [league, decodedName]);

  const standing = standings?.find((s) => s.team_name === decodedName) || null;
  const teamIndex = standings?.findIndex((s) => s.team_name === decodedName);
  const nearbyStandings =
    standings && teamIndex >= 0
      ? standings.slice(Math.max(0, teamIndex - 2), Math.min(standings.length, teamIndex + 3))
      : null;
  const isTitleZone = standings && standings.length > 10;

  const hue = hueFor(decodedName);
  const avgScored = standing?.playedGames ? (standing.goalsFor / standing.playedGames).toFixed(1) : null;
  const avgConceded = standing?.playedGames ? (standing.goalsAgainst / standing.playedGames).toFixed(1) : null;

  return (
    <>
      <header className="border-b border-slate-800 px-6 sm:px-10 py-5">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-violet-400 font-semibold hover:text-violet-300">
            ← Back to Sports Analyzer
          </Link>
        </div>
      </header>

      <main className="px-6 sm:px-10 py-10 flex flex-col gap-6 max-w-5xl mx-auto w-full">
        {/* Hero */}
        <section
          className="rounded-2xl border border-slate-800 shadow-lg shadow-black/20 overflow-hidden"
          style={{ background: `linear-gradient(135deg, hsl(${hue} 65% 20%), rgb(2 6 23) 75%)` }}
        >
          <div className="p-6 sm:p-8 flex flex-wrap items-center gap-5">
            {teamInfo?.crest ? (
              <img src={teamInfo.crest} alt={decodedName} className="w-20 h-20 object-contain drop-shadow" />
            ) : (
              <TeamBadge name={decodedName} tla={teamInfo?.tla} size="lg" />
            )}
            <div className="flex-1 min-w-[12rem]">
              <h1 className="text-2xl sm:text-3xl font-bold">{decodedName}</h1>
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                {teamInfo?.tla && (
                  <span className="text-xs font-semibold uppercase tracking-wide bg-white/10 rounded-full px-2.5 py-1">
                    {teamInfo.tla}
                  </span>
                )}
                {form && (
                  <div className="flex items-center gap-1">
                    {form.form
                      .split("")
                      .slice(0, 5)
                      .map((r, idx) => (
                        <FormBadge key={idx} result={r} size="sm" />
                      ))}
                  </div>
                )}
              </div>
            </div>
            {standing?.position && (
              <div className="text-center bg-black/30 rounded-xl px-5 py-3 backdrop-blur-sm">
                <p className="text-3xl font-bold text-white">
                  {standing.position}
                  <span className="text-base text-slate-400">/{standings.length}</span>
                </p>
                <p className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">League Position</p>
              </div>
            )}
          </div>

          {standing && (
            <div className="flex flex-wrap divide-x divide-white/10 border-t border-white/10 bg-black/20">
              <StatBlock label="Played" value={standing.playedGames} />
              <StatBlock label="W-D-L" value={`${standing.won}-${standing.draw}-${standing.lost}`} />
              <StatBlock label="Goal Diff" value={standing.goalDifference > 0 ? `+${standing.goalDifference}` : standing.goalDifference} />
              <StatBlock label="Goals/Game" value={avgScored} />
              <StatBlock label="Conceded/Game" value={avgConceded} />
              <StatBlock label="Points" value={standing.points} />
            </div>
          )}
        </section>

        {formError && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <p className="text-rose-400 font-semibold">{formError}</p>
          </section>
        )}

        {/* League table snippet */}
        {nearbyStandings && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <h2 className="text-xl font-bold mb-4">Standings</h2>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-slate-400">
                    <th className="px-3 py-2 text-left font-semibold">#</th>
                    <th className="px-3 py-2 text-left font-semibold">Team</th>
                    <th className="px-3 py-2 text-center font-semibold">P</th>
                    <th className="px-3 py-2 text-center font-semibold">W</th>
                    <th className="px-3 py-2 text-center font-semibold">D</th>
                    <th className="px-3 py-2 text-center font-semibold">L</th>
                    <th className="px-3 py-2 text-center font-semibold">GD</th>
                    <th className="px-3 py-2 text-center font-semibold">Pts</th>
                  </tr>
                </thead>
                <tbody>
                  {nearbyStandings.map((s) => {
                    const isCurrent = s.team_name === decodedName;
                    const zoneColor = isTitleZone
                      ? s.position <= 4
                        ? "border-l-4 border-l-emerald-500"
                        : s.position > standings.length - 3
                        ? "border-l-4 border-l-rose-500"
                        : "border-l-4 border-l-transparent"
                      : "";
                    return (
                      <tr
                        key={s.team_name}
                        className={`border-b border-slate-800 ${zoneColor} ${
                          isCurrent ? "bg-violet-500/10 font-bold" : "hover:bg-slate-800/40"
                        }`}
                      >
                        <td className="px-3 py-2.5 text-slate-400">{s.position}</td>
                        <td className="px-3 py-2.5">
                          <Link
                            to={`/team/${league}/${encodeURIComponent(s.team_name)}`}
                            className={`flex items-center gap-2 ${isCurrent ? "text-violet-300" : "hover:text-violet-300"}`}
                          >
                            <TeamBadge name={s.team_name} tla={s.tla} size="sm" />
                            {s.team_name}
                          </Link>
                        </td>
                        <td className="px-3 py-2.5 text-center">{s.playedGames}</td>
                        <td className="px-3 py-2.5 text-center">{s.won}</td>
                        <td className="px-3 py-2.5 text-center">{s.draw}</td>
                        <td className="px-3 py-2.5 text-center">{s.lost}</td>
                        <td className="px-3 py-2.5 text-center">{s.goalDifference}</td>
                        <td className="px-3 py-2.5 text-center text-violet-400">{s.points}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Recent results */}
          {!formError && form && (
            <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
              <h2 className="text-xl font-bold mb-1">Recent Results</h2>
              <p className="text-slate-400 text-sm mb-4">
                {form.points} points from last {form.matches_considered} matches
              </p>
              <div className="flex flex-col divide-y divide-slate-800">
                {form.matches.map((m, idx) => {
                  const result = m.winner === decodedName ? "W" : m.winner === "Draw" ? "D" : "L";
                  return (
                    <div key={idx} className="flex items-center gap-3 py-2.5">
                      <FormBadge result={result} size="sm" />
                      <span className="text-slate-400 text-xs w-20 shrink-0">{m.date}</span>
                      <span className="font-medium text-sm flex-1 truncate">
                        {m.home} {m.score} {m.away}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Upcoming fixtures */}
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <h2 className="text-xl font-bold mb-4">Upcoming Fixtures</h2>
            {fixtures.length === 0 ? (
              <p className="text-slate-400">No upcoming fixtures found.</p>
            ) : (
              <div className="flex flex-col divide-y divide-slate-800">
                {fixtures.map((p, idx) => {
                  const opponent = p.home === decodedName ? p.away : p.home;
                  const teamWinPct = p.home === decodedName ? p.home_win_pct : p.away_win_pct;
                  const isHome = p.home === decodedName;
                  return (
                    <div key={idx} className="flex items-center justify-between gap-3 py-2.5">
                      <div className="min-w-0">
                        <p className="text-slate-400 text-xs">{p.date}</p>
                        <p className="font-medium text-sm truncate">
                          {isHome ? `vs ${opponent}` : `@ ${opponent}`}
                        </p>
                      </div>
                      <span className="text-sm font-bold text-violet-400 shrink-0">{teamWinPct}%</span>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
          <h2 className="text-xl font-bold mb-4">Latest News</h2>
          <NewsList query={decodedName} />
        </section>
      </main>
    </>
  );
}

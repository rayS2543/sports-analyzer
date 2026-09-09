import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import NewsList from "./NewsList";
import { decodeMatchId } from "../matchId";

function PlayerRow({ player, expanded, onToggle }) {
  return (
    <li>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-slate-800/60 transition-colors"
      >
        <span className="text-xs text-slate-500 w-5 text-right shrink-0">{player.number ?? ""}</span>
        <span className="font-medium flex-1 truncate">{player.name}</span>
        <span className="text-xs text-slate-500">{player.position}</span>
      </button>
      {expanded && (
        <div className="ml-9 mb-2 px-3 py-2 rounded-lg bg-slate-800/60 text-sm flex flex-col gap-1.5">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-300">
            <span>
              Rating: <strong className="text-violet-300">{player.rating ?? "-"}</strong>
            </span>
            <span>Minutes: {player.minutes ?? "-"}</span>
            <span>Goals: {player.goals}</span>
            <span>Assists: {player.assists}</span>
            {player.yellow_cards > 0 && <span className="text-amber-400">Yellow: {player.yellow_cards}</span>}
            {player.red_cards > 0 && <span className="text-rose-400">Red: {player.red_cards}</span>}
          </div>
          {player.id && (
            <Link to={`/player/${player.id}`} className="text-violet-400 hover:text-violet-300 font-semibold">
              Full profile →
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

function TeamLineup({ team, expandedPlayer, onTogglePlayer }) {
  if (!team) return null;
  return (
    <div>
      <h3 className="font-bold mb-1">{team.team_name}</h3>
      <p className="text-xs text-slate-500 mb-3">Formation: {team.formation || "-"}</p>

      <p className="text-xs font-semibold text-slate-400 uppercase mb-2">Starting XI</p>
      <ul className="flex flex-col gap-1 mb-4">
        {team.starters.map((p) => (
          <PlayerRow key={p.id} player={p} expanded={expandedPlayer === p.id} onToggle={() => onTogglePlayer(p.id)} />
        ))}
      </ul>

      {team.bench.length > 0 && (
        <>
          <p className="text-xs font-semibold text-slate-400 uppercase mb-2">Bench</p>
          <ul className="flex flex-col gap-1">
            {team.bench.map((p) => (
              <PlayerRow key={p.id} player={p} expanded={expandedPlayer === p.id} onToggle={() => onTogglePlayer(p.id)} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default function MatchDetailPage() {
  const { id } = useParams();
  const { league, date, home, away } = decodeMatchId(id);

  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [expandedPlayer, setExpandedPlayer] = useState(null);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    const query = new URLSearchParams({ league, date, home, away });
    fetch(`http://127.0.0.1:5000/matches/detail?${query}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setDetailError(data.error);
        } else {
          setDetail(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching match detail:", err);
        setDetailError("Could not reach the backend");
      });
  }, [league, date, home, away]);

  const togglePlayer = (playerId) => setExpandedPlayer((current) => (current === playerId ? null : playerId));

  return (
    <>
      <header className="border-b border-slate-800 px-6 sm:px-10 py-5">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-violet-400 font-semibold hover:text-violet-300">
            ← Back to Sports Analyzer
          </Link>
        </div>
      </header>

      <main className="px-6 sm:px-10 py-10 flex flex-col gap-8 max-w-5xl mx-auto w-full">
        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <TeamBadge name={home} />
              <span className="font-bold text-lg truncate">{home}</span>
            </div>
            <span className="text-sm text-slate-400 shrink-0">{date}</span>
            <div className="flex items-center gap-3 flex-1 min-w-0 justify-end">
              <span className="font-bold text-lg truncate text-right">{away}</span>
              <TeamBadge name={away} />
            </div>
          </div>
        </section>

        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
          <h2 className="text-xl font-bold mb-6">Lineups</h2>

          {detailError && <p className="text-rose-400 font-semibold">{detailError}</p>}
          {!detailError && !detail && <p className="text-slate-400">Loading lineups...</p>}
          {!detailError && detail && !detail.available && (
            <p className="text-slate-400">{detail.reason || "Lineup not available for this match."}</p>
          )}
          {!detailError && detail && detail.available && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
              <TeamLineup team={detail.home} expandedPlayer={expandedPlayer} onTogglePlayer={togglePlayer} />
              <TeamLineup team={detail.away} expandedPlayer={expandedPlayer} onTogglePlayer={togglePlayer} />
            </div>
          )}
        </section>

        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
          <h2 className="text-xl font-bold mb-4">Recent Headlines</h2>
          <NewsList query={`${home} vs ${away}`} />
        </section>
      </main>
    </>
  );
}

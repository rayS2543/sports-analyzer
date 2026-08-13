import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";

export default function StandingsTable({ league }) {
  const [standings, setStandings] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetch(`http://127.0.0.1:5000/standings?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setStandings(data);
        } else {
          setStandings([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching standings:", err);
        setStandings([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <div className="max-w-5xl mx-auto w-full bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
      <h2 className="text-xl font-bold mb-6">Standings</h2>
      {error ? (
        <p className="text-base font-semibold text-rose-400">{error}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-slate-800/80 text-slate-300">
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Pos</th>
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Team</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">P</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">W</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">D</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">L</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">GF</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">GA</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">GD</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">Pts</th>
              </tr>
            </thead>
            <tbody>
              {standings.map((s, idx) => (
                <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/40">
                  <td className="px-4 py-3 font-bold text-slate-400">{s.position}</td>
                  <td className="px-4 py-3 font-semibold">
                    <div className="flex items-center gap-2">
                      <TeamBadge name={s.team_name} tla={s.tla} size="sm" />
                      {s.team_name}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">{s.playedGames}</td>
                  <td className="px-4 py-3 text-center">{s.won}</td>
                  <td className="px-4 py-3 text-center">{s.draw}</td>
                  <td className="px-4 py-3 text-center">{s.lost}</td>
                  <td className="px-4 py-3 text-center">{s.goalsFor}</td>
                  <td className="px-4 py-3 text-center">{s.goalsAgainst}</td>
                  <td className="px-4 py-3 text-center">{s.goalDifference}</td>
                  <td className="px-4 py-3 text-center text-base font-bold text-violet-400">{s.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

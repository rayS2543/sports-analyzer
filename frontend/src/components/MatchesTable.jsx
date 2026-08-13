import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";

export default function MatchesTable({ league, leagueName }) {
  const [matches, setMatches] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetch(`http://127.0.0.1:5000/matches?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setMatches(data);
        } else {
          setMatches([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching matches:", err);
        setMatches([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <div className="max-w-5xl mx-auto w-full bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
      <h2 className="text-xl font-bold mb-6">
        ⚽ {leagueName ? `${leagueName} Match Tracker` : "Match Tracker"}
      </h2>
      {error ? (
        <p className="text-base font-semibold text-rose-400">{error}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-slate-800/80 text-slate-300">
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Date</th>
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Home Team</th>
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Away Team</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">Score</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">Winner</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m, idx) => (
                <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/40">
                  <td className="px-4 py-3 text-slate-400">{m.date}</td>
                  <td className="px-4 py-3 font-semibold">
                    <div className="flex items-center gap-2">
                      <TeamBadge name={m.home} size="sm" />
                      {m.home}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-semibold">
                    <div className="flex items-center gap-2">
                      <TeamBadge name={m.away} size="sm" />
                      {m.away}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center text-base font-bold tabular-nums">{m.score}</td>
                  <td
                    className={`px-4 py-3 text-center font-bold ${
                      m.winner === "Draw"
                        ? "text-amber-400"
                        : m.winner === m.home
                        ? "text-emerald-400"
                        : "text-rose-400"
                    }`}
                  >
                    {m.winner}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

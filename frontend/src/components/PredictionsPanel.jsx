import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";

export default function PredictionsPanel({ league }) {
  const [predictions, setPredictions] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!league) return;

    setError(null);
    fetch(`http://127.0.0.1:5000/predictions?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.error) {
          setError(data.error);
          setPredictions([]);
        } else {
          setPredictions(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching predictions:", err);
        setError("Could not reach the predictions service.");
        setPredictions([]);
      });
  }, [league]);

  return (
    <div className="max-w-5xl mx-auto w-full bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
      <h2 className="text-xl font-bold mb-6">🔮 Upcoming Fixture Predictions</h2>

      {error && <p className="font-semibold text-rose-400">{error}</p>}

      {!error && predictions.length === 0 && <p className="text-slate-400">No upcoming fixtures found.</p>}

      {!error && predictions.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-slate-800/80 text-slate-300">
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Date</th>
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Home</th>
                <th className="px-4 py-3 text-left font-semibold border-b border-slate-700">Away</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">Predicted Winner</th>
                <th className="px-4 py-3 text-center font-semibold border-b border-slate-700">Win Probability</th>
              </tr>
            </thead>
            <tbody>
              {predictions.map((p, idx) => (
                <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/40">
                  <td className="px-4 py-3 text-slate-400">{p.date}</td>
                  <td className="px-4 py-3 font-semibold">
                    <div className="flex items-center gap-2">
                      <TeamBadge name={p.home} size="sm" />
                      {p.home}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-semibold">
                    <div className="flex items-center gap-2">
                      <TeamBadge name={p.away} size="sm" />
                      {p.away}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center font-bold text-emerald-400">{p.predicted_winner}</td>
                  <td className="px-4 py-3 text-center">
                    <div className="flex items-center gap-2">
                      <span className="w-24 text-right text-xs text-slate-400">
                        {p.home}: {p.home_win_pct}%
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden flex min-w-[6rem]">
                        <div className="h-full bg-violet-500" style={{ width: `${p.home_win_pct}%` }} />
                        <div className="h-full bg-rose-500" style={{ width: `${p.away_win_pct}%` }} />
                      </div>
                      <span className="w-24 text-left text-xs text-slate-400">
                        {p.away}: {p.away_win_pct}%
                      </span>
                    </div>
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

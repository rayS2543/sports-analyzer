import React, { useEffect, useState } from "react";

export default function LeagueSelector({ league, onChange, onLeaguesLoaded }) {
  const [leagues, setLeagues] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("http://127.0.0.1:5000/leagues")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setLeagues(data);
          if (onLeaguesLoaded) onLeaguesLoaded(data);
        } else {
          setError(data.error || "Failed to load leagues");
        }
      })
      .catch((err) => {
        console.error("Error fetching leagues:", err);
        setError("Could not reach the backend");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex items-center gap-3">
      <select
        id="league-select"
        value={league}
        onChange={(e) => onChange(e.target.value)}
        className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2 text-sm font-semibold text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 hover:border-slate-500"
      >
        {leagues.map((l) => (
          <option key={l.code} value={l.code} className="bg-slate-900 text-slate-100">
            {l.name} ({l.country})
          </option>
        ))}
      </select>
      {error && <span className="text-rose-400 text-sm font-semibold">{error}</span>}
    </div>
  );
}

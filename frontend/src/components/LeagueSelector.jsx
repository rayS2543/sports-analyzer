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
    <div className="max-w-7xl mx-auto mb-8 flex flex-col sm:flex-row sm:items-center gap-3">
      <label htmlFor="league-select" className="text-lg font-bold">
        League
      </label>
      <select
        id="league-select"
        value={league}
        onChange={(e) => onChange(e.target.value)}
        className="bg-gray-800/60 border border-gray-600 rounded-xl px-5 py-3 text-base font-semibold text-white focus:outline-none focus:ring-2 focus:ring-blue-600 hover:bg-blue-600/20"
      >
        {leagues.map((l) => (
          <option key={l.code} value={l.code} className="bg-gray-800 text-white">
            {l.name} ({l.country})
          </option>
        ))}
      </select>
      {error && <span className="text-red-400 font-semibold">{error}</span>}
    </div>
  );
}

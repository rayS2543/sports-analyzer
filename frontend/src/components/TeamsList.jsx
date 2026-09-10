import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";

export default function TeamsList({ league }) {
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetch(`http://127.0.0.1:5000/teams?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setTeams(data);
        } else {
          setTeams([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching teams:", err);
        setTeams([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <div className="max-w-5xl mx-auto w-full bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
      <h2 className="text-xl font-bold mb-6">Teams</h2>
      {error ? (
        <p className="text-base font-semibold text-rose-400">{error}</p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {teams.map((team) => (
            <div
              key={team.tla}
              className="flex flex-col items-center gap-2 bg-slate-800/60 rounded-xl p-4 hover:bg-slate-800 transition-colors"
            >
              {team.crest ? (
                <img src={team.crest} alt={team.name} className="w-12 h-12 object-contain" />
              ) : (
                <TeamBadge name={team.name} tla={team.tla} size="lg" />
              )}
              <p className="text-sm font-semibold text-center">{team.shortName || team.name}</p>
              <p className="text-xs text-slate-400">{team.tla}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

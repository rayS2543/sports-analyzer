import React, { useEffect, useState } from "react";
import { fetchTeams } from "../api";

export default function TeamsGrid() {
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchTeams()
      .then((data) => (data.error ? setError(data.error) : setTeams(data)))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">🛡️ La Liga Teams</h1>
      <div className="max-w-6xl mx-auto">
        {error && <p className="text-red-400 text-center mb-4">{error}</p>}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-6">
          {teams.map((team) => (
            <div
              key={team.tla}
              className="bg-gray-800/60 rounded-2xl p-6 shadow-xl flex flex-col items-center gap-3 hover:bg-blue-600/20 transition-colors"
            >
              {team.crest && <img src={team.crest} alt={team.name} className="w-16 h-16" />}
              <p className="font-bold text-center">{team.shortName}</p>
              <p className="text-xs text-gray-400">{team.tla}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

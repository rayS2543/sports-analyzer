import React, { useEffect, useState } from "react";
import { API_BASE_URL } from "../api/config";

export default function TeamsList() {
  const [teams, setTeams] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/teams`)
      .then((res) => res.json())
      .then((data) => setTeams(Array.isArray(data) ? data : []))
      .catch((err) => console.error("Error fetching teams:", err));
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">La Liga Teams</h1>
      <div className="max-w-7xl mx-auto grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-6">
        {teams.map((team) => (
          <div
            key={team.tla}
            className="bg-gray-800/60 rounded-2xl p-6 shadow-xl flex flex-col items-center gap-3 hover:bg-gray-700/60 transition-colors"
          >
            {team.crest && (
              <img src={team.crest} alt={team.name} className="w-16 h-16 object-contain" />
            )}
            <p className="text-lg font-bold text-center">{team.shortName || team.name}</p>
            <p className="text-sm text-gray-400">{team.tla}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

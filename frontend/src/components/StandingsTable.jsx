import React, { useEffect, useState } from "react";
import { fetchStandings } from "../api";

export default function StandingsTable() {
  const [standings, setStandings] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchStandings()
      .then((data) => (data.error ? setError(data.error) : setStandings(data)))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">🏆 La Liga Standings</h1>
      <div className="max-w-5xl mx-auto bg-gray-800/60 rounded-3xl p-8 shadow-2xl overflow-x-auto">
        {error && <p className="text-red-400 text-center mb-4">{error}</p>}
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-blue-600">
              <th className="px-4 py-4 text-left text-sm font-bold border-b-4 border-gray-600">#</th>
              <th className="px-4 py-4 text-left text-sm font-bold border-b-4 border-gray-600">Team</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">P</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">W</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">D</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">L</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">GD</th>
              <th className="px-4 py-4 text-center text-sm font-bold border-b-4 border-gray-600">Pts</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((team) => (
              <tr key={team.tla ?? team.team_name} className="border-b border-gray-600 hover:bg-blue-600/20">
                <td className="px-4 py-3 text-base font-semibold">{team.position}</td>
                <td className="px-4 py-3 text-base font-semibold flex items-center gap-2">
                  {team.crest && <img src={team.crest} alt="" className="w-6 h-6" />}
                  {team.team_name}
                </td>
                <td className="px-4 py-3 text-center">{team.playedGames}</td>
                <td className="px-4 py-3 text-center">{team.won}</td>
                <td className="px-4 py-3 text-center">{team.draw}</td>
                <td className="px-4 py-3 text-center">{team.lost}</td>
                <td className="px-4 py-3 text-center">{team.goalDifference}</td>
                <td className="px-4 py-3 text-center font-bold">{team.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

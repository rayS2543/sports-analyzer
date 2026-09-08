import React, { useEffect, useState } from "react";
import { API_BASE_URL } from "../api/config";

export default function StandingsTable() {
  const [standings, setStandings] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/standings`)
      .then((res) => res.json())
      .then((data) => setStandings(Array.isArray(data) ? data : []))
      .catch((err) => console.error("Error fetching standings:", err));
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">La Liga Standings</h1>
      <div className="max-w-7xl mx-auto bg-gray-800/60 rounded-3xl p-8 shadow-2xl overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-blue-600">
              <th className="px-4 py-4 text-left text-base font-bold border-b-4 border-gray-600">#</th>
              <th className="px-4 py-4 text-left text-base font-bold border-b-4 border-gray-600">Team</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">P</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">W</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">D</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">L</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">GD</th>
              <th className="px-4 py-4 text-center text-base font-bold border-b-4 border-gray-600">Pts</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((row) => (
              <tr
                key={row.team_name}
                className="border-b border-gray-600 hover:bg-blue-600/20"
              >
                <td className="px-4 py-4 text-base font-semibold">{row.position}</td>
                <td className="px-4 py-4 text-base font-semibold">{row.team_name}</td>
                <td className="px-4 py-4 text-center text-base">{row.playedGames}</td>
                <td className="px-4 py-4 text-center text-base">{row.won}</td>
                <td className="px-4 py-4 text-center text-base">{row.draw}</td>
                <td className="px-4 py-4 text-center text-base">{row.lost}</td>
                <td className="px-4 py-4 text-center text-base">{row.goalDifference}</td>
                <td className="px-4 py-4 text-center text-lg font-bold">{row.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

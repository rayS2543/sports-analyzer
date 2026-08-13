import React, { useEffect, useState } from "react";

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
    <div className="max-w-7xl mx-auto bg-gray-800/60 rounded-3xl p-8 shadow-2xl mb-12">
      <h2 className="text-3xl font-bold mb-6">Standings</h2>
      {error ? (
        <p className="text-lg font-semibold text-red-400">{error}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="bg-blue-600">
                <th className="px-6 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Pos</th>
                <th className="px-6 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Team</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">P</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">W</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">D</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">L</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">GF</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">GA</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">GD</th>
                <th className="px-6 py-5 text-center text-lg font-bold border-b-4 border-gray-600">Pts</th>
              </tr>
            </thead>
            <tbody>
              {standings.map((s, idx) => (
                <tr key={idx} className="border-b border-gray-600 hover:bg-blue-600/20">
                  <td className="px-6 py-4 text-base font-bold">{s.position}</td>
                  <td className="px-6 py-4 text-base font-semibold">{s.team_name}</td>
                  <td className="px-6 py-4 text-center text-base">{s.playedGames}</td>
                  <td className="px-6 py-4 text-center text-base">{s.won}</td>
                  <td className="px-6 py-4 text-center text-base">{s.draw}</td>
                  <td className="px-6 py-4 text-center text-base">{s.lost}</td>
                  <td className="px-6 py-4 text-center text-base">{s.goalsFor}</td>
                  <td className="px-6 py-4 text-center text-base">{s.goalsAgainst}</td>
                  <td className="px-6 py-4 text-center text-base">{s.goalDifference}</td>
                  <td className="px-6 py-4 text-center text-xl font-bold">{s.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

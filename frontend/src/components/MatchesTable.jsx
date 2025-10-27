import React, { useEffect, useState } from "react";

export default function MatchesTable() {
  const [matches, setMatches] = useState([]);
  
  useEffect(() => {
    fetch("http://127.0.0.1:5000/matches")
      .then((res) => res.json())
      .then((data) => setMatches(data))
      .catch((err) => console.error("Error fetching matches:", err));
  }, []);
  
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">
        ⚽ La Liga Match Tracker
      </h1>
      <div className="max-w-7xl mx-auto bg-gray-800/60 rounded-3xl p-8 shadow-2xl">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-blue-600">
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Date</th>
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Home Team</th>
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Away Team</th>
              <th className="px-8 py-5 text-center text-lg font-bold border-b-4 border-gray-600">Score</th>
              <th className="px-8 py-5 text-center text-lg font-bold border-b-4 border-gray-600">Winner</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m, idx) => (
              <tr
                key={idx}
                className="border-b border-gray-600 hover:bg-blue-600/20"
              >
                <td className="px-8 py-6 text-base">{m.date}</td>
                <td className="px-8 py-6 text-base font-semibold">{m.home}</td>
                <td className="px-8 py-6 text-base font-semibold">{m.away}</td>
                <td className="px-8 py-6 text-center text-xl font-bold">{m.score}</td>
                <td
                  className={`px-8 py-6 text-center text-base font-bold ${
                    m.winner === "Draw"
                      ? "text-yellow-300"
                      : m.winner === m.home
                      ? "text-green-400"
                      : "text-red-400"
                  }`}
                >
                  {m.winner}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
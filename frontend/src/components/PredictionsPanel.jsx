import React, { useEffect, useState } from "react";

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
    <div className="max-w-7xl mx-auto bg-gray-800/60 rounded-3xl p-8 shadow-2xl mt-8">
      <h2 className="text-3xl font-bold text-center mb-8">🔮 Upcoming Fixture Predictions</h2>

      {error && (
        <p className="text-center text-red-400 text-lg font-semibold py-6">{error}</p>
      )}

      {!error && predictions.length === 0 && (
        <p className="text-center text-gray-400 text-lg py-6">No upcoming fixtures found.</p>
      )}

      {!error && predictions.length > 0 && (
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-blue-600">
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Date</th>
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Home</th>
              <th className="px-8 py-5 text-left text-lg font-bold border-b-4 border-gray-600">Away</th>
              <th className="px-8 py-5 text-center text-lg font-bold border-b-4 border-gray-600">Predicted Winner</th>
              <th className="px-8 py-5 text-center text-lg font-bold border-b-4 border-gray-600">Win Probability</th>
            </tr>
          </thead>
          <tbody>
            {predictions.map((p, idx) => (
              <tr key={idx} className="border-b border-gray-600 hover:bg-blue-600/20">
                <td className="px-8 py-6 text-base">{p.date}</td>
                <td className="px-8 py-6 text-base font-semibold">{p.home}</td>
                <td className="px-8 py-6 text-base font-semibold">{p.away}</td>
                <td className="px-8 py-6 text-center text-base font-bold text-green-400">
                  {p.predicted_winner}
                </td>
                <td className="px-8 py-6 text-center text-base">
                  <div className="flex items-center gap-2">
                    <span className="w-28 text-right">{p.home}: {p.home_win_pct}%</span>
                    <div className="flex-1 h-3 rounded-full bg-gray-700 overflow-hidden flex min-w-[6rem]">
                      <div
                        className="h-full bg-blue-500"
                        style={{ width: `${p.home_win_pct}%` }}
                      />
                      <div
                        className="h-full bg-red-500"
                        style={{ width: `${p.away_win_pct}%` }}
                      />
                    </div>
                    <span className="w-28 text-left">{p.away}: {p.away_win_pct}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

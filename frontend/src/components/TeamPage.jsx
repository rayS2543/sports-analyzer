import { useParams } from "react-router-dom";
import { useEffect, useState } from "react";

function TeamPage() {
  const { teamName } = useParams();
  const [teamData, setTeamData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTeamData = async () => {
      try {
        const res = await fetch(`http://127.0.0.1:5000/standings/${teamName}`);
        const data = await res.json();
        setTeamData(data);
      } catch (error) {
        console.error("Error fetching team data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchTeamData();
  }, [teamName]);

  if (loading) return <p className="text-center mt-8">Loading...</p>;
  if (!teamData || teamData.error) return <p>Team not found or API error.</p>;

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white py-12 px-6">
      <div className="max-w-4xl mx-auto">
      <div className="bg-gradient-to-br from-blue-900 via-gray-900 to-gray-900 rounded-3xl p-8 shadow-2xl mb-10 border border-gray-800">
        <div className="flex items-center gap-6">
          <img
            src={teamData.crest}
            alt={`${teamData.team_name} crest`}
            className="w-20 h-20 bg-white rounded-full p-2 shadow-md"
          />
          <div>
            <h1 className="text-4xl font-extrabold text-white tracking-tight mb-1">
              {teamData.team_name}
            </h1>
            <div className="h-1 w-24 bg-blue-600 rounded-full mb-2"></div>
            <p className="text-blue-400 font-medium tracking-wide text-sm mt-1">La Liga • 2025 Season</p>
          </div>
        </div>
      </div>

      <div className="bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 rounded-2xl shadow-xl p-6 mb-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-2">Team Stats</h2>
        <ul className="grid grid-cols-2 gap-2 text-sm">
          <li>Position: {teamData.position}</li>
          <li>Points: {teamData.points}</li>
          <li>Goal Difference: {teamData.goalDifference}</li>
          <li>Played Games: {teamData.playedGames}</li>
          <li>Wins: {teamData.won}</li>
          <li>Draws: {teamData.draw}</li>
          <li>Losses: {teamData.lost}</li>
        </ul>
      </div>

      <div className="bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 rounded-2xl shadow-xl p-6 mb-6 border border-gray-700">
        <h2 className="text-xl font-semibold mb-3">Last 5 Matches</h2>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left py-2">Date</th>
              <th className="text-left py-2">Match</th>
              <th className="text-left py-2">Score</th>
              <th className="text-left py-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {teamData.last_5_matches.map((m, i) => (
              <tr key={i} className="border-b border-gray-700">
                <td className="py-1">{m.date}</td>
                <td className="py-1">{m.home} vs {m.away}</td>
                <td className="py-1">{m.score}</td>
                <td className={`py-1 ${m.result === "Win" ? "text-green-400" : m.result === "Loss" ? "text-red-400" : "text-yellow-400"}`}>
                  {m.result}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-8">
        <a
          href="/"
          className="text-blue-400 hover:text-blue-300 font-semibold underline underline-offset-2"
        >
          ← Back to Matches
        </a>
      </div>
      </div>
    </div>
  );
}

export default TeamPage;
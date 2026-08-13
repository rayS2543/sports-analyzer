import React, { useState } from "react";
import LeagueSelector from "./components/LeagueSelector";
import StandingsTable from "./components/StandingsTable";
import MatchesTable from "./components/MatchesTable";

export default function App() {
  const [selectedLeague, setSelectedLeague] = useState("PD");
  const [leagues, setLeagues] = useState([]);

  const selectedLeagueName =
    leagues.find((l) => l.code === selectedLeague)?.name || "";

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 text-white p-8">
      <h1 className="text-5xl font-bold text-center mb-12">
        ⚽ Sports Analyzer
      </h1>

      <LeagueSelector
        league={selectedLeague}
        onChange={setSelectedLeague}
        onLeaguesLoaded={setLeagues}
      />

      <div className="flex flex-col gap-12">
        <StandingsTable league={selectedLeague} />
        <MatchesTable league={selectedLeague} leagueName={selectedLeagueName} />
        {/* PredictionsPanel will be added here in a follow-up merge */}
      </div>
    </div>
  );
}

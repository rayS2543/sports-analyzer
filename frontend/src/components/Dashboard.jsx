import React, { useState } from "react";
import TodayGames from "./TodayGames";
import LeagueSelector from "./LeagueSelector";
import StandingsTable from "./StandingsTable";
import MatchesTable from "./MatchesTable";
import PredictionsPanel from "./PredictionsPanel";
import TeamsList from "./TeamsList";

export default function Dashboard() {
  const [selectedLeague, setSelectedLeague] = useState("PD");
  const [leagues, setLeagues] = useState([]);

  const selectedLeagueName =
    leagues.find((l) => l.code === selectedLeague)?.name || "";

  return (
    <>
      <header className="border-b border-slate-800 px-6 sm:px-10 py-5">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
            <span className="text-violet-400">⚽</span> Sports Analyzer
          </h1>
        </div>
      </header>

      <main className="px-6 sm:px-10 py-10 flex flex-col gap-12">
        <TodayGames />

        <section className="max-w-5xl mx-auto w-full flex flex-col gap-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <h2 className="text-lg font-bold text-slate-300 uppercase tracking-wide">League Explorer</h2>
            <LeagueSelector league={selectedLeague} onChange={setSelectedLeague} onLeaguesLoaded={setLeagues} />
          </div>

          <div className="flex flex-col gap-8">
            <StandingsTable league={selectedLeague} />
            <MatchesTable league={selectedLeague} leagueName={selectedLeagueName} />
            <PredictionsPanel league={selectedLeague} />
            <TeamsList league={selectedLeague} />
          </div>
        </section>
      </main>
    </>
  );
}

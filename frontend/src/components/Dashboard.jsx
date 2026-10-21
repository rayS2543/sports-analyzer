import React, { useState } from "react";
import { Link } from "react-router-dom";
import TodayGames from "./TodayGames";
import LeagueSelector from "./LeagueSelector";
import StandingsTable from "./StandingsTable";
import MatchesTable from "./MatchesTable";
import EloRatingsTable from "./EloRatingsTable";
import PredictionsPanel from "./PredictionsPanel";
import TeamsList from "./TeamsList";
import { LEAGUE_NAMES, PageShell } from "./ui";

export default function Dashboard() {
  const [selectedLeague, setSelectedLeague] = useState("PD");
  const [leagues, setLeagues] = useState([]);

  const current = leagues.find((l) => l.code === selectedLeague);
  const selectedLeagueName = current?.name || LEAGUE_NAMES[selectedLeague] || "";

  return (
    <PageShell>
      <TodayGames />

      <section className="flex flex-col gap-8" aria-labelledby="league-heading">
        <div className="flex flex-col gap-4 border-t border-line pt-8">
          <div className="flex items-baseline gap-3">
            <h2 id="league-heading" className="text-2xl sm:text-3xl font-semibold tracking-tight">
              {selectedLeagueName}
            </h2>
            {current?.country && <span className="text-sm text-muted">{current.country}</span>}
          </div>
          <LeagueSelector league={selectedLeague} onChange={setSelectedLeague} onLeaguesLoaded={setLeagues} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-10 gap-y-12">
          <div className="lg:col-span-7 min-w-0">
            <StandingsTable league={selectedLeague} />
          </div>
          <div className="lg:col-span-5 flex flex-col gap-12 min-w-0">
            <MatchesTable league={selectedLeague} leagueName={selectedLeagueName} />
            <PredictionsPanel league={selectedLeague} />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-10 gap-y-6 border-t border-line pt-10">
          <div className="lg:col-span-7 min-w-0">
            <EloRatingsTable league={selectedLeague} compact />
          </div>
          <div className="lg:col-span-5 min-w-0 flex flex-col justify-end gap-3 pb-1">
            <p className="text-sm text-muted leading-relaxed">
              Power rankings from the same Elo model that drives match tips: home advantage, draws,
              and margin of victory included.
            </p>
            <Link
              to={`/elo?league=${selectedLeague}`}
              className="pressable self-start text-sm font-medium text-accent hover:underline"
            >
              Open Elo ratings
            </Link>
          </div>
        </div>

        <TeamsList league={selectedLeague} />
      </section>
    </PageShell>
  );
}

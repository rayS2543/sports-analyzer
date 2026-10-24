import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../apiBase";
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
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setOverview(null);
    setOverviewError(null);

    fetch(`${API_BASE}/dashboard-overview?league=${selectedLeague}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled) return;
        if (data && typeof data === "object" && !Array.isArray(data) && !data.error) {
          setOverview(data);
          if (Array.isArray(data.leagues) && data.leagues.length > 0) {
            setLeagues(data.leagues);
          }
        } else if (data && data.error) {
          setOverviewError(data.error);
        } else {
          setOverviewError("Unexpected overview format");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Error fetching dashboard overview:", err);
        setOverviewError("Could not reach backend");
      });

    return () => {
      cancelled = true;
    };
  }, [selectedLeague]);

  const current = leagues.find((l) => l.code === selectedLeague);
  const selectedLeagueName = overview?.league_name || current?.name || LEAGUE_NAMES[selectedLeague] || "";

  // SWR hydration helper:
  // - If overview loaded: pass cached data
  // - If still loading: pass null (keeps child skeleton up without triggering 7 duplicate fetches)
  // - If overview failed: pass undefined (child falls back to standalone fetch)
  const getInitial = (key) => {
    if (overview) return overview[key];
    if (overviewError) return undefined;
    return null;
  };

  return (
    <PageShell>
      <TodayGames initialMatches={getInitial("today_matches")} />

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
            <StandingsTable league={selectedLeague} initialStandings={getInitial("standings")} />
          </div>
          <div className="lg:col-span-5 flex flex-col gap-12 min-w-0">
            <MatchesTable
              league={selectedLeague}
              leagueName={selectedLeagueName}
              initialMatches={getInitial("matches")}
            />
            <PredictionsPanel
              league={selectedLeague}
              initialPredictions={getInitial("predictions")}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-10 gap-y-6 border-t border-line pt-10">
          <div className="lg:col-span-7 min-w-0">
            <EloRatingsTable
              league={selectedLeague}
              compact
              initialPayload={getInitial("ratings")}
            />
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

        <TeamsList league={selectedLeague} initialTeams={getInitial("teams")} />
      </section>
    </PageShell>
  );
}

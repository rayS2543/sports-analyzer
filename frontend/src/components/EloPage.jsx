import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import EloRatingsTable from "./EloRatingsTable";
import LeagueSelector from "./LeagueSelector";
import PredictionsPanel from "./PredictionsPanel";
import { LEAGUE_NAMES, PageShell } from "./ui";

export default function EloPage() {
  const [params, setParams] = useSearchParams();
  const initial = params.get("league") || "PD";
  const [selectedLeague, setSelectedLeague] = useState(initial);
  const [leagues, setLeagues] = useState([]);

  const current = leagues.find((l) => l.code === selectedLeague);
  const selectedLeagueName = current?.name || LEAGUE_NAMES[selectedLeague] || selectedLeague;

  const onChange = (code) => {
    setSelectedLeague(code);
    setParams(code === "PD" ? {} : { league: code });
  };

  const modelNotes = useMemo(
    () => [
      "Ratings start at 1500 and update after every finished match in the last 90 days.",
      "Home advantage (+65 Elo) is priced into both rating updates and tips.",
      "Blowouts move ratings more than narrow wins; draws peak when teams are close.",
      "Lightweight model: good for relative strength and lean, not betting odds.",
    ],
    []
  );

  return (
    <PageShell back>
      <section className="flex flex-col gap-3 max-w-2xl">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-accent">Elo</p>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Power ratings</h1>
        <p className="text-sm sm:text-base text-muted leading-relaxed">
          Live club strength for {selectedLeagueName}, rebuilt from recent results. Tips below split
          each fixture into home, draw, and away.
        </p>
      </section>

      <div className="flex flex-col gap-4 border-t border-line pt-8">
        <LeagueSelector league={selectedLeague} onChange={onChange} onLeaguesLoaded={setLeagues} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-10 gap-y-12">
        <div className="lg:col-span-7 min-w-0">
          <EloRatingsTable league={selectedLeague} />
        </div>
        <div className="lg:col-span-5 min-w-0 flex flex-col gap-12">
          <PredictionsPanel league={selectedLeague} />
          <section className="flex flex-col gap-3" aria-labelledby="elo-method">
            <h2 id="elo-method" className="text-base font-semibold tracking-tight">
              How it works
            </h2>
            <ul className="flex flex-col gap-2.5 text-sm text-muted leading-relaxed">
              {modelNotes.map((note) => (
                <li key={note} className="pl-3 border-l border-line">
                  {note}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </PageShell>
  );
}

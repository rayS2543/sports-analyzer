import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";
import { EmptyNote, ErrorNote, Section, SkeletonRows, formatDay } from "./ui";

function Prediction({ p }) {
  const homeFav = p.predicted_winner === p.home;
  return (
    <li className="flex flex-col gap-2.5 py-4 border-b border-line/60 last:border-0">
      <div className="flex items-center justify-between text-xs text-faint">
        <time dateTime={p.date}>{formatDay(p.date)}</time>
        <span className="sr-only">Predicted winner: {p.predicted_winner}</span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-sm">
        <div className="flex items-center gap-2 min-w-0">
          <TeamBadge name={p.home} crest={p.home_crest} size="sm" />
          <span className={`truncate ${homeFav ? "font-semibold" : "text-muted"}`}>{p.home}</span>
        </div>
        <span className="text-xs text-faint">vs</span>
        <div className="flex items-center justify-end gap-2 min-w-0">
          <span className={`truncate text-right ${homeFav ? "text-muted" : "font-semibold"}`}>{p.away}</span>
          <TeamBadge name={p.away} crest={p.away_crest} size="sm" />
        </div>
      </div>
      <div className="flex items-center gap-3 text-xs tabular-nums">
        <span className={`w-10 ${homeFav ? "text-accent font-semibold" : "text-muted"}`}>{p.home_win_pct}%</span>
        <div className="flex-1 flex gap-0.5 h-1.5" role="img" aria-label={`${p.home} ${p.home_win_pct}%, ${p.away} ${p.away_win_pct}%`}>
          <div className={`rounded-full ${homeFav ? "bg-accent" : "bg-faint/50"}`} style={{ width: `${p.home_win_pct}%` }} />
          <div className={`rounded-full ${homeFav ? "bg-faint/50" : "bg-accent"}`} style={{ width: `${p.away_win_pct}%` }} />
        </div>
        <span className={`w-10 text-right ${homeFav ? "text-muted" : "text-accent font-semibold"}`}>{p.away_win_pct}%</span>
      </div>
    </li>
  );
}

export default function PredictionsPanel({ league }) {
  const [predictions, setPredictions] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!league) return;

    setError(null);
    setPredictions(null);
    fetch(`${API_BASE}/predictions?league=${league}`)
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
    <Section title="Predictions" aside="Elo model, last 90 days">
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : predictions === null ? (
        <SkeletonRows rows={4} />
      ) : predictions.length === 0 ? (
        <EmptyNote>No upcoming fixtures found.</EmptyNote>
      ) : (
        <ul className="-mt-4">
          {predictions.map((p, idx) => (
            <Prediction key={idx} p={p} />
          ))}
        </ul>
      )}
    </Section>
  );
}

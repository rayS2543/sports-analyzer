import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import TeamBadge from "./TeamBadge";
import { EmptyNote, ErrorNote, Section, SkeletonRows, formatDay } from "./ui";

function resultLabel(p) {
  if (p.predicted_result === "draw") return "Draw most likely";
  if (p.predicted_result === "home") return `${p.home} lean`;
  if (p.predicted_result === "away") return `${p.away} lean`;
  return p.predicted_winner;
}

function OutcomeBar({ p }) {
  const homeFav = p.predicted_result === "home";
  const awayFav = p.predicted_result === "away";
  const drawFav = p.predicted_result === "draw";

  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="flex h-2 rounded-full overflow-hidden bg-raised"
        role="img"
        aria-label={`${p.home} ${p.home_win_pct}%, draw ${p.draw_pct}%, ${p.away} ${p.away_win_pct}%`}
      >
        <div
          className={`h-full transition-[width] duration-500 ease-out ${homeFav ? "bg-accent" : "bg-accent/45"}`}
          style={{ width: `${p.home_win_pct}%` }}
        />
        <div
          className={`h-full transition-[width] duration-500 ease-out ${drawFav ? "bg-muted" : "bg-faint/40"}`}
          style={{ width: `${p.draw_pct}%` }}
        />
        <div
          className={`h-full transition-[width] duration-500 ease-out ${awayFav ? "bg-win" : "bg-win/40"}`}
          style={{ width: `${p.away_win_pct}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[11px] tabular-nums text-muted">
        <span className={homeFav ? "text-accent font-semibold" : ""}>{p.home_win_pct}%</span>
        <span className={drawFav ? "text-fg font-semibold" : ""}>Draw {p.draw_pct}%</span>
        <span className={awayFav ? "text-win font-semibold" : ""}>{p.away_win_pct}%</span>
      </div>
    </div>
  );
}

function Prediction({ p }) {
  return (
    <li className="flex flex-col gap-3 py-4 border-b border-line/60 last:border-0">
      <div className="flex items-center justify-between gap-3 text-xs text-faint">
        <time dateTime={p.date}>{formatDay(p.date)}</time>
        <span className="text-muted">{resultLabel(p)}</span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-sm">
        <div className="flex items-center gap-2 min-w-0">
          <TeamBadge name={p.home} crest={p.home_crest} size="sm" />
          <div className="min-w-0 flex flex-col">
            <span className={`truncate ${p.predicted_result === "home" ? "font-semibold" : "text-muted"}`}>
              {p.home}
            </span>
            {p.home_elo != null && (
              <span className="text-[11px] tabular-nums text-faint">Elo {p.home_elo}</span>
            )}
          </div>
        </div>
        <span className="text-xs text-faint">vs</span>
        <div className="flex items-center justify-end gap-2 min-w-0">
          <div className="min-w-0 flex flex-col items-end">
            <span
              className={`truncate text-right ${p.predicted_result === "away" ? "font-semibold" : "text-muted"}`}
            >
              {p.away}
            </span>
            {p.away_elo != null && (
              <span className="text-[11px] tabular-nums text-faint">Elo {p.away_elo}</span>
            )}
          </div>
          <TeamBadge name={p.away} crest={p.away_crest} size="sm" />
        </div>
      </div>
      <OutcomeBar p={p} />
    </li>
  );
}

export default function PredictionsPanel({ league, initialPredictions }) {
  const [predictions, setPredictions] = useState(initialPredictions ?? null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!league) return;
    if (initialPredictions !== undefined) {
      if (initialPredictions !== null) {
        setPredictions(initialPredictions);
      } else {
        setPredictions(null);
      }
      return;
    }

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
  }, [league, initialPredictions]);

  return (
    <Section title="Match tips" aside="Elo · home / draw / away">
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : predictions === null ? (
        <SkeletonRows rows={4} />
      ) : predictions.length === 0 ? (
        <EmptyNote>No upcoming fixtures found.</EmptyNote>
      ) : (
        <ul className="-mt-4">
          {predictions.map((p, idx) => (
            <Prediction key={`${p.date}-${p.home}-${p.away}-${idx}`} p={p} />
          ))}
        </ul>
      )}
    </Section>
  );
}

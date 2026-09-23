import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import { encodeMatchId } from "../matchId";
import { ErrorNote, EmptyNote, Section, SkeletonRows, formatDay } from "./ui";

function resultOf(m) {
  if (m.winner === "Draw") return "draw";
  return m.winner === m.home ? "home" : "away";
}

export default function MatchesTable({ league, leagueName }) {
  const [matches, setMatches] = useState(null);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    setError(null);
    setMatches(null);
    fetch(`${API_BASE}/matches?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setMatches(data);
        } else {
          setMatches([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching matches:", err);
        setMatches([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <Section title="Recent results">
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : matches === null ? (
        <SkeletonRows rows={5} />
      ) : matches.length === 0 ? (
        <EmptyNote>No results in the last few days.</EmptyNote>
      ) : (
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{leagueName ? `${leagueName} recent results` : "Recent results"}</caption>
          <thead className="sr-only">
            <tr>
              <th>Date</th>
              <th>Teams</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {matches.map((m, idx) => {
              const result = resultOf(m);
              const to = `/match/${encodeMatchId({ league, date: m.date, home: m.home, away: m.away })}`;
              const team = (name, crest, won) => (
                <div className="flex items-center gap-2.5 min-w-0">
                  <TeamBadge name={name} crest={crest} size="sm" />
                  <span className={`truncate ${won ? "font-semibold" : "text-muted"}`}>{name}</span>
                </div>
              );
              return (
                <tr
                  key={idx}
                  data-result={result}
                  onClick={() => navigate(to)}
                  className="border-b border-line/60 last:border-0 cursor-pointer hover:bg-surface transition-colors duration-150"
                >
                  <td className="py-3 pl-1 pr-3 w-16 text-xs text-faint align-middle whitespace-nowrap">
                    <time dateTime={m.date}>{formatDay(m.date, { weekday: false })}</time>
                  </td>
                  <td className="py-3 max-w-0 w-full">
                    <div className="flex flex-col gap-2">
                      {team(m.home, m.home_crest, result === "home")}
                      {team(m.away, m.away_crest, result === "away")}
                    </div>
                  </td>
                  <td className="py-3 pl-3 pr-1 text-right align-middle">
                    <Link
                      to={to}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`${m.home} ${m.score} ${m.away}, match details`}
                      className="inline-block rounded-md bg-raised px-2 py-1 font-semibold tabular-nums whitespace-nowrap"
                    >
                      {m.score}
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Section>
  );
}

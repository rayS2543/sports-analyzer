import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import { ErrorNote, Section, SkeletonRows } from "./ui";

const th = "py-2.5 px-2 font-medium text-faint text-xs";
const td = "py-2.5 px-2 text-center tabular-nums text-muted";

function Delta({ value }) {
  if (value == null || value === 0) {
    return <span className="text-faint">0</span>;
  }
  const positive = value > 0;
  return (
    <span className={positive ? "text-win" : "text-loss"}>
      {positive ? "+" : ""}
      {value}
    </span>
  );
}

export default function EloRatingsTable({ league, compact = false }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!league) return;
    setError(null);
    setPayload(null);
    fetch(`${API_BASE}/ratings?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (data && data.error) {
          setError(data.error);
          setPayload({ ratings: [] });
        } else {
          setPayload(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching Elo ratings:", err);
        setError("Could not reach the Elo service.");
        setPayload({ ratings: [] });
      });
  }, [league]);

  const rows = payload?.ratings ?? null;
  const visible = compact && rows ? rows.slice(0, 8) : rows;
  const aside =
    payload?.matches_used != null
      ? `${payload.matches_used} matches · last ${payload.window_days}d`
      : "Last 90 days";

  return (
    <Section title="Elo ratings" aside={aside}>
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : rows === null ? (
        <SkeletonRows rows={compact ? 8 : 12} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted py-2">No finished matches in the rating window yet.</p>
      ) : (
        <div className="overflow-x-auto -mx-2">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line">
                <th className={`${th} w-8 text-center`}>#</th>
                <th className={`${th} text-left`}>Team</th>
                <th className={`${th} text-center`} title="Matches in window">P</th>
                <th className={`${th} text-center`} title="Change from 1500 baseline">
                  +/-
                </th>
                <th className={`${th} text-center text-fg`}>Elo</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr
                  key={r.team}
                  className="border-b border-line/60 last:border-0 hover:bg-surface transition-colors duration-150"
                >
                  <td className={`${td} text-faint`}>{r.rank}</td>
                  <td className="py-2.5 px-2 max-w-0 w-full">
                    <Link
                      to={`/team/${league}/${encodeURIComponent(r.team)}`}
                      className="flex items-center gap-2.5 font-medium hover:text-accent transition-colors duration-150"
                    >
                      <TeamBadge name={r.team} crest={r.crest} size="sm" />
                      <span className="truncate">{r.team}</span>
                    </Link>
                  </td>
                  <td className={td}>{r.played}</td>
                  <td className={td}>
                    <Delta value={r.delta} />
                  </td>
                  <td className={`${td} text-fg font-semibold`}>{r.rating}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {compact && rows.length > visible.length && (
            <p className="pt-3 text-xs text-muted">
              Showing top {visible.length} of {rows.length}.{" "}
              <Link to={`/elo?league=${league}`} className="text-accent hover:underline">
                Full Elo table
              </Link>
            </p>
          )}
        </div>
      )}
    </Section>
  );
}

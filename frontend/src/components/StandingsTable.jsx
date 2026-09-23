import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import { ErrorNote, Section, SkeletonRows } from "./ui";

const th = "py-2.5 px-2 font-medium text-faint text-xs";
const td = "py-2.5 px-2 text-center tabular-nums text-muted";

export default function StandingsTable({ league }) {
  const [standings, setStandings] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    setStandings(null);
    fetch(`${API_BASE}/standings?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setStandings(data);
        } else {
          setStandings([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching standings:", err);
        setStandings([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <Section title="Table">
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : standings === null ? (
        <SkeletonRows rows={10} />
      ) : (
        <div className="overflow-x-auto -mx-2">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line">
                <th className={`${th} w-8 text-center`}>#</th>
                <th className={`${th} text-left`}>Team</th>
                <th className={`${th} text-center`} title="Played">P</th>
                <th className={`${th} text-center`} title="Won">W</th>
                <th className={`${th} text-center`} title="Drawn">D</th>
                <th className={`${th} text-center`} title="Lost">L</th>
                <th className={`${th} text-center hidden sm:table-cell`} title="Goals for">GF</th>
                <th className={`${th} text-center hidden sm:table-cell`} title="Goals against">GA</th>
                <th className={`${th} text-center`} title="Goal difference">GD</th>
                <th className={`${th} text-center text-fg`}>Pts</th>
              </tr>
            </thead>
            <tbody>
              {standings.map((s, idx) => (
                <tr key={idx} className="border-b border-line/60 last:border-0 hover:bg-surface transition-colors duration-150">
                  <td className={`${td} text-faint`}>{s.position}</td>
                  <td className="py-2.5 px-2 max-w-0 w-full">
                    <Link
                      to={`/team/${league}/${encodeURIComponent(s.team_name)}`}
                      className="flex items-center gap-2.5 font-medium hover:text-accent transition-colors duration-150"
                    >
                      <TeamBadge name={s.team_name} tla={s.tla} crest={s.crest} size="sm" />
                      <span className="truncate">{s.team_name}</span>
                    </Link>
                  </td>
                  <td className={td}>{s.playedGames}</td>
                  <td className={td}>{s.won}</td>
                  <td className={td}>{s.draw}</td>
                  <td className={td}>{s.lost}</td>
                  <td className={`${td} hidden sm:table-cell`}>{s.goalsFor}</td>
                  <td className={`${td} hidden sm:table-cell`}>{s.goalsAgainst}</td>
                  <td className={td}>{s.goalDifference > 0 ? `+${s.goalDifference}` : s.goalDifference}</td>
                  <td className={`${td} text-fg font-semibold`}>{s.points}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

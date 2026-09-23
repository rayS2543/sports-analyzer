import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import { ErrorNote, Section } from "./ui";

export default function TeamsList({ league }) {
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    fetch(`${API_BASE}/teams?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setTeams(data);
        } else {
          setTeams([]);
          setError(data.error || "Unexpected response from server");
        }
      })
      .catch((err) => {
        console.error("Error fetching teams:", err);
        setTeams([]);
        setError("Could not reach the backend");
      });
  }, [league]);

  return (
    <Section title="Clubs" aside={teams.length > 0 ? `${teams.length} teams` : null}>
      {error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : (
        <ul className="grid grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-3 gap-y-1">
          {teams.map((team) => (
            <li key={team.tla}>
              <Link
                to={`/team/${league}/${encodeURIComponent(team.name)}`}
                className="pressable flex items-center gap-3 rounded-lg px-2 py-2 -mx-2 hover:bg-surface"
              >
                <TeamBadge name={team.name} tla={team.tla} crest={team.crest} size="md" />
                <span className="flex-1 min-w-0 truncate text-sm font-medium">{team.shortName || team.name}</span>
                <span className="text-xs text-faint tabular-nums">{team.tla}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

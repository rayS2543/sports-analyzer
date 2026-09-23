import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";

export default function LeagueSelector({ league, onChange, onLeaguesLoaded }) {
  const [leagues, setLeagues] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/leagues`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setLeagues(data);
          if (onLeaguesLoaded) onLeaguesLoaded(data);
        } else {
          setError(data.error || "Failed to load leagues");
        }
      })
      .catch((err) => {
        console.error("Error fetching leagues:", err);
        setError("Could not reach the backend");
      });
  }, []);

  if (error) return <p className="text-sm text-loss">{error}</p>;

  return (
    <nav aria-label="Choose league" className="-mx-4 px-4 sm:mx-0 sm:px-0 overflow-x-auto [scrollbar-width:none]">
      <ul className="flex gap-6 border-b border-line min-w-max">
        {leagues.map((l) => {
          const active = l.code === league;
          return (
            <li key={l.code}>
              <button
                type="button"
                aria-current={active ? "true" : undefined}
                onClick={() => onChange(l.code)}
                className={`relative h-10 text-sm font-medium transition-colors duration-150 ${
                  active ? "text-fg" : "text-muted hover:text-fg"
                }`}
              >
                {l.name}
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent transition-transform duration-200 ease-out origin-center ${
                    active ? "scale-x-100" : "scale-x-0"
                  }`}
                />
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

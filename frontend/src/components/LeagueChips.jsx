import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";

export const chipClasses = (active) =>
  `pressable shrink-0 rounded-full px-3.5 h-8 text-sm font-medium border whitespace-nowrap ${
    active
      ? "bg-accent border-accent text-accent-fg"
      : "border-line text-muted hover:text-fg hover:border-faint"
  }`;

export default function LeagueChips({ selected, onChange }) {
  const [leagues, setLeagues] = useState([]);

  useEffect(() => {
    fetch(`${API_BASE}/leagues`)
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) setLeagues(data);
      })
      .catch((err) => console.error("Error fetching leagues:", err));
  }, []);

  const allSelected = selected.length === 0;

  const toggle = (code) => {
    if (selected.includes(code)) {
      onChange(selected.filter((c) => c !== code));
    } else {
      onChange([...selected, code]);
    }
  };

  return (
    <div className="flex gap-2 overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 sm:flex-wrap [scrollbar-width:none]" role="group" aria-label="Filter by league">
      <button type="button" aria-pressed={allSelected} onClick={() => onChange([])} className={chipClasses(allSelected)}>
        All
      </button>
      {leagues.map((l) => {
        const active = !allSelected && selected.includes(l.code);
        return (
          <button key={l.code} type="button" aria-pressed={active} onClick={() => toggle(l.code)} className={chipClasses(active)}>
            {l.name}
          </button>
        );
      })}
    </div>
  );
}

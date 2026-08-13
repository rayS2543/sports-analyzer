import React, { useEffect, useState } from "react";

export default function LeagueChips({ selected, onChange }) {
  const [leagues, setLeagues] = useState([]);

  useEffect(() => {
    fetch("http://127.0.0.1:5000/leagues")
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

  const chipClasses = (active) =>
    `rounded-full px-4 py-1.5 text-sm font-semibold border transition-colors ${
      active
        ? "bg-violet-600 border-violet-500 text-white"
        : "bg-slate-900 border-slate-700 text-slate-300 hover:border-slate-500"
    }`;

  return (
    <div className="flex flex-wrap gap-2">
      <button onClick={() => onChange([])} className={chipClasses(allSelected)}>
        All
      </button>
      {leagues.map((l) => (
        <button key={l.code} onClick={() => toggle(l.code)} className={chipClasses(!allSelected && selected.includes(l.code))}>
          {l.name}
        </button>
      ))}
    </div>
  );
}

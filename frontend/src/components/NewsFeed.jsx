import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { EmptyNote, ErrorNote, SkeletonRows } from "./ui";

export default function NewsFeed({ teams }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const key = teams.join(",");

  useEffect(() => {
    if (!teams.length) {
      setItems([]);
      return;
    }
    setItems(null);
    setError(null);
    fetch(`${API_BASE}/news/teams?teams=${encodeURIComponent(key)}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error && !data.items?.length) {
          setError(data.error);
        }
        setItems(data.items || []);
      })
      .catch((err) => {
        console.error("Error fetching team news:", err);
        setError("Could not reach the backend");
        setItems([]);
      });
  }, [key]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (items === null) return <SkeletonRows rows={4} />;
  if (items.length === 0) return <EmptyNote>No recent news found.</EmptyNote>;

  return (
    <ul className="flex flex-col">
      {items.map((a, idx) => (
        <li key={idx} className="flex items-baseline gap-4 py-3 border-b border-line/60 last:border-0 text-sm">
          <a href={a.link} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate font-medium text-fg hover:text-accent">
            {a.title}
          </a>
          {teams.length > 1 && <span className="shrink-0 text-xs text-faint">{a.team_name}</span>}
        </li>
      ))}
    </ul>
  );
}

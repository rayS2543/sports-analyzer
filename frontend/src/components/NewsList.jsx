import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { EmptyNote, SkeletonRows } from "./ui";

export default function NewsList({ query }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!query) return;
    setLoading(true);
    fetch(`${API_BASE}/news?query=${encodeURIComponent(query)}`)
      .then((res) => res.json())
      .then((data) => setItems(data.items || []))
      .catch((err) => {
        console.error("Error fetching news:", err);
        setItems([]);
      })
      .finally(() => setLoading(false));
  }, [query]);

  if (loading) return <SkeletonRows rows={3} />;
  if (items.length === 0) return <EmptyNote>No headlines found.</EmptyNote>;

  return (
    <ul className="flex flex-col">
      {items.map((n, idx) => (
        <li key={idx} className="border-b border-line/60 last:border-0">
          <a
            href={n.link}
            target="_blank"
            rel="noreferrer"
            className="group flex flex-col gap-1 py-3.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6"
          >
            <span className="font-medium group-hover:text-accent group-hover:underline transition-colors duration-150 max-w-[65ch]">
              {n.title}
            </span>
            {n.source && <span className="text-xs text-faint shrink-0">{n.source}</span>}
          </a>
        </li>
      ))}
    </ul>
  );
}

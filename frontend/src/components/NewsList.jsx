import React, { useEffect, useState } from "react";

export default function NewsList({ query }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!query) return;
    setLoading(true);
    fetch(`http://127.0.0.1:5000/news?query=${encodeURIComponent(query)}`)
      .then((res) => res.json())
      .then((data) => setItems(data.items || []))
      .catch((err) => {
        console.error("Error fetching news:", err);
        setItems([]);
      })
      .finally(() => setLoading(false));
  }, [query]);

  if (loading) return <p className="text-slate-400">Loading headlines...</p>;
  if (items.length === 0) return <p className="text-slate-400">No headlines found.</p>;

  return (
    <ul className="flex flex-col gap-3">
      {items.map((n, idx) => (
        <li key={idx}>
          <a href={n.link} target="_blank" rel="noreferrer" className="text-violet-400 hover:text-violet-300 font-medium">
            {n.title}
          </a>
          {n.source && <span className="text-xs text-slate-500 ml-2">{n.source}</span>}
        </li>
      ))}
    </ul>
  );
}

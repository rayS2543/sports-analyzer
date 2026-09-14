import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";

function FormBadge({ result }) {
  const color =
    result === "W" ? "bg-emerald-500" : result === "L" ? "bg-rose-500" : "bg-amber-500";
  return <span className={`w-6 h-6 rounded-full ${color} text-xs font-bold flex items-center justify-center`}>{result}</span>;
}

export default function TeamDetailPage() {
  const { league, name } = useParams();
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setForm(null);
    setError(null);
    fetch(`${API_BASE}/analytics/form/${encodeURIComponent(name)}?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setError(data.error);
        } else {
          setForm(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching team form:", err);
        setError("Could not reach the backend");
      });
  }, [league, name]);

  return (
    <>
      <header className="border-b border-slate-800 px-6 sm:px-10 py-5">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-violet-400 font-semibold hover:text-violet-300">
            ← Back to Sports Analyzer
          </Link>
        </div>
      </header>

      <main className="px-6 sm:px-10 py-10 flex flex-col gap-8 max-w-5xl mx-auto w-full">
        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20 flex items-center gap-5">
          <TeamBadge name={decodeURIComponent(name)} size="lg" />
          <h1 className="text-2xl font-bold">{decodeURIComponent(name)}</h1>
        </section>

        {error && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <p className="text-rose-400 font-semibold">{error}</p>
          </section>
        )}

        {!error && !form && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <p className="text-slate-400">Loading form...</p>
          </section>
        )}

        {!error && form && (
          <>
            <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
              <h2 className="text-xl font-bold mb-4">Recent Form</h2>
              <div className="flex items-center gap-4">
                <div className="flex gap-1">
                  {form.form.split("").map((r, idx) => (
                    <FormBadge key={idx} result={r} />
                  ))}
                </div>
                <span className="text-slate-400">
                  {form.points} points from last {form.matches_considered} matches
                </span>
              </div>
            </section>

            <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
              <h2 className="text-xl font-bold mb-4">Match History</h2>
              <div className="flex flex-col divide-y divide-slate-800">
                {form.matches.map((m, idx) => (
                  <div key={idx} className="flex items-center justify-between py-3">
                    <span className="text-slate-400 text-sm">{m.date}</span>
                    <span className="font-semibold">
                      {m.home} {m.score} {m.away}
                    </span>
                    <span
                      className={`font-bold text-sm ${
                        m.winner === "Draw" ? "text-amber-400" : "text-emerald-400"
                      }`}
                    >
                      {m.winner === "Draw" ? "Draw" : `${m.winner} won`}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}

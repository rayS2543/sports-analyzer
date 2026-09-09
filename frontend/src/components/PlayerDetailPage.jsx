import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import NewsList from "./NewsList";

function Stat({ label, value, accent = "text-white" }) {
  return (
    <div className="bg-slate-800/60 rounded-xl p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent}`}>{value ?? "-"}</p>
    </div>
  );
}

export default function PlayerDetailPage() {
  const { id } = useParams();
  const [player, setPlayer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setPlayer(null);
    setError(null);
    fetch(`http://127.0.0.1:5000/players/${id}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setError(data.error);
        } else {
          setPlayer(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching player:", err);
        setError("Could not reach the backend");
      });
  }, [id]);

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
        {error && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <p className="text-rose-400 font-semibold">{error}</p>
          </section>
        )}

        {!error && !player && (
          <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
            <p className="text-slate-400">Loading player...</p>
          </section>
        )}

        {!error && player && (
          <>
            <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20 flex items-center gap-5">
              {player.photo ? (
                <img
                  src={player.photo}
                  alt={player.name}
                  className="w-20 h-20 rounded-full object-cover border border-slate-700"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <TeamBadge name={player.name} size="lg" />
              )}
              <div>
                <h1 className="text-2xl font-bold">{player.name}</h1>
                <p className="text-slate-400">
                  {[player.position, player.current_team, player.nationality].filter(Boolean).join(" · ")}
                </p>
              </div>
            </section>

            <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
              <h2 className="text-xl font-bold mb-6">{player.season} Season Stats</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <Stat label="Appearances" value={player.appearances} />
                <Stat label="Goals" value={player.goals} />
                <Stat label="Assists" value={player.assists} />
                <Stat label="Rating" value={player.rating} accent="text-violet-300" />
                <Stat label="Yellow Cards" value={player.yellow_cards} accent="text-amber-400" />
                <Stat label="Red Cards" value={player.red_cards} accent="text-rose-400" />
              </div>
            </section>
          </>
        )}

        <section className="bg-slate-900/70 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-lg shadow-black/20">
          <h2 className="text-xl font-bold mb-4">Recent Headlines</h2>
          {player && <NewsList query={player.name} />}
        </section>
      </main>
    </>
  );
}

import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import NewsList from "./NewsList";
import { ErrorNote, PageShell, Section, SkeletonRows } from "./ui";

function Stat({ label, value, tone = "text-fg" }) {
  return (
    <div className="flex flex-col gap-1 bg-surface px-4 py-4">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className={`text-2xl font-semibold tabular-nums tracking-tight ${tone}`}>{value ?? "-"}</dd>
    </div>
  );
}

function PlayerPhoto({ player }) {
  const [failed, setFailed] = useState(false);
  if (!player.photo || failed) return <TeamBadge name={player.name} size="xl" />;
  return (
    <img
      src={player.photo}
      alt={player.name}
      className="w-20 h-20 rounded-xl object-cover bg-raised ring-1 ring-line"
      onError={() => setFailed(true)}
    />
  );
}

export default function PlayerDetailPage() {
  const { id } = useParams();
  const [player, setPlayer] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setPlayer(null);
    setError(null);
    fetch(`${API_BASE}/players/${id}`)
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
    <PageShell back>
      {error && <ErrorNote>{error}</ErrorNote>}

      {!error && !player && <SkeletonRows rows={4} />}

      {!error && player && (
        <>
          <section className="flex items-center gap-5">
            <PlayerPhoto player={player} />
            <div className="flex flex-col gap-1 min-w-0">
              <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">{player.name}</h1>
              <p className="text-sm text-muted">
                {[player.position, player.current_team, player.nationality].filter(Boolean).join(", ")}
              </p>
            </div>
          </section>

          <Section title={`${player.season} season`}>
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line">
              <Stat label="Appearances" value={player.appearances} />
              <Stat label="Goals" value={player.goals} />
              <Stat label="Assists" value={player.assists} />
              <Stat label="Average rating" value={player.rating} tone="text-accent" />
              <Stat label="Yellow cards" value={player.yellow_cards} />
              <Stat label="Red cards" value={player.red_cards} tone={player.red_cards > 0 ? "text-loss" : "text-fg"} />
            </dl>
          </Section>
        </>
      )}

      {player && (
        <Section title="Recent headlines">
          <NewsList query={player.name} />
        </Section>
      )}
    </PageShell>
  );
}

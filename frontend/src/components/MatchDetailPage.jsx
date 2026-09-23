import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import NewsList from "./NewsList";
import { decodeMatchId } from "../matchId";
import { EmptyNote, ErrorNote, LEAGUE_NAMES, PageShell, Section, SkeletonRows, formatDay } from "./ui";

function PlayerRow({ player, expanded, onToggle }) {
  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={`pressable w-full flex items-center gap-3 text-left px-2 py-2 rounded-lg text-sm ${
          expanded ? "bg-raised" : "hover:bg-surface"
        }`}
      >
        <span className="text-xs text-faint w-5 text-right tabular-nums shrink-0">{player.number ?? ""}</span>
        <span className="font-medium flex-1 truncate">{player.name}</span>
        {player.goals > 0 && <span className="text-xs text-fg tabular-nums">{player.goals > 1 ? `${player.goals} goals` : "Goal"}</span>}
        {player.red_cards > 0 && <span className="w-2 h-3 rounded-[2px] bg-loss" title="Red card" />}
        {player.yellow_cards > 0 && !player.red_cards && <span className="w-2 h-3 rounded-[2px] bg-accent" title="Yellow card" />}
        <span className="text-xs text-faint w-4 text-center">{player.position}</span>
      </button>
      {expanded && (
        <div className="ml-10 mr-2 mt-1 mb-2 flex flex-col gap-2 text-sm">
          <dl className="grid grid-cols-4 gap-2">
            {[
              ["Rating", player.rating ?? "-", "text-accent"],
              ["Minutes", player.minutes ?? "-"],
              ["Goals", player.goals],
              ["Assists", player.assists],
            ].map(([label, value, tone]) => (
              <div key={label}>
                <dt className="text-xs text-faint">{label}</dt>
                <dd className={`font-semibold tabular-nums ${tone || ""}`}>{value}</dd>
              </div>
            ))}
          </dl>
          {player.profile_id && (
            <Link to={`/player/${player.profile_id}`} className="self-start text-accent font-medium hover:underline">
              Full profile <span aria-hidden="true">→</span>
            </Link>
          )}
        </div>
      )}
    </li>
  );
}

function PlayerGroup({ label, players, expandedPlayer, onTogglePlayer }) {
  return (
    <div className="flex flex-col gap-1">
      <h4 className="text-xs font-medium text-faint px-2 mb-1">{label}</h4>
      <ul className="flex flex-col">
        {players.map((p) => (
          <PlayerRow
            key={p.id ?? `${p.name}-${p.number}`}
            player={p}
            expanded={expandedPlayer === p.id}
            onToggle={() => onTogglePlayer(p.id)}
          />
        ))}
      </ul>
    </div>
  );
}

function TeamLineup({ team, expandedPlayer, onTogglePlayer }) {
  if (!team) return null;
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-3">
        <h3 className="font-semibold truncate">{team.team_name}</h3>
        <span className="text-sm text-muted tabular-nums shrink-0">{team.formation || "-"}</span>
      </div>
      <PlayerGroup label="Starting XI" players={team.starters} expandedPlayer={expandedPlayer} onTogglePlayer={onTogglePlayer} />
      {team.bench.length > 0 && (
        <PlayerGroup label="Bench" players={team.bench} expandedPlayer={expandedPlayer} onTogglePlayer={onTogglePlayer} />
      )}
    </div>
  );
}

export default function MatchDetailPage() {
  const { id } = useParams();
  const { league, date, home, away } = decodeMatchId(id);

  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(null);
  const [expandedPlayer, setExpandedPlayer] = useState(null);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    const query = new URLSearchParams({ league, date, home, away });
    fetch(`${API_BASE}/matches/detail?${query}`)
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setDetailError(data.error);
        } else {
          setDetail(data);
        }
      })
      .catch((err) => {
        console.error("Error fetching match detail:", err);
        setDetailError("Could not reach the backend");
      });
  }, [league, date, home, away]);

  const togglePlayer = (playerId) => setExpandedPlayer((current) => (current === playerId ? null : playerId));

  return (
    <PageShell back>
      <section className="flex flex-col items-center gap-6 pt-4 text-center">
        <p className="text-sm text-muted">
          {LEAGUE_NAMES[league] || league}
          {date && <> &middot; {formatDay(date)}</>}
        </p>
        <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-4 sm:gap-10 w-full max-w-2xl">
          <div className="flex flex-col items-center gap-3 min-w-0">
            <TeamBadge name={home} size="xl" />
            <h1 className="text-lg sm:text-2xl font-semibold tracking-tight">{home}</h1>
          </div>
          <span className="pt-7 text-faint text-sm">vs</span>
          <div className="flex flex-col items-center gap-3 min-w-0">
            <TeamBadge name={away} size="xl" />
            <h2 className="text-lg sm:text-2xl font-semibold tracking-tight">{away}</h2>
          </div>
        </div>
      </section>

      <Section title="Lineups">
        {detailError && <ErrorNote>{detailError}</ErrorNote>}
        {!detailError && !detail && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            <SkeletonRows rows={8} />
            <SkeletonRows rows={8} />
          </div>
        )}
        {!detailError && detail && !detail.available && <EmptyNote>{detail.reason || "Lineup not available for this match."}</EmptyNote>}
        {!detailError && detail && detail.available && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-12">
            <TeamLineup team={detail.home} expandedPlayer={expandedPlayer} onTogglePlayer={togglePlayer} />
            <TeamLineup team={detail.away} expandedPlayer={expandedPlayer} onTogglePlayer={togglePlayer} />
          </div>
        )}
      </Section>

      <Section title="Recent headlines">
        <NewsList query={`${home} vs ${away}`} />
      </Section>
    </PageShell>
  );
}

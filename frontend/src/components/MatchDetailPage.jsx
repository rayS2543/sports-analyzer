import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import TeamBadge from "./TeamBadge";
import ShotMap, { FormationPitch } from "./MatchPitch";
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

function TeamLineup({ team, side, expandedPlayer, onTogglePlayer }) {
  if (!team) return null;
  const hasPitch = team.starters.length === 11 && team.starters.every((player) => player.pitch_position);
  const selected = team.starters.find((player) => player.id === expandedPlayer);
  return (
    <div className="flex flex-col gap-4 min-w-0">
      <div className="flex items-baseline justify-between gap-3 border-b border-line pb-3">
        <h3 className="font-semibold truncate">{team.team_name}</h3>
        <span className="text-sm text-muted tabular-nums shrink-0">{team.formation || "-"}</span>
      </div>
      {hasPitch ? <>
        <FormationPitch team={team} side={side} selectedPlayer={expandedPlayer} onSelect={onTogglePlayer} />
        <p className="text-xs text-muted">Starting XI · club-color kits · select a player</p>
        {selected && <ul><PlayerRow player={selected} expanded onToggle={() => onTogglePlayer(selected.id)} /></ul>}
      </> : <>
        <EmptyNote>Pitch positions unavailable. Starting XI listed below.</EmptyNote>
        <PlayerGroup label="Starting XI" players={team.starters} expandedPlayer={expandedPlayer} onTogglePlayer={onTogglePlayer} />
      </>}
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
  const [side, setSide] = useState("home");

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setExpandedPlayer(null);
    setSide("home");
    const controller = new AbortController();
    const query = new URLSearchParams({ league, date, home, away });
    fetch(`${API_BASE}/matches/detail?${query}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setDetailError(data.error);
        } else {
          setDetail(data);
        }
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("Error fetching match detail:", err);
        setDetailError("Could not reach the backend");
      });
    return () => controller.abort();
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
            <TeamBadge name={home} crest={detail?.home?.crest} size="xl" />
            <h1 className="text-lg sm:text-2xl font-semibold tracking-tight">{home}</h1>
          </div>
          <span className="pt-7 text-faint text-sm">vs</span>
          <div className="flex flex-col items-center gap-3 min-w-0">
            <TeamBadge name={away} crest={detail?.away?.crest} size="xl" />
            <h2 className="text-lg sm:text-2xl font-semibold tracking-tight">{away}</h2>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.5fr)] gap-8 lg:gap-10 items-start">
      <Section title="Formations & lineups">
        {detailError && <ErrorNote>{detailError}</ErrorNote>}
        {!detailError && !detail && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
            <SkeletonRows rows={8} />
            <SkeletonRows rows={8} />
          </div>
        )}
        {!detailError && detail && !detail.available && <EmptyNote>{detail.reason || "Lineup not available for this match."}</EmptyNote>}
        {!detailError && detail && detail.available && (
          <>
            <div className="flex rounded-lg bg-surface p-1 border border-line" role="group" aria-label="Lineup team">
              {["home", "away"].map((value) => <button key={value} type="button" aria-pressed={side === value} onClick={() => { setSide(value); setExpandedPlayer(null); }} className={`pressable flex-1 min-w-0 px-2 py-3 rounded-md text-sm font-medium ${side === value ? "bg-raised text-fg" : "text-muted"}`}>
                <span className="inline-flex items-center justify-center gap-2"><TeamBadge name={value === "home" ? home : away} crest={detail[value].crest} size="sm" /><span>{detail[value].team_name}</span></span>
              </button>)}
            </div>
            <TeamLineup team={detail[side]} side={side} expandedPlayer={expandedPlayer} onTogglePlayer={togglePlayer} />
          </>
        )}
      </Section>
      <Section title="Shot map" aside="Chance by chance">
        {detailError ? <ErrorNote>{detailError}</ErrorNote> : !detail ? <SkeletonRows rows={8} /> : detail.available ? <ShotMap key={id} shots={detail.shots} home={detail.home} away={detail.away} /> : <EmptyNote>Shot map not available for this match yet.</EmptyNote>}
        {detail?.available && <p className="text-xs text-faint">Match data and formations via FotMob.</p>}
      </Section>
      </div>

      <Section title="Recent headlines">
        <NewsList query={`${home} vs ${away}`} />
      </Section>
    </PageShell>
  );
}

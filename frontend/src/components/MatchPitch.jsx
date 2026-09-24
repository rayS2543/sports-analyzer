import React, { useId, useState } from "react";
import { EmptyNote } from "./ui";

export const TEAM_COLORS = { home: "#f4a08b", away: "#92c9ec" };

function PlayerShirt({ team, player, side }) {
  const patternId = useId();
  // These are club-color illustrations, not verified match-specific kit designs.
  const keeper = player.position === "GK";
  const striped = !keeper && team.id === 9906;
  const base = keeper ? "#8d9f96" : team.id === 8633 || striped ? "#fafaf7" : team.color || TEAM_COLORS[side];
  const hex = /^#[0-9a-f]{6}$/i.test(base) ? base.slice(1) : "ffffff";
  const brightness = [0, 2, 4].reduce((total, offset, index) => total + parseInt(hex.slice(offset, offset + 2), 16) * [0.299, 0.587, 0.114][index], 0);
  return <span className="player-shirt" style={{ color: base }}>
    <svg viewBox="0 0 48 44" aria-hidden="true">
      {striped && <defs><pattern id={patternId} width="12" height="44" patternUnits="userSpaceOnUse"><rect width="12" height="44" fill="#fafaf7" /><rect width="6" height="44" fill="#c63527" /></pattern></defs>}
      <path d="M15 3L3 10l5 12 7-3v22h18V19l7 3 5-12-12-7c-3 7-15 7-18 0Z" fill={striped ? `url(#${patternId})` : "currentColor"} stroke="#d1d9d4" strokeWidth="0.75" />
      <path d="M15 3c3 7 15 7 18 0" fill="none" stroke={keeper ? "#37483f" : "#24374b"} strokeWidth="1.5" />
    </svg>
    <span className={`shirt-number ${striped ? "striped-shirt-number" : ""}`} style={{ color: brightness > 155 ? "#17241e" : "#ffffff" }}>{player.number ?? "–"}</span>
    {player.captain && <span className="captain-mark">C</span>}
  </span>;
}

export function PitchLines({ vertical = false }) {
  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox={vertical ? "0 0 68 105" : "0 0 105 68"} preserveAspectRatio="none" fill="none" aria-hidden="true">
      <g transform={vertical ? "translate(0 105) rotate(-90)" : undefined} stroke="currentColor" strokeWidth="0.25">
        <path d="M0 0H105V68H0Z M52.5 0V68 M0 13.84H16.5V54.16H0 M105 13.84H88.5V54.16H105 M0 24.84H5.5V43.16H0 M105 24.84H99.5V43.16H105" />
        <circle cx="52.5" cy="34" r="9.15" />
        <path d="M16.5 26.69a9.15 9.15 0 0 1 0 14.62 M88.5 26.69a9.15 9.15 0 0 0 0 14.62" />
        <g fill="currentColor" stroke="none"><circle cx="11" cy="34" r="0.4" /><circle cx="94" cy="34" r="0.4" /><circle cx="52.5" cy="34" r="0.4" /></g>
      </g>
    </svg>
  );
}

export function FormationPitch({ team, side, selectedPlayer, onSelect }) {
  const players = team.starters || [];
  if (players.length !== 11 || players.some((player) => !player.pitch_position)) return null;
  return (
    <div className="football-pitch formation-pitch" aria-label={`${team.team_name} starting formation ${team.formation || ""}`}>
      <PitchLines vertical />
      {players.map((player) => (
        <button
          key={player.id}
          type="button"
          className="formation-player"
          style={{ left: `${(1 - player.pitch_position.x) * 100}%`, top: `${(1 - player.pitch_position.y) * 100}%`, "--team-color": TEAM_COLORS[side] }}
          onClick={() => onSelect(player.id)}
          aria-label={`${player.name}, number ${player.number ?? "unknown"}${player.captain ? ", captain" : ""}${player.rating != null ? `, rating ${player.rating}` : ""}`}
          aria-pressed={selectedPlayer === player.id}
          title={player.name}
        >
          <PlayerShirt team={team} player={player} side={side} />
          <span className="player-pitch-name">{player.name}</span>
          <span className="player-pitch-meta">
            {player.rating != null && <span>{Number(player.rating).toFixed(1)}</span>}
            {player.goals > 0 && <span aria-label={`${player.goals} goals`}>⚽{player.goals > 1 ? player.goals : ""}</span>}
            {player.red_cards > 0 ? <span className="pitch-card bg-loss" aria-label="Red card" /> : player.yellow_cards > 0 && <span className="pitch-card bg-accent" aria-label="Yellow card" />}
          </span>
        </button>
      ))}
    </div>
  );
}

export function shotOutcome(shot) {
  if (shot.isOwnGoal) return "Own goal";
  if (shot.eventType === "Goal") return "Goal";
  if (shot.isBlocked) return "Blocked";
  if (shot.eventType === "AttemptSaved" || shot.isOnTarget) return "Saved";
  if (shot.eventType === "Post") return "Woodwork";
  return "Off target";
}

const shotMinute = (shot) => `${shot.min ?? "–"}${shot.minAdded ? `+${shot.minAdded}` : ""}′`;
const words = (text) => text?.replace(/([a-z])([A-Z])/g, "$1 $2") || "–";

export default function ShotMap({ shots, home, away }) {
  const [teamFilter, setTeamFilter] = useState("all");
  const [period, setPeriod] = useState("all");
  const [player, setPlayer] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  if (!shots) return <EmptyNote>Shot map not available for this match yet.</EmptyNote>;
  if (!shots.length) return <EmptyNote>No shots recorded for this match yet.</EmptyNote>;

  const teamShots = shots.filter((shot) => teamFilter === "all" || String(shot.teamId) === teamFilter);
  const players = [...new Map(teamShots.map((shot) => [String(shot.playerId), shot.playerName])).entries()];
  const visible = teamShots.filter((shot) => (period === "all" || shot.period === period) && (player === "all" || String(shot.playerId) === player));
  const selected = visible.find((shot) => shot.id === selectedId);
  const selectedIndex = selected ? visible.indexOf(selected) : -1;
  const color = (shot) => TEAM_COLORS[shot.teamId === home.id ? "home" : "away"];
  const changeFilter = (setter, value) => { setter(value); setSelectedId(null); };

  return (
    <div className="flex flex-col gap-5">
      <div className="shot-filters">
        <label>Team<select aria-label="Team" value={teamFilter} onChange={(e) => { changeFilter(setTeamFilter, e.target.value); setPlayer("all"); }}>
          <option value="all">Both teams</option><option value={home.id}>{home.team_name}</option><option value={away.id}>{away.team_name}</option>
        </select></label>
        <label>Period<select aria-label="Period" value={period} onChange={(e) => changeFilter(setPeriod, e.target.value)}>
          <option value="all">All periods</option>
          {[...new Set(shots.map((shot) => shot.period).filter(Boolean))].map((value) => <option key={value} value={value}>{words(value)}</option>)}
        </select></label>
        <label>Player<select aria-label="Player" value={player} onChange={(e) => changeFilter(setPlayer, e.target.value)}>
          <option value="all">All players</option>{players.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select></label>
      </div>
      <div className="flex justify-between gap-4 text-xs text-muted">
        <span><span style={{ color: TEAM_COLORS.home }}>●</span> {home.team_name} →</span>
        <span className="text-right">← {away.team_name} <span style={{ color: TEAM_COLORS.away }}>●</span></span>
      </div>
      <div className="football-pitch shot-pitch" aria-label="Shot locations">
        <PitchLines />
        {visible.map((shot) => {
          // FotMob normalizes shots toward x=105 on a 105 × 68 metre pitch.
          // Rotate away shots so the teams attack opposite ends.
          const isHome = shot.teamId === home.id;
          const goal = shot.eventType === "Goal" || shot.isOwnGoal;
          const size = 9 + Math.sqrt(Math.max(0, Math.min(1, shot.expectedGoals || 0))) * 17;
          return (
            <button
              key={shot.id}
              type="button"
              className="shot-marker"
              style={{ left: `${(isHome ? shot.x : 105 - shot.x) / 105 * 100}%`, top: `${(isHome ? shot.y : 68 - shot.y) / 68 * 100}%`, "--team-color": color(shot), "--shot-size": `${size}px` }}
              data-goal={goal}
              data-selected={selected?.id === shot.id}
              aria-pressed={selected?.id === shot.id}
              aria-label={`${shot.playerName}, ${shotMinute(shot)}, ${shotOutcome(shot)}`}
              title={`${shot.playerName} · ${shotMinute(shot)} · ${shotOutcome(shot)}`}
              onClick={() => setSelectedId(shot.id)}
            ><span>{goal ? "★" : shot.isBlocked ? "×" : shot.isOnTarget ? "•" : ""}</span></button>
          );
        })}
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-xs text-muted">
        <span>★ Goal &nbsp; • Saved &nbsp; ○ Off target &nbsp; × Blocked</span><span>Dot size = xG · {visible.length} shots</span>
      </div>
      <div className="shot-detail" aria-live="polite">
        {selected ? <>
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-xs font-medium mb-1" style={{ color: color(selected) }}>{shotOutcome(selected)} · {shotMinute(selected)}</p><h3 className="text-lg font-semibold">{selected.playerName}</h3></div>
            <div className="flex items-center gap-2 text-xs text-muted">
              <span>{selectedIndex + 1} / {visible.length}</span>
              <button type="button" className="shot-nav" aria-label="Previous shot" disabled={selectedIndex === 0} onClick={() => setSelectedId(visible[selectedIndex - 1].id)}>←</button>
              <button type="button" className="shot-nav" aria-label="Next shot" disabled={selectedIndex === visible.length - 1} onClick={() => setSelectedId(visible[selectedIndex + 1].id)}>→</button>
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-3 mt-5">
            {[["Expected goals", selected.expectedGoals == null ? "–" : selected.expectedGoals.toFixed(2)], ["Shot type", words(selected.shotType)], ["Situation", words(selected.situation)]].map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="text-sm font-medium mt-1 tabular-nums">{value}</dd></div>)}
          </dl>
        </> : <p className="text-sm text-muted py-6">{visible.length ? "Select a shot on the pitch to explore the chance." : "No shots match these filters."}</p>}
      </div>
    </div>
  );
}

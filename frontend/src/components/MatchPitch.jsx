import React, { useEffect, useId, useRef, useState } from "react";
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
const isNum = (value) => typeof value === "number" && Number.isFinite(value);
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export const OUTCOME_COLORS = { Goal: "#5fe08f", "Own goal": "#5fe08f", Saved: "#f2c14e", Woodwork: "#f2c14e", Blocked: "#ef8354", "Off target": "#a9b8b0" };
// Goal mouth in FotMob's frame: posts at y 30.34–37.66 on the x=105 line, bar at 2.44 m.
const GOAL = { left: 30.34, right: 37.66, bar: 2.44 };
const GOAL_VIEW = { left: 27, right: 41, top: 3.7 };

// Where the ball ended up, in FotMob's frame (every shot attacks x=105).
// Returns null when the feed has no end location, rather than guessing one.
export function shotEnd(shot) {
  if (shot.isBlocked) return isNum(shot.blockedX) && isNum(shot.blockedY) ? { x: shot.blockedX, y: shot.blockedY } : null;
  return isNum(shot.goalCrossedY) ? { x: 105, y: clamp(shot.goalCrossedY, 0, 68) } : null;
}

// Shooter's view of the goal: screen-left is low y because shooters face +x, so no mirroring by team.
// `keeper` flips it to the goalkeeper's view, facing the shooter.
function GoalMouth({ shots, selectedId, onSelect, onHover, onLeave, keeper }) {
  const plotted = shots.filter((shot) => !shot.isBlocked && isNum(shot.goalCrossedY) && isNum(shot.goalCrossedZ));
  const { left, right, top } = GOAL_VIEW;
  return (
    <figure className="goal-mouth">
      <svg viewBox={`${left} ${-top} ${right - left} ${top + 0.3}`} role="group" aria-label="Where shots crossed the goal line">
        <path d={`M${left} 0H${right}`} className="goal-ground" />
        <path d={`M${GOAL.left} 0V${-GOAL.bar}H${GOAL.right}V0`} className="goal-frame" />
        {plotted.map((shot) => {
          const outcome = shotOutcome(shot);
          const offTarget = outcome === "Off target";
          const selected = shot.id === selectedId;
          return (
            <circle
              key={shot.id}
              data-shot={shot.id}
              cx={clamp(keeper ? left + right - shot.goalCrossedY : shot.goalCrossedY, left + 0.25, right - 0.25)}
              cy={-clamp(shot.goalCrossedZ, 0.2, top - 0.25)}
              r={offTarget ? 0.16 : 0.22}
              fill={OUTCOME_COLORS[outcome]}
              fillOpacity={offTarget && !selected ? 0.55 : 1}
              stroke={selected ? "#fff" : "#10251f"}
              strokeWidth={selected ? 0.09 : 0.04}
              onClick={() => onSelect(shot.id)}
              onMouseEnter={() => onHover(shot.id)}
              onMouseLeave={onLeave}
            ><title>{`${shot.playerName} · ${shotMinute(shot)} · ${outcome}`}</title></circle>
          );
        })}
      </svg>
      <figcaption>{keeper ? "Keeper's view · shots on target faced" : "Goal view · where each shot crossed the line"}</figcaption>
    </figure>
  );
}

export default function ShotMap({ shots, home, away, keeper = false, focus }) {
  const [teamFilter, setTeamFilter] = useState("all");
  const [period, setPeriod] = useState("all");
  const [player, setPlayer] = useState("all");
  const [selectedId, setSelectedId] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const hoverTimer = useRef();
  const tooltipId = useId();
  useEffect(() => () => clearTimeout(hoverTimer.current), []);
  // `focus` ({ id, n }) is a request from outside to show one shot; n lets the same goal be re-requested.
  useEffect(() => {
    if (!focus) return;
    setTeamFilter("all");
    setPeriod("all");
    setPlayer("all");
    setSelectedId(focus.id);
  }, [focus]);
  if (!shots) return <EmptyNote>Shot map not available for this match yet.</EmptyNote>;
  if (!shots.length) return <EmptyNote>No shots recorded for this match yet.</EmptyNote>;

  const teamShots = shots.filter((shot) => teamFilter === "all" || String(shot.teamId) === teamFilter);
  const counts = new Map();
  teamShots.forEach((shot) => {
    const entry = counts.get(String(shot.playerId)) || { name: shot.playerName, count: 0 };
    counts.set(String(shot.playerId), { ...entry, count: entry.count + 1 });
  });
  const players = [...counts].sort(([, a], [, b]) => b.count - a.count || a.name.localeCompare(b.name));
  const visible = teamShots.filter((shot) => (period === "all" || shot.period === period) && (player === "all" || String(shot.playerId) === player));
  const selected = visible.find((shot) => shot.id === selectedId);
  const tipShot = visible.find((shot) => shot.id === hoverId) || selected;
  const color = (shot) => TEAM_COLORS[shot.teamId === home.id ? "home" : "away"];
  // FotMob normalizes every shot toward x=105; rotate away shots so the teams attack opposite ends.
  const toPitch = (shot, point) => (shot.teamId === home.id ? point : { x: 105 - point.x, y: 68 - point.y });
  const percent = (point) => ({ left: `${point.x / 105 * 100}%`, top: `${point.y / 68 * 100}%` });
  const changeFilter = (setter, value) => { setter(value); setSelectedId(null); setHoverId(null); };
  const startHover = (id) => { clearTimeout(hoverTimer.current); hoverTimer.current = setTimeout(() => setHoverId(id), 350); };
  const endHover = () => { clearTimeout(hoverTimer.current); setHoverId(null); };
  const select = (id) => { endHover(); setSelectedId((current) => (current === id ? null : id)); };
  // Default: only the clicked shot's path. The toggle adds every visible shot's, with the selected one emphasised.
  const pathShots = (showAll ? visible : selected ? [selected] : []).filter(shotEnd);
  if (selected && showAll) pathShots.push(pathShots.splice(pathShots.indexOf(selected), 1)[0]);

  return (
    <div className="flex flex-col gap-4">
      <div className="shot-filters">
        {!keeper && <label>Team<select aria-label="Team" value={teamFilter} onChange={(e) => { changeFilter(setTeamFilter, e.target.value); setPlayer("all"); }}>
          <option value="all">Both teams</option><option value={home.id}>{home.team_name}</option><option value={away.id}>{away.team_name}</option>
        </select></label>}
        <label>Period<select aria-label="Period" value={period} onChange={(e) => changeFilter(setPeriod, e.target.value)}>
          <option value="all">All periods</option>
          {[...new Set(shots.map((shot) => shot.period).filter(Boolean))].map((value) => <option key={value} value={value}>{words(value)}</option>)}
        </select></label>
        <label>{keeper ? "Shooter" : "Player"}<select aria-label="Player" value={player} onChange={(e) => changeFilter(setPlayer, e.target.value)}>
          <option value="all">All players</option>{players.map(([id, { name, count }]) => <option key={id} value={id}>{name} ({count})</option>)}
        </select></label>
      </div>
      <GoalMouth keeper={keeper} shots={visible} selectedId={selected?.id} onSelect={select} onHover={startHover} onLeave={endHover} />
      {!keeper && <div className="flex justify-between gap-4 text-xs text-muted">
        <span><span style={{ color: TEAM_COLORS.home }}>●</span> {home.team_name} →</span>
        <span className="text-right">← {away.team_name} <span style={{ color: TEAM_COLORS.away }}>●</span></span>
      </div>}
      <div className="football-pitch shot-pitch" aria-label="Shot locations" onClick={(e) => e.target === e.currentTarget && setSelectedId(null)}>
        <PitchLines />
        {pathShots.length > 0 && (
          <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 105 68" preserveAspectRatio="none" aria-hidden="true">
            {pathShots.map((shot) => {
              const from = toPitch(shot, shot), to = toPitch(shot, shotEnd(shot));
              const outcome = shotOutcome(shot), isSel = shot.id === selected?.id;
              return (
                <g key={shot.id} opacity={isSel || !showAll ? 1 : 0.4}>
                  <line data-testid="shot-line" x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={OUTCOME_COLORS[outcome]} strokeWidth={isSel ? 2 : 1} strokeLinecap="round" strokeDasharray={shot.isBlocked ? "4 3" : undefined} vectorEffect="non-scaling-stroke" />
                  <circle cx={to.x} cy={to.y} r={isSel ? 0.9 : 0.55} fill={OUTCOME_COLORS[outcome]} stroke="#10251f" strokeWidth="0.25" />
                </g>
              );
            })}
          </svg>
        )}
        {visible.map((shot) => {
          const goal = shot.eventType === "Goal" || shot.isOwnGoal;
          const size = 9 + Math.sqrt(Math.max(0, Math.min(1, shot.expectedGoals || 0))) * 17;
          return (
            <button
              key={shot.id}
              type="button"
              className="shot-marker"
              style={{ ...percent(toPitch(shot, shot)), "--team-color": color(shot), "--shot-size": `${size}px` }}
              data-goal={goal}
              data-selected={selected?.id === shot.id}
              aria-pressed={selected?.id === shot.id}
              aria-label={`${shot.playerName}, ${shotMinute(shot)}, ${shotOutcome(shot)}`}
              aria-describedby={tipShot?.id === shot.id ? tooltipId : undefined}
              onClick={() => select(shot.id)}
              onMouseEnter={() => startHover(shot.id)}
              onMouseLeave={endHover}
              onFocus={() => startHover(shot.id)}
              onBlur={endHover}
            ><span>{goal ? "★" : shot.isBlocked ? "×" : shot.isOnTarget ? "•" : ""}</span></button>
          );
        })}
        {!visible.length && <p className="shot-empty">No shots match these filters.</p>}
        {tipShot && <ShotTooltip id={tooltipId} shot={tipShot} point={toPitch(tipShot, tipShot)} />}
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-xs text-muted">
        <span>★ Goal &nbsp; • Saved &nbsp; ○ Off target &nbsp; × Blocked</span>
        <label className="inline-flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show all shot paths</label>
        <span>Dot size = xG · {visible.length} shots · Hover for details, click for the shot path</span>
      </div>
    </div>
  );
}

function ShotTooltip({ id, shot, point }) {
  const outcome = shotOutcome(shot);
  const left = point.x / 105 * 100, top = point.y / 68 * 100;
  // Sit above the dot; flip below near the top edge and hug the sides near the touchlines.
  const x = left < 22 ? "-12%" : left > 78 ? "-88%" : "-50%";
  const y = top < 38 ? "22px" : "calc(-100% - 22px)";
  const stats = [
    ["xG", isNum(shot.expectedGoals) ? shot.expectedGoals.toFixed(2) : "–"],
    ...(isNum(shot.expectedGoalsOnTarget) && shot.isOnTarget && !shot.isBlocked ? [["xGOT", shot.expectedGoalsOnTarget.toFixed(2)]] : []),
    ["Type", words(shot.shotType)],
    ["Situation", words(shot.situation)],
  ];
  return (
    <div id={id} role="tooltip" className="shot-tooltip" style={{ left: `${left}%`, top: `${top}%`, transform: `translate(${x}, ${y})` }}>
      <p className="text-xs font-medium" style={{ color: OUTCOME_COLORS[outcome] }}>{outcome} · {shotMinute(shot)}</p>
      <p className="text-sm font-semibold mt-0.5">{shot.playerName}</p>
      <dl className="shot-tooltip-stats">
        {stats.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </div>
  );
}

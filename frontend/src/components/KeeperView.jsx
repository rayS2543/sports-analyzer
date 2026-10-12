import React, { useState } from "react";
import ShotMap, { shotOutcome } from "./MatchPitch";
import { EmptyNote } from "./ui";

// Shots on target a keeper faced. FotMob only sets keeperId on those (blocked shots and misses have none).
export function keeperSummary(shots) {
  const conceded = shots.filter((shot) => shotOutcome(shot) === "Goal").length;
  const xgot = shots.reduce((total, shot) => total + (shot.expectedGoalsOnTarget || 0), 0);
  return { faced: shots.length, saves: shots.length - conceded, conceded, xgot, prevented: xgot - conceded };
}

export default function KeeperView({ home, away, shots }) {
  const [side, setSide] = useState("home");
  const team = side === "home" ? home : away;
  const keepers = [...team.starters, ...team.bench].filter((player) => player.position === "GK"
    && (player.starter || shots.some((shot) => shot.keeperId === player.id)));
  const [pickedId, setPickedId] = useState(null);
  const keeper = keepers.find((player) => player.id === pickedId) || keepers[0];
  if (!keeper) return <EmptyNote>No goalkeeper data for this match yet.</EmptyNote>;
  const faced = (shots || []).filter((shot) => shot.keeperId === keeper.id);
  const { saves, conceded, xgot, prevented } = keeperSummary(faced);
  const stats = [
    ["Shots on target", faced.length], ["Saves", saves], ["Conceded", conceded],
    ["Save %", faced.length ? `${Math.round(saves / faced.length * 100)}%` : "–"],
    ["xGOT faced", xgot.toFixed(2)], ["Goals prevented", `${prevented > 0 ? "+" : ""}${prevented.toFixed(2)}`],
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="shot-filters">
        <label>Team<select aria-label="Keeper team" value={side} onChange={(e) => { setSide(e.target.value); setPickedId(null); }}>
          <option value="home">{home.team_name}</option><option value="away">{away.team_name}</option>
        </select></label>
        <label>Goalkeeper<select aria-label="Goalkeeper" value={keeper.id} onChange={(e) => setPickedId(Number(e.target.value))}>
          {keepers.map((player) => <option key={player.id} value={player.id}>{player.name}</option>)}
        </select></label>
      </div>
      <dl className="grid grid-cols-3 gap-3">
        {stats.map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="text-lg font-semibold tabular-nums">{value}</dd></div>)}
      </dl>
      {faced.length
        ? <ShotMap key={keeper.id} keeper shots={faced} home={home} away={away} />
        : <EmptyNote>{keeper.name} faced no shots on target.</EmptyNote>}
    </div>
  );
}

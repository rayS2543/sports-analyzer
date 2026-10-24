import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import FollowButton from "./FollowButton";
import NewsFeed from "./NewsFeed";
import TeamBadge from "./TeamBadge";
import { encodeMatchId } from "../matchId";
import { EmptyNote, ErrorNote, LEAGUE_NAMES, PageShell, Section, SkeletonRows, formatDay } from "./ui";

const RESULT_STYLE = {
  W: { label: "Win", className: "bg-win/15 text-win" },
  D: { label: "Draw", className: "bg-raised text-muted" },
  L: { label: "Loss", className: "bg-loss/15 text-loss" },
};

const POSITION_LABELS = {
  Goalkeeper: "Goalkeepers",
  Defence: "Defenders",
  Midfield: "Midfielders",
  Offence: "Forwards",
};

const POSITION_SHORT = {
  Goalkeeper: "GK",
  Defence: "DEF",
  Midfield: "MID",
  Offence: "FWD",
};

function ResultChip({ result, size = "md" }) {
  const style = RESULT_STYLE[result] || RESULT_STYLE.D;
  const dims = size === "lg" ? "w-9 h-9 text-sm" : "w-6 h-6 text-xs";
  return (
    <span className={`inline-flex items-center justify-center rounded-md font-semibold ${dims} ${style.className}`} title={style.label}>
      <span aria-hidden="true">{result}</span>
      <span className="sr-only">{style.label}</span>
    </span>
  );
}

function resultFor(match, teamName) {
  if (match.winner === "Draw") return "D";
  return match.winner === teamName ? "W" : "L";
}

function matchPath(league, match) {
  return `/match/${encodeMatchId({ league, date: match.date, home: match.home, away: match.away })}`;
}

function StandingStrip({ standing }) {
  if (!standing) return null;
  const cells = [
    ["Pos", standing.position],
    ["P", standing.playedGames],
    ["W", standing.won],
    ["D", standing.draw],
    ["L", standing.lost],
    ["GD", standing.goalDifference > 0 ? `+${standing.goalDifference}` : standing.goalDifference],
    ["Pts", standing.points],
  ];
  return (
    <dl className="grid grid-cols-4 sm:grid-cols-7 gap-px overflow-hidden rounded-xl border border-line bg-line">
      {cells.map(([label, value]) => (
        <div key={label} className="bg-surface px-3 py-3 flex flex-col gap-1">
          <dt className="text-xs text-faint">{label}</dt>
          <dd className={`text-lg font-semibold tabular-nums tracking-tight ${label === "Pts" || label === "Pos" ? "text-fg" : "text-muted"}`}>
            {value ?? "-"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function MatchRow({ league, teamName, match, upcoming = false }) {
  const to = matchPath(league, match);
  const result = upcoming ? null : resultFor(match, teamName);
  return (
    <li>
      <Link
        to={to}
        className="pressable flex items-center gap-4 py-3 border-b border-line/60 last:border-0 text-sm hover:bg-surface -mx-2 px-2 rounded-lg"
      >
        <time dateTime={match.date} className="w-20 shrink-0 text-xs text-faint">
          {formatDay(match.date)}
        </time>
        <span className="min-w-0 flex-1 truncate">
          <span className={match.home === teamName ? "font-semibold" : "text-muted"}>{match.home}</span>
          {upcoming ? (
            <span className="text-faint px-1.5">vs</span>
          ) : (
            <span className="tabular-nums font-semibold px-1.5">{match.score}</span>
          )}
          <span className={match.away === teamName ? "font-semibold" : "text-muted"}>{match.away}</span>
        </span>
        {result && <ResultChip result={result} />}
      </Link>
    </li>
  );
}

function RosterGroup({ label, players }) {
  if (!players.length) return null;
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <h3 className="text-xs font-medium text-faint px-1 mb-1">
        {label} · {players.length}
      </h3>
      <ul className="flex flex-col">
        {players.map((player) => (
          <li
            key={player.id ?? `${player.name}-${player.shirtNumber}`}
            className="flex items-center gap-3 px-1 py-2 border-b border-line/50 last:border-0 text-sm"
          >
            <span className="w-7 text-right text-xs text-faint tabular-nums shrink-0">
              {player.shirtNumber ?? "—"}
            </span>
            <span className="font-medium flex-1 min-w-0 truncate">{player.name}</span>
            <span className="text-xs text-muted truncate max-w-[40%] text-right">{player.nationality || ""}</span>
            <span className="text-xs text-faint w-8 text-center shrink-0">
              {POSITION_SHORT[player.position] || ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LastLineup({ league, teamName, match }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!match) return undefined;
    setDetail(null);
    setError(null);
    const controller = new AbortController();
    const query = new URLSearchParams({
      league,
      date: match.date,
      home: match.home,
      away: match.away,
    });
    fetch(`${API_BASE}/matches/detail?${query}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) setError(data.error);
        else setDetail(data);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setError("Could not load lineup");
      });
    return () => controller.abort();
  }, [league, match]);

  if (!match) return <EmptyNote>No recent match to show a lineup for.</EmptyNote>;

  const side = match.home === teamName ? "home" : "away";
  const team = detail?.available ? detail[side] : null;
  const to = matchPath(league, match);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Last XI vs{" "}
        <Link to={to} className="text-fg font-medium hover:text-accent transition-colors duration-150">
          {match.home === teamName ? match.away : match.home}
        </Link>
        <span className="text-faint"> · {formatDay(match.date)}</span>
        {team?.formation && <span className="text-faint"> · {team.formation}</span>}
      </p>

      {error && <EmptyNote>{error}</EmptyNote>}
      {!error && !detail && <SkeletonRows rows={6} />}
      {!error && detail && !detail.available && (
        <EmptyNote>
          Lineup not available yet.{" "}
          <Link to={to} className="text-accent font-medium hover:underline">
            Open match page
          </Link>
        </EmptyNote>
      )}
      {team && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
          {team.starters.map((player) => (
            <li
              key={player.id ?? `${player.name}-${player.number}`}
              className="flex items-center gap-3 py-2 border-b border-line/50 text-sm"
            >
              <span className="w-6 text-right text-xs text-faint tabular-nums shrink-0">{player.number ?? ""}</span>
              <span className="font-medium flex-1 truncate">{player.name}</span>
              <span className="text-xs text-faint w-6 text-center">{player.position}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function TeamDetailPage() {
  const { league, name } = useParams();
  const teamName = decodeURIComponent(name);
  const [team, setTeam] = useState(null);
  const [elo, setElo] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setTeam(null);
    setError(null);
    const controller = new AbortController();
    const query = new URLSearchParams({ league, name: teamName });
    fetch(`${API_BASE}/teams/detail?${query}`, { signal: controller.signal })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) setError(data.error);
        else setTeam(data);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("Error fetching team detail:", err);
        setError("Could not reach the backend");
      });
    return () => controller.abort();
  }, [league, teamName]);

  const displayName = team?.name || teamName;
  const squadGroups = Object.keys(POSITION_LABELS).map((position) => ({
    position,
    label: POSITION_LABELS[position],
    players: (team?.squad || []).filter((player) => player.position === position),
  }));
  const otherPlayers = (team?.squad || []).filter((player) => !POSITION_LABELS[player.position]);

  useEffect(() => {
    setElo(null);
    fetch(`${API_BASE}/ratings?league=${league}`)
      .then((res) => res.json())
      .then((data) => {
        if (data?.ratings) {
          const row = data.ratings.find((r) => r.team === teamName);
          setElo(row || null);
        }
      })
      .catch((err) => {
        console.error("Error fetching team Elo:", err);
      });
  }, [league, teamName]);


  return (
    <PageShell back>
      <section className="flex items-start gap-5">
        <TeamBadge name={displayName} crest={team?.crest} league={league} size="xl" />
        <div className="flex flex-col gap-1.5 min-w-0 flex-1">
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">{displayName}</h1>
          <p className="text-sm text-muted">{LEAGUE_NAMES[league] || league}</p>
          {(team?.venue || team?.coach?.name || team?.founded) && (
            <p className="text-sm text-faint">
              {[team.venue, team.coach?.name && `Coach ${team.coach.name}`, team.founded && `Est. ${team.founded}`]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          {elo && (
            <p className="text-sm text-muted pt-1">
              <span className="text-fg font-semibold tabular-nums">Elo {elo.rating}</span>
              <span className="text-faint"> · </span>
              <span className="tabular-nums">#{elo.rank}</span>
              <span className="text-faint"> in league · </span>
              <span className={`tabular-nums ${elo.delta > 0 ? "text-win" : elo.delta < 0 ? "text-loss" : ""}`}>
                {elo.delta > 0 ? "+" : ""}
                {elo.delta}
              </span>
              <span className="text-faint"> vs baseline · </span>
              <Link to={`/elo?league=${league}`} className="text-accent hover:underline">
                Full table
              </Link>
            </p>
          )}
        </div>
        <FollowButton league={league} name={displayName} />
      </section>

      {error && <ErrorNote>{error}</ErrorNote>}
      {!error && !team && <SkeletonRows rows={10} />}

      {!error && team && (
        <>
          <Section title="Season so far" aside={team.standing ? `#${team.standing.position}` : null}>
            <StandingStrip standing={team.standing} />
            {team.form ? (
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3 mt-4">
                <div className="flex gap-1.5">
                  {team.form.split("").map((r, idx) => (
                    <ResultChip key={idx} result={r} size="lg" />
                  ))}
                </div>
                <p className="text-sm text-muted">
                  <span className="text-fg font-semibold tabular-nums">{team.form_points}</span> points from the last{" "}
                  {team.matches_considered} matches
                </p>
              </div>
            ) : (
              <EmptyNote>No recent results yet.</EmptyNote>
            )}
          </Section>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 lg:gap-12 items-start">
            <Section title="Last lineup" aside="Starting XI">
              <LastLineup league={league} teamName={displayName} match={team.recent_matches[0]} />
            </Section>

            <Section title="Upcoming" aside={team.upcoming_matches.length ? `${team.upcoming_matches.length}` : null}>
              {team.upcoming_matches.length === 0 ? (
                <EmptyNote>No upcoming fixtures scheduled.</EmptyNote>
              ) : (
                <ul className="flex flex-col">
                  {team.upcoming_matches.map((match) => (
                    <MatchRow
                      key={`${match.date}-${match.home}-${match.away}`}
                      league={league}
                      teamName={displayName}
                      match={match}
                      upcoming
                    />
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <Section title="Recent results" aside={team.recent_matches.length ? `${team.recent_matches.length}` : null}>
            {team.recent_matches.length === 0 ? (
              <EmptyNote>No finished matches found.</EmptyNote>
            ) : (
              <ul className="flex flex-col">
                {team.recent_matches.map((match) => (
                  <MatchRow
                    key={`${match.date}-${match.home}-${match.away}`}
                    league={league}
                    teamName={displayName}
                    match={match}
                  />
                ))}
              </ul>
            )}
          </Section>

          <Section title="Squad" aside={team.squad.length ? `${team.squad.length} players` : null}>
            {team.squad.length === 0 ? (
              <EmptyNote>Squad not available for this club.</EmptyNote>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {squadGroups.map((group) => (
                  <RosterGroup key={group.position} label={group.label} players={group.players} />
                ))}
                {otherPlayers.length > 0 && <RosterGroup label="Other" players={otherPlayers} />}
              </div>
            )}
          </Section>

          <Section title="News">
            <NewsFeed teams={[`${displayName}@${league}`]} />
          </Section>
        </>
      )}
    </PageShell>
  );
}

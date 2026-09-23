import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import FollowButton from "./FollowButton";
import NewsFeed from "./NewsFeed";
import TeamBadge from "./TeamBadge";
import { ErrorNote, LEAGUE_NAMES, PageShell, Section, SkeletonRows, formatDay } from "./ui";

const RESULT_STYLE = {
  W: { label: "Win", className: "bg-win/15 text-win" },
  D: { label: "Draw", className: "bg-raised text-muted" },
  L: { label: "Loss", className: "bg-loss/15 text-loss" },
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

export default function TeamDetailPage() {
  const { league, name } = useParams();
  const teamName = decodeURIComponent(name);
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

  const resultFor = (m) => (m.winner === "Draw" ? "D" : m.winner === teamName ? "W" : "L");

  return (
    <PageShell back>
      <section className="flex items-center gap-5">
        <TeamBadge name={teamName} size="xl" />
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">{teamName}</h1>
          <p className="text-sm text-muted">{LEAGUE_NAMES[league] || league}</p>
        </div>
        <FollowButton league={league} name={teamName} />
      </section>

      <Section title="News">
        <NewsFeed teams={[teamName]} />
      </Section>

      {error && <ErrorNote>{error}</ErrorNote>}

      {!error && !form && <SkeletonRows rows={6} />}

      {!error && form && (
        <>
          <Section title="Recent form">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <div className="flex gap-1.5">
                {form.form.split("").map((r, idx) => (
                  <ResultChip key={idx} result={r} size="lg" />
                ))}
              </div>
              <p className="text-sm text-muted">
                <span className="text-fg font-semibold tabular-nums">{form.points}</span> points from the last{" "}
                {form.matches_considered} matches
              </p>
            </div>
          </Section>

          <Section title="Match history">
            <ul className="flex flex-col">
              {form.matches.map((m, idx) => {
                const result = resultFor(m);
                return (
                  <li key={idx} className="flex items-center gap-4 py-3 border-b border-line/60 last:border-0 text-sm">
                    <div className="flex-1 min-w-0 flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-4">
                      <time dateTime={m.date} className="sm:w-24 shrink-0 text-xs text-faint">
                        {formatDay(m.date)}
                      </time>
                      <span className="min-w-0 truncate">
                        <span className={m.home === teamName ? "font-semibold" : "text-muted"}>{m.home}</span>{" "}
                        <span className="tabular-nums font-semibold px-1">{m.score}</span>{" "}
                        <span className={m.away === teamName ? "font-semibold" : "text-muted"}>{m.away}</span>
                      </span>
                    </div>
                    <ResultChip result={result} />
                  </li>
                );
              })}
            </ul>
          </Section>
        </>
      )}
    </PageShell>
  );
}

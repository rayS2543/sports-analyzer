import { API_BASE } from "../apiBase";
import React, { useEffect, useState } from "react";
import { EmptyNote, ErrorNote, SkeletonRows } from "./ui";

export const TOPICS = [
  ["transfers", "Transfers"],
  ["injuries", "Injuries"],
  ["matches", "Matches"],
  ["club", "Club"],
  ["other", "Other"],
];
const LANGUAGES = { es: "Spanish", ca: "Catalan" };
const PAGE = 30;

export const DEFAULT_PREFS = {
  topics: TOPICS.map(([key]) => key),
  rumors: "all", // "all" | "concrete" | "official" -- applies to transfer stories only
  hiddenSources: [],
  showOriginal: true,
  pinned: null,
};

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function timeAgo(iso) {
  if (!iso) return null;
  const minutes = Math.round((new Date(iso) - Date.now()) / 60000);
  if (minutes > -60) return rtf.format(minutes, "minute");
  if (minutes > -60 * 24) return rtf.format(Math.round(minutes / 60), "hour");
  return rtf.format(Math.round(minutes / 1440), "day");
}

function passesRumorFilter(article, rumors) {
  const ctx = article.context;
  if (!ctx || rumors === "all") return true;
  if (rumors === "official") return ctx.stage === "official";
  return !ctx.tentative;
}

export function applyPrefs(items, prefs) {
  return items.filter(
    (a) =>
      prefs.topics.includes(a.topic) &&
      !prefs.hiddenSources.includes(`${a.team_name}:${a.source}`) &&
      passesRumorFilter(a, prefs.rumors)
  );
}

const TONE = {
  tentative: "bg-raised text-muted ring-line",
  concrete: "bg-accent/10 text-accent ring-accent/30",
  official: "bg-win/10 text-win ring-win/30",
};

export const TIERS = {
  high: ["Established source", "bg-win/10 text-win ring-win/30"],
  medium: ["Club-leaning source", "bg-accent/10 text-accent ring-accent/30"],
  low: ["Fan site", "bg-loss/10 text-loss ring-loss/30"],
};

function SourceNote({ article }) {
  const tier = TIERS[article.source_tier];
  if (!tier) return null;
  return (
    <details className="group">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
        <span className={`rounded-md px-1.5 py-px font-medium ring-1 ring-inset ${tier[1]}`}>{tier[0]}</span>
        <span aria-hidden="true" className="text-faint transition-transform group-open:rotate-90 group-hover:text-fg">›</span>
        <span className="sr-only">About {article.source}</span>
      </summary>
      <p className="mt-1.5 max-w-[65ch] rounded-lg bg-surface px-3 py-2 text-sm text-muted ring-1 ring-inset ring-line">
        <span className="font-medium text-fg">{article.source}.</span> {article.source_about}{" "}
        <span className="text-xs text-faint">Our own judgement, not a fact-check of this story.</span>
      </p>
    </details>
  );
}

function ContextNote({ context }) {
  const tone = context.stage === "official" ? "official" : context.tentative ? "tentative" : "concrete";
  return (
    <details className="group mt-1">
      <summary className="inline-flex cursor-pointer list-none items-center gap-2 text-xs [&::-webkit-details-marker]:hidden">
        <span className={`rounded-md px-2 py-0.5 font-medium ring-1 ring-inset ${TONE[tone]}`}>{context.label}</span>
        <span className="text-faint">{context.sourcing}</span>
        <span className="text-faint group-hover:text-fg">
          How to read this <span aria-hidden="true" className="inline-block transition-transform group-open:rotate-90">›</span>
        </span>
      </summary>
      <div className="mt-2 max-w-[65ch] rounded-lg bg-surface px-3 py-2.5 text-sm text-muted ring-1 ring-inset ring-line">
        <p>{context.note}</p>
        <p className="mt-1.5 text-xs text-faint">
          An automated reading of the article’s wording and sourcing, not a verdict on whether the story is true.
        </p>
      </div>
    </details>
  );
}

function Story({ article, showTeam, showOriginal }) {
  const when = timeAgo(article.published);
  return (
    <article className="flex flex-col gap-1.5 py-4 border-b border-line/60 last:border-0">
      <div className="flex flex-wrap items-start gap-x-2 gap-y-1 text-xs text-faint">
        <span className="font-medium text-muted">{article.source}</span>
        {article.source_kind === "local" && <span className="rounded bg-raised px-1.5 py-px text-muted">Local</span>}
        <SourceNote article={article} />
        {article.translated && <span>· Translated from {LANGUAGES[article.lang] || article.lang}</span>}
        {when && (
          <time dateTime={article.published} title={new Date(article.published).toLocaleString()}>
            · {when}
          </time>
        )}
        {showTeam && <span className="ml-auto">{article.team_name}</span>}
      </div>
      <a
        href={article.link}
        target="_blank"
        rel="noreferrer"
        className="max-w-[70ch] text-[15px] font-medium leading-snug text-fg hover:text-accent hover:underline"
      >
        {article.title}
      </a>
      {showOriginal && article.original_title && (
        <p lang={article.lang} className="max-w-[70ch] text-sm italic text-faint">
          {article.original_title}
        </p>
      )}
      {article.summary && <p className="max-w-[70ch] text-sm text-muted line-clamp-2">{article.summary}</p>}
      {article.context && <ContextNote context={article.context} />}
    </article>
  );
}

function FeedHealth({ sources }) {
  const failed = sources.filter((s) => !s.ok);
  const untranslated = sources.filter((s) => s.ok && s.count && s.translated === false);
  return (
    <div className="flex flex-col gap-1 text-xs text-faint">
      <p>
        {sources.length - failed.length} of {sources.length} sources loaded
      </p>
      {failed.length > 0 && <p className="text-loss">Couldn’t load: {failed.map((s) => s.name).join(", ")}</p>}
      {untranslated.length > 0 && (
        <p>Translation unavailable right now for {untranslated.map((s) => s.name).join(", ")}; showing original headlines.</p>
      )}
    </div>
  );
}

export default function NewsFeed({ teams, prefs = DEFAULT_PREFS, onSources }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [shown, setShown] = useState(PAGE);
  const key = teams.join(",");

  useEffect(() => {
    if (!teams.length) {
      setData({ items: [], sources: [] });
      return;
    }
    setData(null);
    setError(null);
    setShown(PAGE);
    fetch(`${API_BASE}/news/teams?teams=${encodeURIComponent(key)}`)
      .then((res) => res.json())
      .then((body) => {
        if (body.error && !body.items?.length) setError(body.error);
        const next = { items: body.items || [], sources: body.sources || [] };
        setData(next);
        onSources?.(next.sources);
      })
      .catch((err) => {
        console.error("Error fetching team news:", err);
        setError("Could not reach the backend");
        setData({ items: [], sources: [] });
      });
    // Refetch only when the teams change, not when the parent re-renders onSources.
  }, [key]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (data === null) return <SkeletonRows rows={4} />;

  const items = applyPrefs(data.items, prefs);
  return (
    <div className="flex flex-col gap-3">
      {data.sources.length > 0 && <FeedHealth sources={data.sources} />}
      {items.length === 0 ? (
        <EmptyNote>{data.items.length ? "No stories match your filters." : "No recent news found."}</EmptyNote>
      ) : (
        <div className="flex flex-col">
          {items.slice(0, shown).map((a) => (
            <Story key={a.link || a.title} article={a} showTeam={teams.length > 1} showOriginal={prefs.showOriginal} />
          ))}
        </div>
      )}
      {items.length > shown && (
        <button
          type="button"
          onClick={() => setShown((n) => n + PAGE)}
          className="pressable self-start rounded-lg px-3 py-1.5 text-sm font-medium text-muted ring-1 ring-inset ring-line hover:bg-surface"
        >
          Show more ({items.length - shown})
        </button>
      )}
    </div>
  );
}

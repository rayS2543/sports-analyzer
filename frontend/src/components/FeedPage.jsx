import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useFavorites } from "../favorites";
import NewsFeed, { DEFAULT_PREFS, TIERS, TOPICS } from "./NewsFeed";
import TeamBadge from "./TeamBadge";
import { PageShell } from "./ui";

const STORAGE_KEY = "sa-newsroom";
const RUMOR_OPTIONS = [
  ["all", "Everything", "Rumours included"],
  ["concrete", "Firmer reports", "Hide tentative transfer stories"],
  ["official", "Official only", "Only announced transfers"],
];

function loadPrefs() {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return DEFAULT_PREFS;
  }
}

function usePrefs() {
  const [prefs, setPrefs] = useState(loadPrefs);
  function update(patch) {
    setPrefs((old) => {
      const next = { ...old, ...patch };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // localStorage unavailable -- preferences still apply for this session.
      }
      return next;
    });
  }
  return [prefs, update];
}

const toggle = (list, value) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

function Chip({ pressed, onClick, title, children }) {
  return (
    <button
      type="button"
      title={title}
      aria-pressed={pressed}
      onClick={onClick}
      className={`pressable rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-inset ${
        pressed ? "bg-accent/15 text-accent ring-accent/30" : "text-muted ring-line hover:bg-surface"
      }`}
    >
      {children}
    </button>
  );
}

function Customize({ prefs, update, sources }) {
  return (
    <details className="group rounded-xl bg-surface ring-1 ring-inset ring-line">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
        Customize your feed
        <span aria-hidden="true" className="text-faint transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      <div className="flex flex-col gap-5 border-t border-line px-4 py-4">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">Topics</legend>
          <div className="flex flex-wrap gap-2">
            {TOPICS.map(([key, label]) => (
              <Chip key={key} pressed={prefs.topics.includes(key)} onClick={() => update({ topics: toggle(prefs.topics, key) })}>
                {label}
              </Chip>
            ))}
          </div>
        </fieldset>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">Transfer rumours</legend>
          <div className="flex flex-wrap gap-2">
            {RUMOR_OPTIONS.map(([key, label, hint]) => (
              <Chip key={key} title={hint} pressed={prefs.rumors === key} onClick={() => update({ rumors: key })}>
                {label}
              </Chip>
            ))}
          </div>
        </fieldset>

        {sources.length > 0 && (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">Sources</legend>
            <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              {sources.map((s) => {
                const id = `${s.team_name}:${s.name}`;
                return (
                  <label key={id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="accent-[rgb(var(--accent))]"
                      checked={!prefs.hiddenSources.includes(id)}
                      onChange={() => update({ hiddenSources: toggle(prefs.hiddenSources, id) })}
                    />
                    <span>{s.name}</span>
                    <span className="text-xs text-faint" title={s.about || undefined}>
                      {s.team_name} · {s.kind === "local" ? "local" : "international"}
                      {TIERS[s.tier] && ` · ${TIERS[s.tier][0].toLowerCase()}`}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        )}

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="accent-[rgb(var(--accent))]"
            checked={prefs.showOriginal}
            onChange={() => update({ showOriginal: !prefs.showOriginal })}
          />
          Show original headlines under translations
        </label>
      </div>
    </details>
  );
}

export default function FeedPage() {
  const { favorites } = useFavorites();
  const [prefs, update] = usePrefs();
  const [sources, setSources] = useState([]);
  const names = favorites.map((f) => f.name);
  // "Name@League" tells the backend which country's press to search.
  const spec = (name) => {
    const { league } = favorites.find((f) => f.name === name);
    return league ? `${name}@${league}` : name;
  };
  const pinned = names.includes(prefs.pinned) ? prefs.pinned : null;
  const [tab, setTab] = useState(pinned || "all");
  const active = tab === "all" || names.includes(tab) ? tab : "all";
  const tabs = ["all", ...(pinned ? [pinned] : []), ...names.filter((n) => n !== pinned)];

  return (
    <PageShell back>
      <section className="flex flex-col gap-2">
        <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">My Football</h1>
        <p className="text-sm text-muted">
          Your clubs, local reporting translated into English, and a note on how solid each transfer story is.
        </p>
      </section>

      {favorites.length === 0 ? (
        <p className="text-sm text-muted py-2">
          Follow a team to build your feed.{" "}
          <Link to="/" className="text-accent hover:underline">
            Browse teams →
          </Link>
        </p>
      ) : (
        <section className="flex flex-col gap-5 min-w-0">
          <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Clubs">
            {tabs.map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={active === t}
                onClick={() => setTab(t)}
                className={`pressable inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                  active === t ? "bg-raised text-fg ring-1 ring-inset ring-line" : "text-muted hover:text-fg"
                }`}
              >
                {t === "all" ? "All clubs" : (
                  <>
                    <TeamBadge name={t} size="sm" />
                    {t}
                    {t === pinned && <span aria-label="pinned" className="text-accent">★</span>}
                  </>
                )}
              </button>
            ))}
            {active !== "all" && (
              <button
                type="button"
                onClick={() => update({ pinned: pinned === active ? null : active })}
                className="pressable ml-auto text-sm text-muted hover:text-fg"
              >
                {pinned === active ? "Unpin" : "Pin as default"}
              </button>
            )}
          </div>

          <Customize prefs={prefs} update={update} sources={sources} />

          <NewsFeed teams={(active === "all" ? names : [active]).map(spec)} prefs={prefs} onSources={setSources} />
        </section>
      )}
    </PageShell>
  );
}

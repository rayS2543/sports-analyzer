import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NewsFeed, { DEFAULT_PREFS, applyPrefs } from "./NewsFeed";

const rumor = {
  title: "El Barça podría fichar a un delantero",
  summary: "Según fuentes",
  link: "https://example.com/a",
  published: new Date().toISOString(),
  source: "Mundo Deportivo",
  source_kind: "local",
  lang: "es",
  team_name: "FC Barcelona",
  topic: "transfers",
  context: { stage: "interest", label: "Tentative report", sourcing: "Unnamed sources", tentative: true, note: "Describes possible interest." },
};
const official = { ...rumor, link: "b", title: "Barça announce signing", context: { ...rumor.context, stage: "official", label: "Says it's official", tentative: false } };
const match = { ...rumor, link: "c", title: "Player ratings", topic: "matches", context: null };

beforeEach(() => {
  global.fetch = vi.fn((url) =>
    Promise.resolve({
      json: async () =>
        url.includes("/news/translate")
          ? { titles: ["Barça could sign a striker"] }
          : {
              items: [rumor],
              sources: [
                { team_name: "FC Barcelona", name: "Mundo Deportivo", ok: true, count: 1 },
                { team_name: "FC Barcelona", name: "Ara", ok: false, count: 0 },
              ],
            },
    })
  );
});

afterEach(() => vi.restoreAllMocks());

describe("NewsFeed", () => {
  it("shows the translated story, its original headline, context and failed feeds", async () => {
    render(<NewsFeed teams={["FC Barcelona"]} />);

    expect(await screen.findByRole("link", { name: "Barça could sign a striker" })).toBeInTheDocument();
    expect(screen.getByText("El Barça podría fichar a un delantero")).toBeInTheDocument();
    expect(screen.getByText(/Translated from Spanish/)).toBeInTheDocument();
    expect(screen.getByText("Tentative report")).toBeInTheDocument();
    expect(screen.getByText(/Couldn’t load: Ara/)).toBeInTheDocument();
  });

  it("sends only the headlines it shows for translation", async () => {
    const many = Array.from({ length: 35 }, (_, i) => ({ ...rumor, link: `l${i}`, title: `Titular ${i}` }));
    global.fetch = vi.fn((url) =>
      Promise.resolve({ json: async () => (url.includes("/news/translate") ? { titles: [] } : { items: many, sources: [] }) })
    );
    render(<NewsFeed teams={["FC Barcelona"]} />);
    const sent = () => global.fetch.mock.calls.filter(([u]) => u.includes("/news/translate")).flatMap(([, o]) => JSON.parse(o.body).titles);
    await waitFor(() => expect(sent()).toHaveLength(30), { timeout: 4000 });
    expect(sent()).not.toContain("Titular 34");
  });
});

describe("applyPrefs", () => {
  const items = [rumor, official, match];
  const titles = (prefs) => applyPrefs(items, { ...DEFAULT_PREFS, ...prefs }).map((a) => a.title);

  it("filters by topic", () => {
    expect(titles({ topics: ["matches"] })).toEqual(["Player ratings"]);
  });

  it("hides tentative transfer stories but keeps non-transfer news", () => {
    expect(titles({ rumors: "concrete" })).toEqual(["Barça announce signing", "Player ratings"]);
    expect(titles({ rumors: "official" })).toEqual(["Barça announce signing", "Player ratings"]);
  });

  it("hides muted sources", () => {
    expect(titles({ hiddenSources: ["FC Barcelona:Mundo Deportivo"] })).toEqual([]);
  });
});

import pytest
import news_client
from news_client import reporting_context, topic_of


def test_hedged_interest_is_tentative():
    ctx = reporting_context("Barça could consider a move for midfielder", "Sources say the club is monitoring him.")
    assert ctx["label"] == "Tentative report"
    assert ctx["sourcing"] == "Unnamed sources"
    assert ctx["tentative"]
    assert "“could”" in ctx["note"]


def test_spanish_conditional_stays_tentative_even_if_translation_hardens_it():
    ctx = reporting_context("El Barça podría presentar una oferta", "", "Barça submits an offer")
    assert ctx["label"] == "Tentative report"


def test_unhedged_bid_is_concrete_claim():
    ctx = reporting_context("United submit £40m bid for striker", 'Ratcliffe said: "We made our offer last night."')
    assert ctx["label"] == "Concrete claim"
    assert ctx["sourcing"] == "On-record quote"
    assert not ctx["tentative"]


def test_official_announcement():
    ctx = reporting_context("El Barça anuncia la incorporación de Dany Freire", "")
    assert ctx["label"] == "Says it's official"


def test_denied_confirmation_is_not_official():
    assert reporting_context("No bid has been confirmed for the winger", "")["stage"] == "bid"


def test_papers_review_is_a_roundup():
    assert reporting_context("Papers: Man Utd line up Conte", "")["sourcing"] == "Rumour roundup"


def test_headline_stronger_than_text_is_flagged():
    ctx = reporting_context("Deal agreed for Barça's new winger", "The club are interested and may open talks.")
    assert "headline makes a stronger claim" in ctx["note"]


def test_topics():
    assert topic_of("El Barça cierra el fichaje de Livakovic") == "transfers"
    assert topic_of("Pedri suffers hamstring injury") == "injuries"
    assert topic_of("Laporta faces the club assembly") == "club"
    assert topic_of("Player ratings from Sevilla vs Barça") == "matches"


def test_for_teams_tags_and_reports_failed_feeds_without_translating(monkeypatch):
    feeds = {
        "https://www.mundodeportivo.com/rss/futbol/fc-barcelona": [
            {"title": "El Barça podría fichar a un delantero", "link": "a", "published": "2026-09-23T10:00:00+00:00", "summary": "Según fuentes"},
        ],
        "https://www.fcbarcelonanoticias.com/rss": None,
    }
    monkeypatch.setattr(news_client, "_fetch", lambda url: feeds.get(url, []))
    monkeypatch.setattr(news_client, "translate", lambda *a: pytest.fail("loading a feed must not spend translation quota"))

    items, sources = news_client.for_teams(["FC Barcelona"])

    [article] = items
    assert article["title"] == "El Barça podría fichar a un delantero" and article["lang"] == "es"
    assert article["source"] == "Mundo Deportivo"
    assert article["topic"] == "transfers"
    assert article["context"]["label"] == "Tentative report"
    failed = [s["name"] for s in sources if not s["ok"]]
    assert failed == ["FC Barcelona Noticias"]


def test_translation_failure_falls_back_to_original(monkeypatch):
    def boom(lines, lang):
        raise ValueError("rate limited")

    monkeypatch.setattr(news_client, "_retry_after", 0.0)
    monkeypatch.setattr(news_client, "_translate_lines", boom)
    assert news_client.translate(["Hola", "Adiós"], "es") == [None, None]
    assert news_client.translate(["Hi"], "en") == ["Hi"]

    # Backs off instead of hammering the endpoint again.
    monkeypatch.setattr(news_client, "_translate_lines", lambda lines, lang: ("Hello",))
    assert news_client.translate(["Hola"], "es") == [None]


def test_unknown_team_contributes_nothing():
    assert news_client.for_teams(["Nowhere FC"]) == ([], [])


def test_team_news_route_returns_sources(client, monkeypatch):
    monkeypatch.setattr(news_client, "for_teams", lambda teams: ([], [{"name": "X", "ok": False}]))
    body = client.get("/news/teams?teams=FC%20Barcelona").get_json()
    assert body == {"items": [], "sources": [{"name": "X", "ok": False}]}


def test_every_curated_source_has_a_tier_and_description():
    for sources in news_client.CLUB_SOURCES.values():
        for s in sources:
            assert s["tier"] in ("high", "medium", "low"), s["name"]
            assert s["about"], s["name"]


def test_unknown_outlet_gets_no_tier():
    s = news_client._source("Some Blog", "https://example.com/rss")
    assert s["tier"] is None and s["about"] is None


def test_search_name_drops_legal_forms():
    assert news_client._search_name("RCD Espanyol de Barcelona") == "Espanyol de Barcelona"
    assert news_client._search_name("Sevilla FC") == "Sevilla"
    assert news_client._search_name("Real Madrid CF") == "Real Madrid"


def test_uncurated_team_gets_local_google_news_by_league():
    [src] = news_client.sources_for("FC Internazionale Milano", "SA")
    assert src["lang"] == "it" and src["aggregate"]
    assert "ceid=IT%3Ait" in src["url"] and "calcio" in src["url"] and "Internazionale+Milano" in src["url"]
    assert news_client.sources_for("Unknown FC") == []  # no league, no slug: nothing to guess
    assert [s["name"] for s in news_client.sources_for("Sevilla FC", "PD")] == ["The Guardian", "Google News"]


def test_aggregator_items_are_split_by_outlet_and_rated(monkeypatch):
    items = [
        {"outlet": "Gazzetta dello Sport", "title": "Inter, colpo a centrocampo", "link": "a", "published": "2026-09-23T10:00:00+00:00", "summary": ""},
        {"outlet": "Blog Sconosciuto", "title": "Inter in finale", "link": "b", "published": "2026-09-23T09:00:00+00:00", "summary": ""},
    ]
    monkeypatch.setattr(news_client, "_fetch", lambda url: items)

    articles, sources = news_client.for_teams(["FC Internazionale Milano@SA"])

    assert [(a["source"], a["source_tier"], a["team_name"]) for a in articles] == [
        ("Gazzetta dello Sport", "high", "FC Internazionale Milano"),
        ("Blog Sconosciuto", None, "FC Internazionale Milano"),
    ]
    assert {s["name"]: s["tier"] for s in sources} == {"Gazzetta dello Sport": "high", "Blog Sconosciuto": None}


def test_deepl_sends_only_new_headlines(monkeypatch):
    sent = []

    class Resp:
        def __init__(self, texts): self.texts = texts
        def raise_for_status(self): pass
        def json(self): return {"translations": [{"text": f"EN {t}"} for t in self.texts]}

    def post(url, headers, json, timeout):
        assert url == "https://api-free.deepl.com/v2/translate" and headers["Authorization"] == "DeepL-Auth-Key k:fx"
        sent.append(json["text"])
        return Resp(json["text"])

    monkeypatch.setenv("DEEPL_API_KEY", "k:fx")
    monkeypatch.setattr(news_client, "_retry_after", 0.0)
    monkeypatch.setattr(news_client, "_deepl_cache", {})
    monkeypatch.setattr(news_client.requests, "post", post)

    assert news_client.translate(["Hola", "Adiós"], "es") == ["EN Hola", "EN Adiós"]
    assert news_client.translate(["Hola", "Gol"], "es") == ["EN Hola", "EN Gol"]
    assert sent == [["Hola", "Adiós"], ["Gol"]]  # the repeat only paid for the new headline


def test_translate_route_translates_only_what_it_is_sent(client, monkeypatch):
    monkeypatch.setattr(news_client, "translate", lambda texts, lang: [f"EN {t}" for t in texts])
    body = client.post("/news/translate", json={"lang": "es", "titles": ["Hola"]}).get_json()
    assert body == {"titles": ["EN Hola"]}
    assert client.post("/news/translate", json={"lang": "es", "titles": []}).status_code == 400


def test_club_sites_are_recognised_and_other_outlets_are_not():
    assert news_client._info("Arsenal.com", "Arsenal FC")[0] == "club"
    assert news_client._info("Real Madrid CF | Web Oficial", "Real Madrid CF")[0] == "club"
    assert news_client._info("Inter.it", "FC Internazionale Milano")[0] == "club"
    assert news_client._info("La Gazzetta dello Sport", "FC Internazionale Milano")[0] == "high"
    assert news_client._info("Diario Madrid", "Real Madrid CF") == (None, None)


def test_italian_german_french_headlines_are_classified_without_translation():
    assert topic_of("Calciomercato Inter: trattativa avviata per il centrocampista") == "transfers"
    assert topic_of("Inter, infortunio per Lautaro: out due settimane") == "injuries"
    assert topic_of("Bayern: Verletzung bei Musiala, Ausfall bis Dezember") == "injuries"
    assert topic_of("PSG : le défaite à Marseille, la compo probable") == "matches"
    ctx = reporting_context("Inter, trattativa per il difensore", "Secondo fonti, il club potrebbe offrire 20 milioni")
    assert ctx["tentative"] and ctx["sourcing"] == "Unnamed sources"
    assert reporting_context("Bayern: Wechsel ist offiziell", "")["stage"] == "official"

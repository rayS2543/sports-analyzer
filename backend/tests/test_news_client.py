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


def test_for_teams_translates_tags_and_reports_failed_feeds(monkeypatch):
    feeds = {
        "https://www.mundodeportivo.com/rss/futbol/fc-barcelona": [
            {"title": "El Barça podría fichar a un delantero", "link": "a", "published": "2026-09-23T10:00:00+00:00", "summary": "Según fuentes"},
        ],
        "https://www.fcbarcelonanoticias.com/rss": None,
    }
    monkeypatch.setattr(news_client, "_fetch", lambda url: feeds.get(url, []))
    monkeypatch.setattr(news_client, "_translate_lines", lambda lines, lang: ("Barça could sign a striker", "According to sources"))

    items, sources = news_client.for_teams(["FC Barcelona"])

    [article] = items
    assert article["title"] == "Barça could sign a striker"
    assert article["original_title"] == "El Barça podría fichar a un delantero"
    assert article["translated"] and article["source"] == "Mundo Deportivo"
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

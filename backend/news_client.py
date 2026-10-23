"""Per-club news for the favorites newsroom.

Pilot clubs (Barça, Man United) get a curated mix of local and
international RSS feeds; every other La Liga club falls back to its
Guardian feed. Non-English headlines are machine-translated, and each
article gets a topic plus -- for transfer stories -- a rule-based
"how to read this" note (see reporting_context).

Distinct from routes/news.py's generic Google News query search.
"""
import html
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from cache import cached

GUARDIAN = "https://www.theguardian.com/football/{slug}/rss"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
PER_SOURCE = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (sports-analyzer news reader)"}


# Editorial judgement of how much to trust each outlet's reporting, shown
# next to every story. Tiers: "high" (established newsroom with corrections
# policy), "medium" (credible but close to the club or prone to speculation),
# "low" (fan-run, unverified). Unknown outlets get no badge, not a guess.
SOURCE_INFO = {
    "The Guardian": ("high", "UK national newspaper with a large football desk and a public corrections policy."),
    "Sky Sports": ("high", "Broadcaster whose reporters are frequently first with confirmed transfer news."),
    "Manchester Evening News": ("high", "Greater Manchester's daily paper; strong on local club news, less so on global transfer scoops."),
    "Ara": ("high", "Catalan-language national daily with independent sports coverage of Barça."),
    "Mundo Deportivo": ("medium", "Barcelona sports daily, openly pro-Barça; reliable on club news, but transfer claims are often speculative."),
    "FC Barcelona Noticias": ("low", "Fan-run news site; useful for volume, but stories are often rewritten from other outlets without checking."),
}


def _source(name, url, lang="en", kind="international"):
    tier, about = SOURCE_INFO.get(name, (None, None))
    return {"name": name, "url": url, "lang": lang, "kind": kind, "tier": tier, "about": about}


CLUB_SOURCES = {
    "FC Barcelona": [
        _source("Mundo Deportivo", "https://www.mundodeportivo.com/rss/futbol/fc-barcelona", "es", "local"),
        _source("FC Barcelona Noticias", "https://www.fcbarcelonanoticias.com/rss", "es", "local"),
        _source("Ara", "https://www.ara.cat/rss/esports/barca/", "ca", "local"),
        _source("The Guardian", GUARDIAN.format(slug="barcelona")),
    ],
    "Manchester United FC": [
        _source("Manchester Evening News", "https://www.manchestereveningnews.co.uk/all-about/manchester-united-fc?service=rss", kind="local"),
        _source("Sky Sports", "https://www.skysports.com/rss/11667"),
        _source("The Guardian", GUARDIAN.format(slug="manchester-united")),
    ],
}

TEAM_SLUGS = {
    "Real Madrid CF": "realmadrid",
    "Club Atlético de Madrid": "atleticomadrid",
    "Athletic Club": "athleticbilbao",
    "Villarreal CF": "villarreal",
    "Real Betis Balompié": "realbetis",
    "RC Celta de Vigo": "celtavigo",
    "Real Sociedad de Fútbol": "realsociedad",
    "Sevilla FC": "sevilla",
    "Valencia CF": "valencia",
    "RCD Espanyol de Barcelona": "espanyol",
    "Getafe CF": "getafe",
    "CA Osasuna": "osasuna",
    "RCD Mallorca": "realmallorca",
    "Rayo Vallecano de Madrid": "rayo-vallecano",
    "Girona FC": "girona",
    "Deportivo Alavés": "alaves",
    "UD Las Palmas": "laspalmas",
    "Real Valladolid CF": "valladolid",
    "Elche CF": "elche",
    "Levante UD": "levante",
}


def sources_for(team_name):
    if team_name in CLUB_SOURCES:
        return CLUB_SOURCES[team_name]
    slug = TEAM_SLUGS.get(team_name)
    return [_source("The Guardian", GUARDIAN.format(slug=slug))] if slug else []


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _iso(pub_date):
    try:
        dt = parsedate_to_datetime(pub_date)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@cached(ttl_seconds=1800)
def _fetch(url):
    """One feed's newest items, or None if the feed failed -- None (not [])
    so the caller can report the failure instead of silently showing less."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return None

    items = []
    for item in root.findall("./channel/item")[:PER_SOURCE]:
        summary = _clean(item.findtext("description"))
        items.append(
            {
                "title": _clean(item.findtext("title")),
                "link": (item.findtext("link") or "").strip(),
                "published": _iso((item.findtext("pubDate") or "").strip()),
                "summary": summary[:280] + ("…" if len(summary) > 280 else ""),
            }
        )
    return items


# ponytail: unofficial Google Translate endpoint (free, no key, no SLA,
# rate-limits bursts). Swap this one function for a Claude call once
# there's an API budget.
@cached(ttl_seconds=None)
def _translate_lines(lines, lang):
    """One request for a whole feed: newline-joined in, split back out.
    Raises on any failure so a failure is never cached."""
    response = requests.post(
        TRANSLATE_URL,
        params={"client": "gtx", "sl": lang, "tl": "en", "dt": "t"},
        data={"q": "\n".join(lines)},
        timeout=15,
    )
    response.raise_for_status()
    out = "".join(segment[0] for segment in response.json()[0] if segment[0]).split("\n")
    if len(out) != len(lines):
        raise ValueError("translation lost line alignment")
    return tuple(line.strip() for line in out)


_retry_after = 0.0


def translate(texts, lang):
    """English translations of texts (same order), or all None if it
    failed -- the caller then shows the originals instead. Backs off for
    10 minutes after a failure so a 429 isn't prolonged by every page load."""
    global _retry_after
    if lang == "en":
        return list(texts)
    if time.monotonic() < _retry_after:
        return [None] * len(texts)
    try:
        return list(_translate_lines(tuple(t or "-" for t in texts), lang))
    except Exception:
        _retry_after = time.monotonic() + 600
        return [None] * len(texts)


# --- Topic + reporting context -------------------------------------------
# Keyword rules over the original text and its English translation, in
# English, Spanish and Catalan. Matching the original matters: translation
# can harden "podría" (could) into something more certain.

def _rx(words):
    return re.compile(r"\b(" + "|".join(words) + r")", re.IGNORECASE)


TOPICS = [
    ("transfers", _rx([
        "transfer", "signing", "sign ", "signs", "fichaje", "fichar", "ficha ", "fitxatge", "fitxar",
        "mercado", "mercat", "loan", "cesión", "cessió", "release clause", "cláusula", "clàusula",
        "bid", "oferta", "offer", "here we go", "renov", "contract", "contrato", "contracte", "target",
    ])),
    ("injuries", _rx([
        "injur", "lesión", "lesion", "lesió", "hamstring", "isquio", "knock", "sidelined", "baja",
        "fitness", "recovery", "recupera", "surgery", "operad", "quirófano", "out for",
    ])),
    ("club", _rx([
        "president", "laporta", "ratcliffe", "glazer", "board", "junta", "financ", "revenue", "debt",
        "deuda", "deute", "stadium", "estadio", "estadi", "camp nou", "old trafford", "asamblea",
        "assemblea", "election", "kit", "camiseta", "samarreta", "sponsor", "fair play",
    ])),
    ("matches", _rx([
        "vs", "v ", "preview", "player ratings", "ratings", "result", "draw", "defeat", "win ",
        "victoria", "victòria", "derrota", "empate", "empat", "crónica", "previa", "alineación",
        "lineup", "line-up", "goal", "gol", "champions", "liga", "premier league", "cup", "copa",
    ])),
]

# Strongest first: the first stage that matches is the claim being made.
STAGES = [
    ("official", "an official announcement", _rx([
        # Not "confirm": "no bid has been confirmed" / "Laporta confirma el interés".
        "official", "oficial", "announce", "anuncia", "unveil", "completes",
    ])),
    ("agreement", "an agreement", _rx([
        "agreement", "agreed", "acuerdo", "acord", "here we go", "deal done", "pre-contract",
        "precontrato", "medical", "revisión médica", "revisió mèdica", "seal", "close on",
        # Not bare "sign": "race to sign" / "want to sign" is interest.
        "closes in", "cierra", "tanca", "firma", "signs", "llega", "arriba", "joins",
    ])),
    ("bid", "a bid or offer", _rx([
        "bid", "offer", "oferta", "propuesta", "proposta", "ofrece", "ofereix",
    ])),
    ("talks", "talks", _rx([
        "talks", "negotiat", "negocia", "contact", "conversa", "meeting", "reunión", "reunió",
    ])),
    ("interest", "interest", _rx([
        "interest", "interés", "interès", "interesa", "linked", "target", "objetivo", "objectiu",
        "monitor", "eye", "want", "quiere", "vol ", "consider", "sondea", "shortlist", "rumou?r",
        "radar", "agenda", "sueño", "somni", "dream",
    ])),
]

HEDGES = _rx([
    "could", "might", "may ", "would", "consider", "possible", "potential", "podría", "podria",
    "posible", "possible", "planteja", "plantea", "estudia", "valora", "dream", "sueño", "somni",
    "open to", "no descarta",
])
QUOTE = re.compile(r"[\"“«][^\"”»]{12,}[\"”»]")
UNNAMED = _rx([
    "sources", "fuentes", "fonts", "reportedly", "report", "según", "segons", "understood",
    "according to", "informa", "apunta", "claim", "revela", "desvela",
])
ROUNDUP = _rx(["papers", "gossip", "roundup", "round-up", "rumour mill", "live", "rumours", "prensa"])


def _cues(pattern, text):
    return sorted({m.group(0).strip().lower() for m in pattern.finditer(text)})[:3]


def _stage(text):
    for key, phrase, pattern in STAGES:
        if pattern.search(text):
            return key, phrase
    return None, None


def topic_of(text):
    for key, pattern in TOPICS:
        if pattern.search(text):
            return key
    return "other"


def reporting_context(title, summary, translated=""):
    """Plain-language "how to read this" for a transfer story. Judges how
    strongly the article makes its claim and what it cites -- never whether
    the claim is true."""
    text = f"{title} {summary} {translated}"
    # The headline is the claim; long summaries mention side stories.
    stage, phrase = _stage(title)
    if stage is None:
        stage, phrase = _stage(text)
    hedges = _cues(HEDGES, text)
    notes = []

    if stage is None and hedges:
        label = "Tentative report"
        notes.append("Speculates about a move without describing interest, talks or a bid.")
    elif stage is None:
        label = "Transfer talk"
        notes.append("Mentions the transfer market without describing a specific move.")
    elif stage == "official":
        label = "Says it's official"
        notes.append("Describes an official announcement. Check the club's own channels to confirm it.")
    elif stage in ("agreement", "bid") and not hedges:
        label = "Concrete claim"
        notes.append(f"Reports {phrase} as fact, not possibility.")
    elif stage == "talks" and not hedges:
        label = "Reported talks"
        notes.append("Describes talks or contact, not a bid or agreement.")
    else:
        label = "Tentative report"
        notes.append("Describes interest, not talks or a deal." if stage == "interest"
                     else f"Describes {phrase} as a possibility, not a done deal.")

    if hedges:
        notes.append("Uses conditional language (" + ", ".join(f"“{h}”" for h in hedges) + ").")

    if ROUNDUP.search(title):
        sourcing = "Rumour roundup"
        notes.append("Collects other outlets' reports rather than original reporting.")
    elif QUOTE.search(text):
        sourcing = "On-record quote"
        notes.append("Includes a direct quote.")
    elif UNNAMED.search(text):
        sourcing = "Unnamed sources"
        notes.append("Cites unnamed or secondhand sources.")
    else:
        sourcing = "No sourcing given"
        notes.append("Doesn't say where the information comes from.")

    headline_stage, _ = _stage(title)
    body_stage, _ = _stage(summary)
    order = [key for key, _, _ in STAGES]
    if summary and headline_stage and body_stage and order.index(headline_stage) < order.index(body_stage):
        notes.append("The headline makes a stronger claim than the article text.")

    return {
        "stage": stage or "none",
        "label": label,
        "sourcing": sourcing,
        "tentative": bool(hedges) or stage in (None, "interest"),
        "note": " ".join(notes),
    }


def _load(team_name, source):
    """(articles, status) for one feed, translated and tagged."""
    items = _fetch(source["url"])
    status = {"team_name": team_name, "name": source["name"], "lang": source["lang"],
              "kind": source["kind"], "tier": source["tier"], "about": source["about"],
              "ok": items is not None, "count": len(items or [])}
    if not items:
        return [], status

    english = translate([a["title"] for a in items] + [a["summary"] for a in items], source["lang"])
    titles_en, summaries_en = english[: len(items)], english[len(items):]
    translated = source["lang"] != "en" and titles_en[0] is not None
    status["translated"] = translated if source["lang"] != "en" else None

    articles = []
    for article, title_en, summary_en in zip(items, titles_en, summaries_en):
        text_en = f"{title_en or ''} {summary_en or ''}"
        topic = topic_of(f"{article['title']} {article['summary']} {text_en}")
        articles.append({
            **article,
            "title": title_en or article["title"],
            "summary": summary_en or article["summary"],
            "original_title": article["title"] if translated else None,
            "lang": source["lang"],
            "translated": translated,
            "source": source["name"],
            "source_kind": source["kind"],
            "source_tier": source["tier"],
            "source_about": source["about"],
            "team_name": team_name,
            "topic": topic,
            "context": reporting_context(article["title"], article["summary"], text_en)
            if topic == "transfers" else None,
        })
    return articles, status


def for_teams(team_names):
    """Combined, newest-first articles for one or more teams, plus a
    per-source status list so the page can say which feeds failed."""
    jobs = [(team, source) for team in team_names for source in sources_for(team)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: _load(*job), jobs))

    articles = [a for items, _ in results for a in items]
    statuses = [status for _, status in results]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
    articles.sort(key=lambda a: a["published"] or epoch, reverse=True)
    return articles, statuses

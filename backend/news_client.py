"""Per-club news for the favorites newsroom.

Pilot clubs (Barça, Man United) get a curated mix of local and
international RSS feeds; every other La Liga club falls back to its
Guardian feed. Non-English headlines are machine-translated on demand (only the ones
the page shows), and each
article gets a topic plus -- for transfer stories -- a rule-based
"how to read this" note (see reporting_context).

Distinct from routes/news.py's generic Google News query search.
"""
import html
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import requests

from cache import cached

GUARDIAN = "https://www.theguardian.com/football/{slug}/rss"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
PER_SOURCE = 40  # aggregator feeds mix several outlets; single-outlet feeds rarely have this many
HEADERS = {"User-Agent": "Mozilla/5.0 (sports-analyzer news reader)"}


# Editorial judgement of how much to trust each outlet's reporting, shown
# next to every story. Tiers: "high" (established newsroom with a corrections
# policy), "medium" (credible but close to the club or prone to speculation),
# "mixed" (tabloid-style: scoops and misses), "low" (fan-run, unverified).
# Outlets not listed here get no badge, not a guess.
SOURCE_INFO = {
    "The Guardian": ("high", "UK national newspaper with a large football desk and a public corrections policy."),
    "BBC Sport": ("high", "Public broadcaster with a strict impartiality remit; slower on transfer rumours, careful on facts."),
    "Sky Sports": ("high", "Broadcaster whose reporters are frequently first with confirmed transfer news."),
    "The Athletic": ("high", "Subscription sports outlet known for in-depth, well-sourced club reporting."),
    "ESPN": ("high", "Major US sports network with a global football desk; solid on results and confirmed news."),
    "Manchester Evening News": ("high", "Greater Manchester's daily paper; strong on local club news, less so on global transfer scoops."),
    "Ara": ("high", "Catalan-language national daily with independent sports coverage of Barça."),
    "El País": ("high", "Spain's largest national daily; independent, with a well-regarded sports desk."),
    "Gazzetta dello Sport": ("high", "Italy's leading sports daily; the main source for Serie A transfer news, though early reports can fall through."),
    "Corriere dello Sport": ("medium", "Rome sports daily; good local access, but leans toward the Rome clubs."),
    "Tuttosport": ("medium", "Turin sports daily; strong on Juventus and Torino, with a local slant."),
    "Kicker": ("high", "Germany's long-established football magazine; careful and well-sourced on Bundesliga."),
    "Bild": ("mixed", "German tabloid with real scoops and real misses; treat unconfirmed transfer claims with caution."),
    "L'Équipe": ("high", "France's national sports daily; the reference for Ligue 1 news."),
    "RMC Sport": ("medium", "French sports broadcaster; fast on transfers, though early claims are sometimes revised."),
    "Marca": ("medium", "Madrid sports daily, widely read and leaning toward Real Madrid; often runs unconfirmed transfer claims."),
    "AS": ("medium", "Madrid sports daily, leaning toward Real Madrid and Atlético; often runs unconfirmed transfer claims."),
    "Sport": ("medium", "Barcelona sports daily, openly pro-Barça; often runs unconfirmed transfer claims."),
    "Mundo Deportivo": ("medium", "Barcelona sports daily, openly pro-Barça; reliable on club news, but transfer claims are often speculative."),
    "Daily Mail": ("mixed", "UK tabloid; large football coverage with a mixed record on transfer scoops."),
    "The Sun": ("mixed", "UK tabloid; fast on gossip, but many transfer stories do not pan out."),
    "Mirror": ("mixed", "UK tabloid; high volume of rumour-based transfer stories."),
    "The Telegraph": ("high", "UK national broadsheet with a long-running football desk."),
    "Spiegel": ("high", "German news magazine with a strong investigative reputation; light on day-to-day club news."),
    "RTVE.es": ("high", "Spain's public broadcaster; reliable on confirmed news, less on transfer speculation."),
    "FC Barcelona Noticias": ("low", "Fan-run news site; useful for volume, but stories are often rewritten from other outlets without checking."),
}
_INFO_BY_NAME = {name.casefold(): info for name, info in SOURCE_INFO.items()}
_ALIASES = {"as.com": "as", "marca.com": "marca", "sport.es": "sport", "mirror.co.uk": "mirror",
            "dailymail.co.uk": "daily mail", "bbc.com": "bbc sport", "espn.com": "espn",
            "elpais.com": "el país", "la gazzetta dello sport": "gazzetta dello sport", "bbc": "bbc sport",
            "the daily mail": "daily mail", "daily mirror": "mirror", "spiegel.de": "spiegel", "bild.de": "bild", "kicker.de": "kicker"}


def _is_club_site(outlet, team_name):
    """'Arsenal.com' / 'Real Madrid CF | Web Oficial' / 'Inter.it' for the team they cover."""
    base = re.split(r"\s*[|·]\s*", outlet.casefold())[0]
    base = re.sub(r"\.(com|it|es|de|fr|net|org|co\.uk)$", "", base).strip()
    name = _search_name(team_name).casefold()
    return all(w in base for w in name.split()) or (len(base) >= 4 and name.startswith(base))


CLUB_SITE = ("club", "Published by the club itself: accurate on its own announcements, but not independent reporting.")


def _info(name, team_name=None):
    key = (name or "").casefold().strip()
    known = _INFO_BY_NAME.get(_ALIASES.get(key, key))
    if known:
        return known
    return CLUB_SITE if name and team_name and _is_club_site(name, team_name) else (None, None)


def _source(name, url, lang="en", kind="international"):
    tier, about = _info(name)
    return {"name": name, "url": url, "lang": lang, "kind": kind, "tier": tier, "about": about}


# Google News edition and search keyword per league, so any followed team
# gets local-language press without a hand-curated list.
GOOGLE_NEWS = "https://news.google.com/rss/search"
LEAGUE_LOCALE = {
    "PD": ("es", "ES", "fútbol"),
    "PL": ("en", "GB", "football"),
    "SA": ("it", "IT", "calcio"),
    "BL1": ("de", "DE", "Fußball"),
    "FL1": ("fr", "FR", "football"),
}
_LEGAL = {"fc", "cf", "afc", "sc", "rc", "rcd", "ud", "ca", "cd", "sd", "ac", "ssc", "us", "bsc", "sv", "tsg", "vfl", "vfb"}


def _search_name(team_name):
    """'RCD Espanyol de Barcelona' -> 'Espanyol de Barcelona': legal-form
    prefixes and suffixes make poor news queries."""
    words = team_name.split()
    while len(words) > 1 and words[0].casefold() in _LEGAL:
        words.pop(0)
    while len(words) > 1 and words[-1].casefold() in _LEGAL:
        words.pop()
    return " ".join(words)


def _google_source(team_name, league):
    lang, country, keyword = LEAGUE_LOCALE[league]
    query = f'"{_search_name(team_name)}" {keyword} when:7d'
    params = {"q": query, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
    return {"name": "Google News", "url": f"{GOOGLE_NEWS}?{urlencode(params)}", "lang": lang,
            "kind": "local", "tier": None, "about": None, "aggregate": True}


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


def sources_for(team_name, league=None):
    if team_name in CLUB_SOURCES:
        return CLUB_SOURCES[team_name]
    sources = []
    slug = TEAM_SLUGS.get(team_name)
    if slug:
        sources.append(_source("The Guardian", GUARDIAN.format(slug=slug)))
    if league in LEAGUE_LOCALE:
        sources.append(_google_source(team_name, league))
    return sources


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
        outlet = _clean(item.findtext("source")) or None
        title = _clean(item.findtext("title"))
        # Google News titles end in " - Outlet"; its description is just related links.
        summary = "" if outlet else _clean(item.findtext("description"))
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(outlet) - 3]
        items.append(
            {
                "outlet": outlet,
                "title": title,
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


# ponytail: process-lifetime cache keyed by text, never pruned; a feed's
# worth of headlines a day is tiny next to a restart cycle.
_deepl_cache = {}


def _deepl(texts, key):
    """DeepL API Free (monthly character quota): only texts not seen before are
    sent, so a feed that refreshes every 30 minutes costs only its new items."""
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    missing = list(dict.fromkeys(t for t in texts if t not in _deepl_cache))
    for i in range(0, len(missing), 50):
        chunk = missing[i : i + 50]
        response = requests.post(
            f"https://{host}/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
            json={"text": chunk, "target_lang": "EN-US"},
            timeout=15,
        )
        response.raise_for_status()
        _deepl_cache.update(zip(chunk, (t["text"] for t in response.json()["translations"])))
    return [_deepl_cache[t] for t in texts]


def _metered():
    return bool(os.environ.get("DEEPL_API_KEY"))


def translate(texts, lang):
    """English translations of texts (same order), or all None if it
    failed -- the caller then shows the originals instead. Uses DeepL when
    DEEPL_API_KEY is set, else the unofficial Google endpoint. Backs off
    for 10 minutes after a failure so a 429 isn't prolonged by every page load."""
    global _retry_after
    if lang == "en":
        return list(texts)
    if time.monotonic() < _retry_after:
        return [None] * len(texts)
    texts = [t or "-" for t in texts]
    try:
        if _metered():
            return _deepl(texts, os.environ["DEEPL_API_KEY"])
        return list(_translate_lines(tuple(texts), lang))
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
        # it / de / fr
        "calciomercato", "trattativa", "acquisto", "prestito", "riscatto", "rinnov", "contratto", "ingaggio",
        "wechsel", "verpflicht", "leihe", "ablöse", "vertrag", "angebot", "transfert", "recrue", "prolong", "mercato",
    ])),
    ("injuries", _rx([
        "injur", "lesión", "lesion", "lesió", "hamstring", "isquio", "knock", "sidelined", "baja",
        "fitness", "recovery", "recupera", "surgery", "operad", "quirófano", "out for",
        "infortun", "infermeria", "lesione", "indisponibil", "verletz", "ausfall", "fällt aus", "muskel",
        "blessure", "blessé", "forfait",
    ])),
    ("club", _rx([
        "president", "laporta", "ratcliffe", "glazer", "board", "junta", "financ", "revenue", "debt",
        "deuda", "deute", "stadium", "estadio", "estadi", "camp nou", "old trafford", "asamblea",
        "assemblea", "election", "kit", "camiseta", "samarreta", "sponsor", "fair play",
        "président", "präsident", "stadio", "stadion", "bilancio", "vorstand",
    ])),
    ("matches", _rx([
        "vs", "v ", "preview", "player ratings", "ratings", "result", "draw", "defeat", "win ",
        "victoria", "victòria", "derrota", "empate", "empat", "crónica", "previa", "alineación",
        "lineup", "line-up", "goal", "gol", "champions", "liga", "premier league", "cup", "copa",
        "partita", "sconfitta", "pareggio", "formazioni", "pagelle", "serie a", "spiel", "niederlage", "sieg",
        "unentschieden", "aufstellung", "bundesliga", "pokal", "match", "défaite", "victoire", "compo", "ligue 1", "coupe",
    ])),
]

# Strongest first: the first stage that matches is the claim being made.
STAGES = [
    ("official", "an official announcement", _rx([
        # Not "confirm": "no bid has been confirmed" / "Laporta confirma el interés".
        "official", "oficial", "announce", "anuncia", "unveil", "completes", "ufficial", "offiziell", "officiel",
    ])),
    ("agreement", "an agreement", _rx([
        "agreement", "agreed", "acuerdo", "acord", "here we go", "deal done", "pre-contract",
        "precontrato", "medical", "revisión médica", "revisió mèdica", "seal", "close on",
        # Not bare "sign": "race to sign" / "want to sign" is interest.
        "closes in", "cierra", "tanca", "firma", "signs", "llega", "arriba", "joins",
        "accordo", "visite mediche", "è fatta", "einigung", "vereinbar", "accord", "visite médicale",
    ])),
    ("bid", "a bid or offer", _rx([
        "bid", "offer", "oferta", "propuesta", "proposta", "ofrece", "ofereix", "offerta", "angebot", "offre",
    ])),
    ("talks", "talks", _rx([
        "talks", "negotiat", "negocia", "contact", "conversa", "meeting", "reunión", "reunió",
        "trattativa", "verhandl", "gespräch", "négoci", "discussions",
    ])),
    ("interest", "interest", _rx([
        "interest", "interés", "interès", "interesa", "linked", "target", "objetivo", "objectiu",
        "monitor", "eye", "want", "quiere", "vol ", "consider", "sondea", "shortlist", "rumou?r",
        "radar", "agenda", "sueño", "somni", "dream", "interesse", "interessiert", "intérêt", "mirino", "obiettivo",
    ])),
]

HEDGES = _rx([
    "could", "might", "may ", "would", "consider", "possible", "potential", "podría", "podria",
    "posible", "possible", "planteja", "plantea", "estudia", "valora", "dream", "sueño", "somni",
    "open to", "no descarta", "potrebbe", "forse", "könnte", "vielleicht", "pourrait", "peut-être",
])
QUOTE = re.compile(r"[\"“«][^\"”»]{12,}[\"”»]")
UNNAMED = _rx([
    "sources", "fuentes", "fonts", "reportedly", "report", "según", "segons", "understood",
    "according to", "informa", "apunta", "claim", "revela", "desvela", "fonti", "quellen", "laut ", "selon",
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
    """(articles, statuses) for one feed, tagged but not translated -- the
    page asks /news/translate for just the headlines it shows. Aggregator
    feeds (Google News) mix outlets, so they report one status per outlet."""
    items = _fetch(source["url"])
    base = {"team_name": team_name, "name": source["name"], "lang": source["lang"], "kind": source["kind"],
            "tier": source["tier"], "about": source["about"]}
    if not items:
        return [], [{**base, "ok": items is not None, "count": 0}]

    articles, counts = [], {}
    for article in items:
        article = dict(article)
        outlet = article.pop("outlet", None)
        name = outlet or source["name"]
        tier, about = _info(outlet, team_name) if outlet else (source["tier"], source["about"])
        counts[name] = counts.get(name, 0) + 1
        topic = topic_of(f"{article['title']} {article['summary']}")
        articles.append({
            **article,
            "lang": source["lang"],
            "source": name,
            "source_kind": source["kind"],
            "source_tier": tier,
            "source_about": about,
            "team_name": team_name,
            "topic": topic,
            "context": reporting_context(article["title"], article["summary"])
            if topic == "transfers" else None,
        })
    statuses = [
        {**base, "name": name, **dict(zip(("tier", "about"), _info(name, team_name) if source.get("aggregate") else (base["tier"], base["about"]))),
         "ok": True, "count": count}
        for name, count in counts.items()
    ]
    return articles, statuses


def for_teams(team_specs):
    """Combined, newest-first articles for one or more teams, plus a
    per-source status list so the page can say which feeds failed. Each
    spec is "Team Name" or "Team Name@PD" -- the league picks the language
    of the auto-discovered local press."""
    teams = [spec.partition("@")[::2] for spec in team_specs]
    jobs = [(name, source) for name, league in teams for source in sources_for(name, league or None)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: _load(*job), jobs))

    articles = [a for items, _ in results for a in items]
    statuses = [status for _, group in results for status in group]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
    articles.sort(key=lambda a: a["published"] or epoch, reverse=True)
    return articles, statuses

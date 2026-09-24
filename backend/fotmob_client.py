import json
import re
import unicodedata

import requests

from cache import cached

BASE_URL = "https://www.fotmob.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# FotMob's numeric league ids + URL slugs for our 5 supported competitions.
# FotMob has no public/keyed API for this (its API gateway requires signed
# request headers), but its match-center pages are server-rendered with the
# full page state embedded in a `__NEXT_DATA__` script tag, so a plain GET
# + JSON parse gets the same data without a browser.
LEAGUE_MAP = {
    "PD": (87, "laliga"),  # La Liga
    "PL": (47, "premier-league"),  # Premier League
    "SA": (55, "serie-a"),  # Serie A
    "BL1": (54, "bundesliga"),  # Bundesliga
    "FL1": (53, "ligue-1"),  # Ligue 1
}

POSITION_GROUPS = {0: "GK", 1: "DEF", 2: "MID", 3: "FWD"}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class FotMobError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _fetch_page_props(path):
    try:
        response = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=10)
    except requests.exceptions.RequestException as e:
        raise FotMobError(f"Could not reach FotMob: {e}", status_code=502)

    if not response.ok:
        raise FotMobError(f"Unexpected FotMob response ({response.status_code}).", status_code=502)

    match = _NEXT_DATA_RE.search(response.text)
    if not match:
        raise FotMobError("Could not find FotMob's embedded page data.", status_code=502)

    try:
        data = json.loads(match.group(1))
    except ValueError as e:
        raise FotMobError(f"Could not parse FotMob's embedded page data: {e}", status_code=502)

    return data["props"]["pageProps"]


# FotMob's own team names already have common legal-form suffixes/words
# stripped (e.g. "Villarreal" not "Villarreal CF", "Levante" not "Levante
# UD"), but football-data.org's don't — so normalization has to drop these
# as whole words, not just as substrings, to line the two up.
_STRIP_WORDS = {"fc", "cf", "ud", "sd", "cd", "rcd", "ca", "afc", "ac", "sad", "and", "hove", "albion"}


# Exact provider aliases, checked against each supported league's club list.
# Avoid fuzzy/substring matching: similarly named clubs must stay distinct.
_TEAM_ALIASES = {
    official.casefold(): fotmob
    for official, fotmob in {
        "Club Atlético de Madrid": "Atlético Madrid",
        "RCD Espanyol de Barcelona": "Espanyol",
        "Rayo Vallecano de Madrid": "Rayo Vallecano",
        "Real Betis Balompié": "Real Betis",
        "Real Sociedad de Fútbol": "Real Sociedad",
        "RC Celta de Vigo": "Celta Vigo",
        "RC Deportivo La Coruña": "Deportivo A Coruña",
        "Real Racing Club de Santander": "Racing Santander",
        "ACF Fiorentina": "Fiorentina",
        "AS Roma": "Roma",
        "Atalanta BC": "Atalanta",
        "Bologna FC 1909": "Bologna",
        "Cagliari Calcio": "Cagliari",
        "Genoa CFC": "Genoa",
        "FC Internazionale Milano": "Inter",
        "SS Lazio": "Lazio",
        "Parma Calcio 1913": "Parma",
        "SSC Napoli": "Napoli",
        "Udinese Calcio": "Udinese",
        "Frosinone Calcio": "Frosinone",
        "US Sassuolo Calcio": "Sassuolo",
        "US Lecce": "Lecce",
        "Como 1907": "Como",
        "TSG 1899 Hoffenheim": "Hoffenheim",
        "Bayer 04 Leverkusen": "Bayer Leverkusen",
        "SV Werder Bremen": "Werder Bremen",
        "1. FSV Mainz 05": "Mainz 05",
        "SC Freiburg": "Freiburg",
        "1. FC Union Berlin": "Union Berlin",
        "SC Paderborn 07": "Paderborn",
        "SV 07 Elversberg": "Elversberg",
        "Stade Brestois 29": "Brest",
        "Olympique de Marseille": "Marseille",
        "AJ Auxerre": "Auxerre",
        "Lille OSC": "Lille",
        "OGC Nice": "Nice",
        "Olympique Lyonnais": "Lyon",
        "Stade Rennais FC 1901": "Rennes",
        "ES Troyes AC": "Troyes",
        "Angers SCO": "Angers",
        "Racing Club de Lens": "Lens",
        "AS Monaco FC": "Monaco",
        "RC Strasbourg Alsace": "Strasbourg",
    }.items()
}


def _normalize(name):
    name = _TEAM_ALIASES.get((name or "").casefold(), name or "")
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    words = re.findall(r"\w+", name.casefold())
    return " ".join(w for w in words if w not in _STRIP_WORDS)


@cached(ttl_seconds=300)
def find_fixture(league_code, date, home_name, away_name):
    """Resolve a (league, date, home, away) match to a FotMob fixture by
    scanning that league's season fixture list for a same-day, name match.

    Returns a dict with the fixture's FotMob id and page URL, or None for
    "no confident match" (unmapped league, name mismatch, or no fixture
    that day) — an expected, common outcome the caller should treat as an
    empty state rather than an error.
    """
    mapping = LEAGUE_MAP.get(league_code)
    if mapping is None:
        return None
    league_id, slug = mapping

    page_props = _fetch_page_props(f"/leagues/{league_id}/matches/{slug}")
    all_matches = (page_props.get("fixtures") or {}).get("allMatches") or []

    home_norm = _normalize(home_name)
    away_norm = _normalize(away_name)

    for fixture in all_matches:
        status = fixture.get("status") or {}
        if not (status.get("utcTime") or "").startswith(date):
            continue
        if (
            _normalize((fixture.get("home") or {}).get("name")) == home_norm
            and _normalize((fixture.get("away") or {}).get("name")) == away_norm
        ):
            return {"id": fixture.get("id"), "page_url": fixture.get("pageUrl")}

    return None


@cached(ttl_seconds=60)
def fetch_match_content(page_url):
    page_props = _fetch_page_props(page_url)
    content = page_props.get("content") or {}
    colors = (page_props.get("general") or {}).get("teamColors", {}).get("darkMode", {})
    event = (page_props.get("seo") or {}).get("eventJSONLD") or {}
    content["teamAssets"] = {
        side: {"crest": (event.get(f"{side}Team") or {}).get("logo"), "color": colors.get(side)}
        for side in ("home", "away")
    }
    return content

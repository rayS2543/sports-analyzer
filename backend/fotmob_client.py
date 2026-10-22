import json
import re
import unicodedata
import xml.etree.ElementTree as ET

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
    "CL": (42, "champions-league"),  # Champions League
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
        "Club Brugge KV": "Club Brugge",
        "FK Bodø/Glimt": "Bodø/Glimt",
        "FK Shakhtar Donetsk": "Shakhtar Donetsk",
        "Fenerbahçe SK": "Fenerbahçe",
        "Feyenoord Rotterdam": "Feyenoord",
        "Galatasaray SK": "Galatasaray",
        "LASK Linz": "LASK",
        "PAE AEK": "AEK Athens",
        "PSV": "PSV Eindhoven",
        "SK Slavia Praha": "Slavia Prague",
        "Sporting Clube de Portugal": "Sporting CP",
        "Viking FK": "Viking",
        "ŠK Slovan Bratislava": "Slovan Bratislava",
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


@cached(ttl_seconds=300)
def _table_places(url):
    """{team_id: place} from the FotMob table feed (XML, rows already in rank order)."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        rows = ET.fromstring(response.text).iter("t") if response.ok else []
        return {int(row.get("id")): place for place, row in enumerate(rows, start=1)}
    except (requests.exceptions.RequestException, ET.ParseError, TypeError, ValueError):
        return {}


def _goal_events(header):
    events = header.get("events") or {}
    goals = []
    for side, key in (("home", "homeTeamGoals"), ("away", "awayTeamGoals")):
        for entries in (events.get(key) or {}).values():
            for e in entries:
                if e.get("isPenaltyShootout"):
                    continue
                goals.append(
                    {
                        "side": side,
                        "player_id": (e.get("player") or {}).get("id"),
                        "name": (e.get("player") or {}).get("name"),
                        "minute": e.get("time"),
                        "added": e.get("overloadTime"),
                        "own_goal": bool(e.get("ownGoal")),
                    }
                )
    goals.sort(key=lambda g: (g["minute"] or 0, g["added"] or 0))
    return goals


@cached(ttl_seconds=60)
def fetch_match_content(page_url):
    page_props = _fetch_page_props(page_url)
    content = page_props.get("content") or {}
    header = page_props.get("header") or {}
    teams = header.get("teams") or []
    table_url = (content.get("table") or {}).get("url")
    places = _table_places(table_url) if table_url else {}
    content["summary"] = {
        "started": bool((header.get("status") or {}).get("started")),
        "scores": [t.get("score") for t in teams[:2]] if len(teams) == 2 else None,
        "goals": _goal_events(header),
        "places": [places.get(t.get("id")) for t in teams[:2]] if len(teams) == 2 else None,
    }
    colors = (page_props.get("general") or {}).get("teamColors", {}).get("darkMode", {})
    event = (page_props.get("seo") or {}).get("eventJSONLD") or {}
    content["teamAssets"] = {
        side: {"crest": (event.get(f"{side}Team") or {}).get("logo"), "color": colors.get(side)}
        for side in ("home", "away")
    }
    return content

"""Per-club Guardian RSS feeds, for the favorites news feed.

Distinct from routes/news.py's generic Google News query search: this
is scoped per club (no keyword filtering needed) for teams the mapping
below covers. La Liga only for now -- other leagues need their own
slug entries before favoriting a team there returns anything.
"""
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

from cache import cached

FEED_URL = "https://www.theguardian.com/football/{slug}/rss"

TEAM_SLUGS = {
    "FC Barcelona": "barcelona",
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


@cached(ttl_seconds=1800)
def _fetch(slug):
    """Fetch and parse one club's feed. Degrades to an empty list on any
    failure rather than ever breaking the page it's on -- same policy as
    routes/news.py's Google News search."""
    try:
        response = requests.get(FEED_URL.format(slug=slug), timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return []

    items = []
    for item in root.findall("./channel/item"):
        items.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
            }
        )
    return items


def _published_at(article):
    try:
        return parsedate_to_datetime(article["published"])
    except (TypeError, ValueError):
        return parsedate_to_datetime("Thu, 1 Jan 1970 00:00:00 GMT")


def for_teams(team_names):
    """Combined, newest-first articles for one or more teams. Teams with
    no known slug contribute nothing rather than raising."""
    articles = []
    for team_name in team_names:
        slug = TEAM_SLUGS.get(team_name)
        if slug is None:
            continue
        articles.extend(dict(a, team_name=team_name) for a in _fetch(slug))

    articles.sort(key=_published_at, reverse=True)
    return articles

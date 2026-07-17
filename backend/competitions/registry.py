"""Registry of soccer competitions the platform aims to support.

Mirrors the competitions listed in the project vision. `provider_code`
is the football-data.org competition code for competitions available
on their free tier; it is None where that provider doesn't offer the
competition, which marks where a future data provider needs to plug
in before that competition actually works.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Competition:
    slug: str
    name: str
    category: str  # "domestic", "international", "women"
    provider_code: Optional[str]  # football-data.org code, or None if unsupported today


COMPETITIONS = [
    # Domestic leagues
    Competition("premier-league", "Premier League", "domestic", "PL"),
    Competition("la-liga", "La Liga", "domestic", "PD"),
    Competition("serie-a", "Serie A", "domestic", "SA"),
    Competition("bundesliga", "Bundesliga", "domestic", "BL1"),
    Competition("ligue-1", "Ligue 1", "domestic", "FL1"),
    Competition("mls", "MLS", "domestic", None),
    Competition("eredivisie", "Eredivisie", "domestic", "DED"),
    Competition("liga-portugal", "Liga Portugal", "domestic", "PPL"),
    Competition("championship", "Championship", "domestic", "ELC"),
    # International competitions
    Competition("champions-league", "Champions League", "international", "CL"),
    Competition("europa-league", "Europa League", "international", None),
    Competition("conference-league", "Conference League", "international", None),
    Competition("club-world-cup", "FIFA Club World Cup", "international", "CLI"),
    Competition("world-cup", "World Cup", "international", "WC"),
    Competition("euros", "UEFA European Championship", "international", "EC"),
    Competition("copa-america", "Copa America", "international", None),
    Competition("nations-league", "Nations League", "international", None),
    # Women's football
    Competition("wsl", "WSL", "women", None),
    Competition("nwsl", "NWSL", "women", None),
    Competition("liga-f", "Liga F", "women", None),
    Competition("womens-champions-league", "Women's Champions League", "women", None),
    Competition("womens-world-cup", "Women's World Cup", "women", None),
]

_BY_SLUG = {c.slug: c for c in COMPETITIONS}

DEFAULT_COMPETITION_SLUG = "la-liga"


def get_competition(slug):
    return _BY_SLUG.get(slug)


def list_competitions():
    return list(COMPETITIONS)

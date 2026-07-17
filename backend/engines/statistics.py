"""Statistics engine: orchestrates repositories into the shapes the API
layer returns. This is where the platform's actual working logic lives
today -- standings, recent matches, and team form -- until the
tactical/prediction/betting engines have real data sources to draw on.
"""
from datetime import datetime, timedelta

from backend.cache import TTLCache
from backend.competitions.registry import DEFAULT_COMPETITION_SLUG, get_competition
from backend.config import config


class UnsupportedCompetitionError(Exception):
    pass


class TeamNotFoundError(Exception):
    pass


class StatisticsEngine:
    def __init__(self, team_repository, match_repository):
        self.teams = team_repository
        self.matches = match_repository
        self._matches_cache = TTLCache(config.MATCHES_CACHE_TTL_SECONDS)

    def _provider_code(self, competition_slug):
        competition = get_competition(competition_slug)
        if competition is None or competition.provider_code is None:
            raise UnsupportedCompetitionError(competition_slug)
        return competition.provider_code

    def recent_matches(self, competition_slug=DEFAULT_COMPETITION_SLUG, days=10):
        provider_code = self._provider_code(competition_slug)

        cached = self._matches_cache.get_fresh()
        if cached is not None:
            return cached

        today = datetime.utcnow().date()
        date_from = (today - timedelta(days=days)).isoformat()
        date_to = today.isoformat()

        try:
            result = self.matches.recent_matches(provider_code, date_from, date_to)
        except Exception:
            stale = self._matches_cache.get_stale()
            if stale is not None:
                return stale
            raise

        self._matches_cache.set(result)
        return result

    def standings(self, competition_slug=DEFAULT_COMPETITION_SLUG):
        provider_code = self._provider_code(competition_slug)
        return self.teams.standings(provider_code)

    def team_profile(self, team_name, competition_slug=DEFAULT_COMPETITION_SLUG):
        provider_code = self._provider_code(competition_slug)
        team = self.teams.find_team(provider_code, team_name)
        if team is None:
            raise TeamNotFoundError(team_name)

        team["last_5_matches"] = self.matches.team_recent_form(team["id"], limit=5)
        return team

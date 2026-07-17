"""Interface every competition data adapter must implement.

An adapter's job is to turn a specific upstream provider's response
shape into the plain dicts the rest of the backend expects. Supporting
a new provider, or a competition only a different provider covers,
means adding an adapter here rather than touching engines or routes.
"""
from abc import ABC, abstractmethod


class CompetitionAdapter(ABC):
    @abstractmethod
    def get_standings(self, competition_code):
        """Return the TOTAL standings table (list of raw entries) for a competition."""

    @abstractmethod
    def get_matches(self, competition_code, date_from, date_to):
        """Return raw matches for a competition within a date range."""

    @abstractmethod
    def get_team_recent_matches(self, team_id, limit=5):
        """Return the most recent finished matches for a team, most recent first."""

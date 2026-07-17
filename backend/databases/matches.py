"""Match repository: recent league matches and per-team recent form."""
from backend.domain.models import match_to_result_summary, match_to_team_form_entry


class MatchRepository:
    def __init__(self, adapter):
        self.adapter = adapter

    def recent_matches(self, competition_code, date_from, date_to):
        matches = self.adapter.get_matches(competition_code, date_from, date_to)
        summaries = [match_to_result_summary(m) for m in matches]
        summaries.sort(key=lambda m: (m["date"], m["home"], m["away"]))
        return summaries

    def team_recent_form(self, team_id, limit=5):
        matches = self.adapter.get_team_recent_matches(team_id, limit=limit)
        return [match_to_team_form_entry(m, team_id) for m in matches]

"""CompetitionAdapter backed by football-data.org."""
from backend.adapters.base import CompetitionAdapter
from backend.data_ingestion.football_data_client import FootballDataClient, FootballDataError


class FootballDataAdapter(CompetitionAdapter):
    def __init__(self, client=None):
        self.client = client or FootballDataClient()

    def get_standings(self, competition_code):
        data = self.client.get(f"/competitions/{competition_code}/standings")
        standings = data.get("standings", [])
        if not standings:
            raise FootballDataError("No standings returned", 500)

        total = next((s for s in standings if s.get("type") == "TOTAL"), standings[0])
        return total.get("table", [])

    def get_matches(self, competition_code, date_from, date_to):
        data = self.client.get(
            "/matches",
            params={"competitions": competition_code, "dateFrom": date_from, "dateTo": date_to},
        )
        return data.get("matches", [])

    def get_team_recent_matches(self, team_id, limit=5):
        data = self.client.get(f"/teams/{team_id}/matches", params={"status": "FINISHED", "limit": limit})
        matches = data.get("matches", [])
        matches.sort(key=lambda m: m["utcDate"], reverse=True)
        return matches[:limit]

"""Team repository.

Named `TeamRepository` rather than `TeamDatabase` even though the
project's target architecture calls this a "database" -- today it's a
read-through layer over the competition adapter, not real storage.
When persisted player/team profiles (injuries, market values,
contracts) get built, they slot in behind this same interface.
"""
from backend.domain.models import standing_entry_to_dict


class TeamRepository:
    def __init__(self, adapter):
        self.adapter = adapter

    def standings(self, competition_code):
        table = self.adapter.get_standings(competition_code)
        entries = [standing_entry_to_dict(entry) for entry in table]
        entries.sort(key=lambda e: e["position"] if e["position"] is not None else 999)
        return entries

    def find_team(self, competition_code, name_or_tla):
        needle = name_or_tla.lower()
        table = self.adapter.get_standings(competition_code)
        for entry in table:
            team = entry.get("team", {})
            name = team.get("name", "").lower()
            tla = team.get("tla", "").lower()
            if needle in name or name in needle or needle == tla:
                result = standing_entry_to_dict(entry)
                result["id"] = team.get("id")
                return result
        return None

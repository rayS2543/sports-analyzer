"""Similarity engine -- not yet implemented.

Will find statistically or tactically similar players/teams once the
player repository has real advanced metrics to compare on.
"""


class SimilarityEngine:
    def similar_players(self, player_id, limit=5):
        raise NotImplementedError("Player data provider not yet integrated")

    def similar_teams(self, team_id, limit=5):
        raise NotImplementedError("Tactical/statistical fingerprints not yet available")

"""Tactical intelligence engine -- not yet implemented.

Needs event-level data (pressing triggers, buildup sequences,
defensive line height) that football-data.org doesn't provide. This is
where formation/pressing-style/build-up explanations from the vision
doc will live once a tracking or event-data provider is wired in.
"""


class TacticalEngine:
    def team_identity(self, team_id):
        raise NotImplementedError("Tactical data provider not yet integrated")

    def explain_concept(self, concept, team_id=None):
        raise NotImplementedError("Tactical data provider not yet integrated")

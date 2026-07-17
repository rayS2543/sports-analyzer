"""Report generator -- not yet implemented.

Will turn engine output (statistics today, tactical/prediction later)
into the narrative match/team reports described in the vision doc.
"""


class ReportGenerator:
    def match_report(self, match_id):
        raise NotImplementedError("Report generation not yet implemented")

    def team_report(self, team_id):
        raise NotImplementedError("Report generation not yet implemented")

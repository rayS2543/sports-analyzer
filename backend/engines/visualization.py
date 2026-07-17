"""Visualization engine -- not yet implemented.

Will prepare chart-ready data (shot maps, passing networks, xG charts,
radar charts, etc.) for the frontend once event-level match data is
available. Standings/form already flow straight from the statistics
engine today since they need no extra shaping for charting.
"""


class VisualizationEngine:
    def shot_map(self, match_id):
        raise NotImplementedError("Event-level match data not yet integrated")

    def passing_network(self, match_id):
        raise NotImplementedError("Event-level match data not yet integrated")

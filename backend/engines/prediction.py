"""Prediction engine -- not yet implemented.

Match/score/award probability models from the vision doc need a
historical dataset and a trained model before this can return real
confidence-scored predictions instead of a stub.
"""


class PredictionEngine:
    def match_probabilities(self, home_team_id, away_team_id):
        raise NotImplementedError("Prediction models not yet trained")

    def score_prediction(self, home_team_id, away_team_id):
        raise NotImplementedError("Prediction models not yet trained")

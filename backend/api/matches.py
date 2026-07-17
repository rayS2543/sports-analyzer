"""HTTP routes for match data."""
from flask import Blueprint, jsonify

from backend.data_ingestion.football_data_client import FootballDataError
from backend.engines.statistics import UnsupportedCompetitionError


def create_matches_blueprint(statistics_engine):
    bp = Blueprint("matches", __name__)

    @bp.route("/matches")
    def get_matches():
        try:
            return jsonify(statistics_engine.recent_matches())
        except UnsupportedCompetitionError as e:
            return jsonify({"error": f"Competition '{e}' is not supported yet"}), 400
        except FootballDataError as e:
            return jsonify({"error": "Failed to fetch matches", "status": e.status_code}), 500

    return bp

"""HTTP routes for standings and team stats."""
from flask import Blueprint, jsonify

from backend.data_ingestion.football_data_client import FootballDataError
from backend.engines.statistics import TeamNotFoundError, UnsupportedCompetitionError


def create_standings_blueprint(statistics_engine):
    bp = Blueprint("standings", __name__)

    @bp.route("/standings")
    def get_standings():
        try:
            return jsonify(statistics_engine.standings())
        except UnsupportedCompetitionError as e:
            return jsonify({"error": f"Competition '{e}' is not supported yet"}), 400
        except FootballDataError as e:
            return jsonify({"error": "Unexpected API response", "status": e.status_code}), 500

    @bp.route("/standings/<team_name>")
    def get_team_stats(team_name):
        try:
            return jsonify(statistics_engine.team_profile(team_name))
        except TeamNotFoundError:
            return jsonify({"error": f"Team '{team_name}' not found in standings."}), 404
        except UnsupportedCompetitionError as e:
            return jsonify({"error": f"Competition '{e}' is not supported yet"}), 400
        except FootballDataError as e:
            return jsonify({"error": "Unexpected API response", "status": e.status_code}), 500

    return bp

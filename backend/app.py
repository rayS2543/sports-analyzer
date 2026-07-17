"""Application factory: wires adapters, repositories, and engines into
Flask blueprints. Business logic lives in engines/repositories/adapters
(see backend/README.md); this file only assembles them.
"""
from flask import Flask
from flask_cors import CORS

from backend.adapters.football_data_adapter import FootballDataAdapter
from backend.api.competitions import competitions_bp
from backend.api.health import health_bp
from backend.api.matches import create_matches_blueprint
from backend.api.standings import create_standings_blueprint
from backend.conversation.memory import ConversationMemory
from backend.databases.matches import MatchRepository
from backend.databases.teams import TeamRepository
from backend.engines.statistics import StatisticsEngine


def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    CORS(app)

    adapter = FootballDataAdapter()
    team_repository = TeamRepository(adapter)
    match_repository = MatchRepository(adapter)
    statistics_engine = StatisticsEngine(team_repository, match_repository)

    # Not wired to any route yet -- scaffolding for the future AI chat layer.
    app.conversation_memory = ConversationMemory()

    app.register_blueprint(health_bp)
    app.register_blueprint(competitions_bp)
    app.register_blueprint(create_matches_blueprint(statistics_engine))
    app.register_blueprint(create_standings_blueprint(statistics_engine))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

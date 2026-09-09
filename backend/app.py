from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from routes.football import football_bp
from routes.matches_detail import matches_detail_bp
from routes.news import news_bp
from routes.players import players_bp
from routes.predictions import predictions_bp

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    CORS(app)

    @app.route("/")
    def home():
        return jsonify({"message": "Sports Analyzer backend running"})

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    app.register_blueprint(football_bp)
    app.register_blueprint(predictions_bp)
    app.register_blueprint(matches_detail_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(news_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS

from routes.football import football_bp
from routes.predictions import predictions_bp

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False
    CORS(app)

    @app.route("/")
    def home():
        return jsonify({"message": "Sports Analyzer backend running"})

    app.register_blueprint(football_bp)
    app.register_blueprint(predictions_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

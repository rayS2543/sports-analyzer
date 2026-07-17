from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/")
def home():
    return jsonify({"message": "Sports Analyzer backend running"})

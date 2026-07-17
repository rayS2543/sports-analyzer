"""HTTP route listing the competitions the platform targets, and which
of them are actually wired up to a data provider today."""
from flask import Blueprint, jsonify

from backend.competitions.registry import list_competitions

competitions_bp = Blueprint("competitions", __name__)


@competitions_bp.route("/competitions")
def get_competitions():
    return jsonify([
        {
            "slug": c.slug,
            "name": c.name,
            "category": c.category,
            "supported": c.provider_code is not None,
        }
        for c in list_competitions()
    ])

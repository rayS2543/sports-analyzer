# Prediction endpoints are implemented on top of this blueprint.
# See backend/elo.py for the rating model.
from flask import Blueprint

predictions_bp = Blueprint("predictions", __name__)

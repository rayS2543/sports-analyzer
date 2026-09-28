"""Discover candidate footage; availability is not evidence of a VAR incident."""
import re
from datetime import date
from urllib.parse import urlsplit

import requests
from flask import Blueprint, jsonify, request

from cache import cached

var_clips_bp = Blueprint("var_clips", __name__)
ESPN_LEAGUES = {"PD": "esp.1", "PL": "eng.1", "SA": "ita.1", "BL1": "ger.1", "FL1": "fra.1"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


@cached(ttl_seconds=900)
def _get(league, resource, **params):
    response = requests.get(f"{BASE}/{ESPN_LEAGUES[league]}/{resource}", params=params, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected ESPN response")
    return payload


def _https_url(value, hosts):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username and not parsed.password and parsed.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


def clip_list(league, event_id):
    """Clips ESPN lists for an event; the only trusted source of footage URLs."""
    result = []
    for video in _get(league, "summary", event=event_id).get("videos", []):
        links = video.get("links") or {}
        source = _https_url((links.get("source") or {}).get("href"), {"espnmedia-cdn.akamaized.net"})
        page = _https_url((links.get("web") or {}).get("href"), {"www.espn.com", "espn.com"})
        if not source and not page:
            continue
        result.append({"id": str(video["id"]), "title": video.get("headline"), "duration_seconds": video.get("duration"), "source_url": source, "page_url": page})
    return result


@var_clips_bp.get("/var/fixtures")
def fixtures():
    """Return provider IDs so callers select an exact fixture, not a fuzzy match."""
    league = request.args.get("league", "PD")
    day = request.args.get("date", "")
    if league not in ESPN_LEAGUES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return jsonify(error="A supported league and YYYY-MM-DD date are required"), 400
    try:
        date.fromisoformat(day)
    except ValueError:
        return jsonify(error="Invalid date"), 400
    try:
        data = _get(league, "scoreboard", dates=day.replace("-", ""))
        result = []
        for event in data.get("events", []):
            competition = (event.get("competitions") or [{}])[0]
            teams = {c.get("homeAway"): c.get("team", {}).get("displayName") for c in competition.get("competitors", [])}
            result.append({"id": event["id"], "name": event.get("name"), "date": event.get("date"), "home": teams.get("home"), "away": teams.get("away")})
        return jsonify(provider="ESPN", fixtures=result)
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN fixtures"), 502


@var_clips_bp.get("/var/clips")
def clips():
    league = request.args.get("league", "PD")
    event_id = request.args.get("event", "")
    if league not in ESPN_LEAGUES or not re.fullmatch(r"\d{1,12}", event_id):
        return jsonify(error="A supported league and numeric ESPN event ID are required"), 400
    try:
        return jsonify(provider="ESPN", event=event_id, clips=clip_list(league, event_id), analysis_status="not_analyzed")
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN clips"), 502

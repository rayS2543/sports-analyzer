"""Discover candidate footage; availability is not evidence of a VAR incident."""
import re
import unicodedata
from datetime import date, timedelta
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


MAX_DISCOVER_DAYS = 14
HIGHLIGHT_SECONDS = 120  # a longer clip is a recap, not one incident
KINDS = (  # first match wins; the headline is only a hint, never evidence of what the footage shows
    ("highlights", re.compile(r"highlights?|recap|every goal|all goals|full match|preview|press conference|reaction", re.I)),
    ("offside", re.compile(r"offside|ruled out|disallow|chalked off|wiped off|cancelled|overturn|var (?:review|check|decision)|denied by var", re.I)),
    ("foul", re.compile(r"sent off|red card|straight red|dismiss|reckless|dangerous (?:tackle|challenge)", re.I)),
)


def classify(title, duration):
    """'highlights' | 'offside' | 'foul' | 'other' from the headline and length alone."""
    if isinstance(duration, (int, float)) and duration > HIGHLIGHT_SECONDS:
        return "highlights"
    return next((kind for kind, pattern in KINDS if pattern.search(title or "")), "other")


OVERTURNED = re.compile(r"goal overturned by var|ruled out after a var review|var decision: no goal", re.I)
CONFIRMED = re.compile(r"var decision: goal|goal confirmed|goal stands", re.I)
SCORER = re.compile(r"(?:scores|:)\s*([^()]+?)\s*\(")
OFFSIDE_PLAYER = re.compile(r"offside, [^.]+\.\s*([^.]+?) is caught offside", re.I)


def _plain(text):
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def var_incidents(league, event_id, clips_of_event):
    """VAR reviews in ESPN's match commentary, one per minute: goal ruled out or confirmed, and whether an
    offside call came at the same minute (the usual reason). A clip is attached when its headline names the
    player and it is short enough to be one incident; that match is a guess from the headline, not checked."""
    by_minute = {}
    for line in _get(league, "summary", event=event_id).get("commentary") or []:
        text, minute = line.get("text") or "", ((line.get("time") or {}).get("displayValue") or "")
        if not minute:
            continue
        slot = by_minute.setdefault(minute.split("'")[0], {"minute": minute, "overturned": False, "confirmed": False, "offside": False, "player": None})
        if OVERTURNED.search(text):
            slot["overturned"], scorer = True, SCORER.search(text)
            slot["player"] = slot["player"] or (scorer.group(1).strip() if scorer else None)
        elif CONFIRMED.search(text):
            slot["confirmed"] = True
        elif text.startswith("Offside,"):
            slot["offside"], caught = True, OFFSIDE_PLAYER.search(text)
            slot["player"] = slot["player"] or (caught.group(1).strip() if caught else None)
    found = []
    for slot in by_minute.values():
        if not (slot["overturned"] or slot["confirmed"]):
            continue
        surname = _plain(slot["player"]).split()[-1] if slot["player"] else ""
        clip = next((c for c in clips_of_event if surname and surname in _plain(c["title"]) and c["source_url"]
                     and (c["duration_seconds"] or 0) <= HIGHLIGHT_SECONDS and classify(c["title"], c["duration_seconds"]) != "highlights"), None)
        found.append(dict(slot, outcome="goal ruled out" if slot["overturned"] else "goal confirmed", clip=clip))
    return found


@var_clips_bp.get("/var/discover")
def discover():
    """Short clips ESPN lists for a league's finished matches in a date range, tagged by headline so the
    ones likely to show an offside or a foul come first and recaps are left out."""
    league, start, end = request.args.get("league", "PD"), request.args.get("from", ""), request.args.get("to", "")
    kind = request.args.get("kind", "offside")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return jsonify(error="from and to must be valid YYYY-MM-DD dates"), 400
    if league not in ESPN_LEAGUES or kind not in ("offside", "foul", "all") or not 0 <= (last - first).days < MAX_DISCOVER_DAYS:
        return jsonify(error=f"A supported league, kind (offside, foul, all) and a range of at most {MAX_DISCOVER_DAYS} days are required"), 400
    found, reviews, failed = [], [], 0
    try:
        for offset in range((last - first).days + 1):
            day = (first + timedelta(days=offset)).isoformat()
            for event in _get(league, "scoreboard", dates=day.replace("-", "")).get("events", []):
                competition = (event.get("competitions") or [{}])[0]
                if (competition.get("status") or {}).get("type", {}).get("state") != "post":
                    continue
                try:
                    clips_of_event = clip_list(league, event["id"])
                except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
                    failed += 1
                    continue
                for review in var_incidents(league, event["id"], clips_of_event):
                    if review["offside"] and kind in ("offside", "all"):
                        reviews.append(dict(review, event=event["id"], match=event.get("name"), date=day))
                for clip in clips_of_event:
                    tag = classify(clip["title"], clip["duration_seconds"])
                    if clip["source_url"] and (tag == kind or (kind == "all" and tag != "highlights")):
                        found.append(dict(clip, kind=tag, event=event["id"], match=event.get("name"), date=day))
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return jsonify(error="Could not load ESPN fixtures"), 502
    found.sort(key=lambda c: (c["date"], c["duration_seconds"] or 0), reverse=True)
    reviews.sort(key=lambda r: r["date"], reverse=True)
    reviews.sort(key=lambda r: r["clip"] is None)  # stable: clips first, newest first within each group
    return jsonify(provider="ESPN", kind=kind, clips=found, reviews=reviews, events_failed=failed,
                   note="Reviews come from ESPN's match commentary (an offside call and a VAR check at the same minute). A clip is attached "
                        "when its headline names the player: a guess, and whether it shows the incident is not checked until it is analysed.")


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

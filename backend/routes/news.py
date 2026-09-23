import xml.etree.ElementTree as ET

import requests
from flask import Blueprint, jsonify, request

import news_client

news_bp = Blueprint("news", __name__)

RSS_URL = "https://news.google.com/rss/search"


@news_bp.route("/news/teams")
def get_team_news():
    """Combined news for one or more favorited teams -- backs both a
    single team's news section and the "For You" feed, depending on
    how many team names the caller passes."""
    teams = [t for t in request.args.get("teams", "").split(",") if t]
    if not teams:
        return jsonify({"items": [], "error": "teams parameter is required"}), 400
    return jsonify({"items": news_client.for_teams(teams)})


@news_bp.route("/news")
def get_news():
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"items": [], "error": "query parameter is required"}), 400

    try:
        response = requests.get(
            RSS_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=10,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for item in root.findall("./channel/item")[:8]:
            items.append(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "link": (item.findtext("link") or "").strip(),
                    "source": (item.findtext("source") or "").strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                }
            )
    except Exception as e:
        # This is an unofficial, undocumented feed (no SLA) — it must
        # degrade to an empty list rather than ever break the page it's on.
        return jsonify({"items": [], "error": f"Could not load news: {e}"})

    return jsonify({"items": items})

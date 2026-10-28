"""Favorites and search news must degrade, and club feeds must not mix."""

import requests

import news_client
from routes import news as news_routes


class _Rss:
    def __init__(self, content, status_code=200):
        self.content = content if isinstance(content, bytes) else content.encode()
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _item(title, link, published, source=None):
    source_xml = f"<source>{source}</source>" if source is not None else ""
    published_xml = f"<pubDate>{published}</pubDate>" if published is not None else ""
    return (
        f"<item><title>{title}</title><link>{link}</link>{source_xml}{published_xml}</item>"
    )


def _feed(*items):
    return _Rss(f"<?xml version='1.0'?><rss><channel>{''.join(items)}</channel></rss>")


def test_team_news_merges_known_clubs_newest_first(client, monkeypatch):
    calls = []

    def fake_get(url, timeout=10):
        calls.append(url)
        if url.endswith("/barcelona/rss"):
            return _feed(
                _item("  Later Barcelona  ", "https://example.com/barca-new", "Wed, 21 Oct 2026 12:00:00 GMT"),
                _item("Undated Barcelona", "https://example.com/barca-old", None),
            )
        if url.endswith("/realmadrid/rss"):
            return _feed(
                _item("Madrid match", "https://example.com/madrid", "Thu, 22 Oct 2026 09:00:00 GMT"),
            )
        raise AssertionError(url)

    monkeypatch.setattr(news_client.requests, "get", fake_get)

    missing = client.get("/news/teams")
    assert missing.status_code == 400
    assert missing.get_json()["items"] == []

    blank = client.get("/news/teams?teams=,")
    assert blank.status_code == 400

    resp = client.get("/news/teams?teams=Arsenal FC,FC Barcelona,,Real Madrid CF")
    again = client.get("/news/teams?teams=FC Barcelona,Real Madrid CF")

    assert resp.status_code == 200
    assert [item["title"] for item in resp.get_json()["items"]] == [
        "Madrid match",
        "Later Barcelona",
        "Undated Barcelona",
    ]
    assert [item["team_name"] for item in resp.get_json()["items"]] == [
        "Real Madrid CF",
        "FC Barcelona",
        "FC Barcelona",
    ]
    assert resp.get_json()["items"][1]["link"] == "https://example.com/barca-new"
    # One fetch per known slug; an unknown club and a repeat request stay on the cache.
    assert calls == [
        "https://www.theguardian.com/football/barcelona/rss",
        "https://www.theguardian.com/football/realmadrid/rss",
    ]
    assert again.get_json()["items"][0]["title"] == "Madrid match"


def test_a_failed_club_feed_does_not_drop_the_others(client, monkeypatch):
    def fake_get(url, timeout=10):
        if url.endswith("/barcelona/rss"):
            raise requests.ConnectionError("down")
        if url.endswith("/sevilla/rss"):
            return _Rss(b"<rss>", status_code=200)
        if url.endswith("/realmadrid/rss"):
            return _Rss(b"not xml", status_code=500)
        if url.endswith("/valencia/rss"):
            return _feed(_item("Valencia win", "https://example.com/valencia", "Fri, 23 Oct 2026 18:00:00 GMT"))
        raise AssertionError(url)

    monkeypatch.setattr(news_client.requests, "get", fake_get)
    resp = client.get("/news/teams?teams=FC Barcelona,Sevilla FC,Real Madrid CF,Valencia CF")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "items": [
            {
                "title": "Valencia win",
                "link": "https://example.com/valencia",
                "published": "Fri, 23 Oct 2026 18:00:00 GMT",
                "team_name": "Valencia CF",
            }
        ]
    }


def test_news_search_returns_the_first_eight_and_degrades(client, monkeypatch):
    assert client.get("/news").status_code == 400
    assert client.get("/news?query=%20%20").status_code == 400
    assert client.get("/news").get_json()["items"] == []

    seen = {}

    def fake_get(url, params=None, timeout=10):
        seen["url"] = url
        seen["params"] = params
        items = "".join(
            _item(f"  Headline {i} ", f"https://n.example/{i}", "Wed, 21 Oct 2026 12:00:00 GMT", source="Paper")
            for i in range(9)
        )
        return _feed(items)

    monkeypatch.setattr(news_routes.requests, "get", fake_get)
    resp = client.get("/news?query=lamine%20yamal")
    body = resp.get_json()

    assert resp.status_code == 200
    assert seen["url"] == news_routes.RSS_URL
    assert seen["params"]["q"] == "lamine yamal"
    assert seen["params"]["hl"] == "en-US"
    assert [item["title"] for item in body["items"]] == [f"Headline {i}" for i in range(8)]
    assert body["items"][0]["source"] == "Paper"
    assert "error" not in body

    def fail(url, params=None, timeout=10):
        raise requests.ConnectionError("dns")

    monkeypatch.setattr(news_routes.requests, "get", fail)
    failed = client.get("/news?query=lamine%20yamal")
    assert failed.status_code == 200
    assert failed.get_json()["items"] == []
    assert "Could not load news" in failed.get_json()["error"]

    monkeypatch.setattr(news_routes.requests, "get", lambda *args, **kwargs: _Rss(b"<rss>"))
    broken = client.get("/news?query=lamine%20yamal")
    assert broken.status_code == 200
    assert broken.get_json()["items"] == []
    assert "Could not load news" in broken.get_json()["error"]

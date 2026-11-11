import requests

import news_client


def _response(body, ok=True):
    class Response:
        def __init__(self):
            self.ok = ok
            self.content = body.encode()

        def raise_for_status(self):
            if not self.ok:
                raise RuntimeError("bad status")

    return Response()


def test_for_teams_sorts_newest_first_and_skips_unknown_clubs(monkeypatch):
    feeds = {
        "barcelona": """
            <rss><channel>
              <item>
                <title>  Early story  </title>
                <link> https://example.com/early </link>
                <pubDate>Mon, 09 Nov 2026 09:00:00 GMT</pubDate>
              </item>
              <item>
                <title>Undated</title>
                <link>https://example.com/old</link>
                <pubDate>not-a-date</pubDate>
              </item>
            </channel></rss>
        """,
        "realmadrid": """
            <rss><channel>
              <item>
                <title>Late story</title>
                <link>https://example.com/late</link>
                <pubDate>Wed, 11 Nov 2026 09:00:00 GMT</pubDate>
              </item>
            </channel></rss>
        """,
    }
    seen = []

    def fake_get(url, timeout=10):
        slug = url.rstrip("/").split("/")[-2]
        seen.append(slug)
        return _response(feeds[slug])

    monkeypatch.setattr(news_client.requests, "get", fake_get)
    articles = news_client.for_teams(["Arsenal", "FC Barcelona", "Real Madrid CF"])

    assert seen == ["barcelona", "realmadrid"]
    assert [(a["team_name"], a["title"], a["link"]) for a in articles] == [
        ("Real Madrid CF", "Late story", "https://example.com/late"),
        ("FC Barcelona", "Early story", "https://example.com/early"),
        ("FC Barcelona", "Undated", "https://example.com/old"),
    ]


def test_a_broken_feed_does_not_drop_the_other_club(monkeypatch):
    def fake_get(url, timeout=10):
        if "barcelona" in url:
            return _response("<rss><channel><item></not-xml>")
        return _response(
            """<rss><channel><item>
                <title>Madrid story</title><link>https://example.com/m</link>
                <pubDate>Wed, 11 Nov 2026 09:00:00 GMT</pubDate>
            </item></channel></rss>"""
        )

    monkeypatch.setattr(news_client.requests, "get", fake_get)
    articles = news_client.for_teams(["FC Barcelona", "Real Madrid CF"])

    assert [a["title"] for a in articles] == ["Madrid story"]


def test_team_news_requires_a_team_and_search_degrades(client, monkeypatch):
    assert client.get("/news/teams").status_code == 400
    assert client.get("/news").status_code == 400

    monkeypatch.setattr(news_client.requests, "get", lambda *args, **kwargs: _response("", ok=False))
    team_news = client.get("/news/teams?teams=Arsenal,FC%20Barcelona")
    assert team_news.status_code == 200
    assert team_news.get_json()["items"] == []

    def fail(*args, **kwargs):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(requests, "get", fail)
    search = client.get("/news?query=barcelona")
    assert search.status_code == 200
    assert search.get_json()["items"] == []
    assert "Could not load news" in search.get_json()["error"]

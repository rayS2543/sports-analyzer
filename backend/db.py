"""SQLite persistence for cached API responses and match history.

Caching upstream responses lets the app survive football-data.org rate
limits/outages by serving the last good payload, and persisting parsed
matches builds up history beyond the rolling 10-day window the /matches
endpoint queries, which is what the /analytics/form endpoint relies on.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


def get_db_path():
    return os.getenv("SPORTS_ANALYZER_DB_PATH", DEFAULT_DB_PATH)


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                competition TEXT NOT NULL,
                match_date TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_score INTEGER NOT NULL,
                away_score INTEGER NOT NULL,
                winner TEXT NOT NULL,
                home_points INTEGER NOT NULL,
                away_points INTEGER NOT NULL
            )
            """
        )


def reset_db():
    """Drop and recreate all tables. Used by tests to isolate state."""
    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS api_cache")
        conn.execute("DROP TABLE IF EXISTS matches")
    init_db()


def get_cached(cache_key, ttl_seconds):
    """Return the cached payload for cache_key, or None if missing/expired.

    Pass ttl_seconds=None to ignore expiry and fetch whatever is cached,
    however stale (used as a fallback when the upstream API is down).
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT payload, fetched_at FROM api_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    if ttl_seconds is not None and (time.time() - row["fetched_at"]) > ttl_seconds:
        return None
    return json.loads(row["payload"])


def set_cached(cache_key, payload):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO api_cache (cache_key, payload, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                fetched_at = excluded.fetched_at
            """,
            (cache_key, json.dumps(payload), time.time()),
        )


def _parse_score(score):
    home, away = score.split(" - ")
    return int(home), int(away)


def upsert_matches(matches, competition):
    """Persist cleaned match dicts (as returned by /matches) for a competition."""
    with get_connection() as conn:
        for m in matches:
            home_score, away_score = _parse_score(m["score"])
            match_id = f'{competition}:{m["date"]}:{m["home"]}:{m["away"]}'
            conn.execute(
                """
                INSERT INTO matches (
                    id, competition, match_date, home_team, away_team,
                    home_score, away_score, winner, home_points, away_points
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    home_score = excluded.home_score,
                    away_score = excluded.away_score,
                    winner = excluded.winner,
                    home_points = excluded.home_points,
                    away_points = excluded.away_points
                """,
                (
                    match_id,
                    competition,
                    m["date"],
                    m["home"],
                    m["away"],
                    home_score,
                    away_score,
                    m["winner"],
                    m["home_points"],
                    m["away_points"],
                ),
            )


def recent_matches_for_team(team_name, competition, limit=5):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM matches
            WHERE competition = ? AND (home_team = ? OR away_team = ?)
            ORDER BY match_date DESC, id DESC
            LIMIT ?
            """,
            (competition, team_name, team_name, limit),
        ).fetchall()
    return [dict(row) for row in rows]

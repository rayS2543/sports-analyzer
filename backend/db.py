"""SQLite persistence for match history, powering /analytics/form.

Persisting parsed matches builds up history beyond the rolling 10-day
window /matches queries against football-data.org, which is what
/analytics/form relies on to report a team's recent form.
"""

import os
import sqlite3
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
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                league TEXT NOT NULL,
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
        conn.execute("DROP TABLE IF EXISTS matches")
    init_db()


def _parse_score(score):
    home, away = score.split(" - ")
    return int(home), int(away)


def upsert_matches(matches, league):
    """Persist cleaned match dicts (as returned by /matches) for a league."""
    with get_connection() as conn:
        for m in matches:
            home_score, away_score = _parse_score(m["score"])
            match_id = f'{league}:{m["date"]}:{m["home"]}:{m["away"]}'
            conn.execute(
                """
                INSERT INTO matches (
                    id, league, match_date, home_team, away_team,
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
                    league,
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


def recent_matches_for_team(team_name, league, limit=5):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM matches
            WHERE league = ? AND (home_team = ? OR away_team = ?)
            ORDER BY match_date DESC, id DESC
            LIMIT ?
            """,
            (league, team_name, team_name, limit),
        ).fetchall()
    return [dict(row) for row in rows]

"""Persisted match history is what /analytics/form reports."""

import pytest

import db


def _row(date, home, away, score, winner, home_points, away_points):
    return {
        "date": date,
        "home": home,
        "away": away,
        "score": score,
        "winner": winner,
        "home_points": home_points,
        "away_points": away_points,
    }


def test_form_stays_inside_one_league(client):
    db.upsert_matches(
        [
            _row("2024-05-01", "Real Madrid CF", "Getafe CF", "2 - 0", "Real Madrid CF", 3, 0),
            _row("2024-05-03", "Villarreal CF", "Real Madrid CF", "0 - 1", "Real Madrid CF", 0, 3),
        ],
        "PD",
    )
    db.upsert_matches(
        [
            _row("2024-05-02", "Arsenal FC", "Real Madrid CF", "1 - 0", "Arsenal FC", 3, 0),
        ],
        "PL",
    )

    la_liga = client.get("/analytics/form/Real Madrid CF?league=PD").get_json()
    premier = client.get("/analytics/form/Real Madrid CF?league=PL").get_json()

    assert la_liga["form"] == "WW"
    assert la_liga["points"] == 6
    assert la_liga["matches_considered"] == 2
    assert [match["home"] for match in la_liga["matches"]] == ["Villarreal CF", "Real Madrid CF"]
    assert premier["form"] == "L"
    assert premier["points"] == 0
    assert premier["matches"] == [
        {"date": "2024-05-02", "home": "Arsenal FC", "away": "Real Madrid CF", "score": "1 - 0", "winner": "Arsenal FC"}
    ]


def test_a_bad_score_does_not_keep_the_earlier_rows_in_the_batch():
    with pytest.raises(ValueError):
        db.upsert_matches(
            [
                _row("2024-05-01", "Real Madrid CF", "Getafe CF", "2 - 0", "Real Madrid CF", 3, 0),
                _row("2024-05-03", "Villarreal CF", "Real Madrid CF", "1 - x", "Real Madrid CF", 3, 0),
            ],
            "PD",
        )

    assert db.recent_matches_for_team("Real Madrid CF", "PD") == []
    assert db.recent_matches_for_team("Getafe CF", "PD") == []

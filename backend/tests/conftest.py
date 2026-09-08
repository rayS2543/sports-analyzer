import pytest

from backend import db
from backend.app import app as flask_app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Give every test a fresh, empty SQLite DB so cached responses and
    persisted matches from one test never leak into another."""
    monkeypatch.setenv("SPORTS_ANALYZER_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture
def app():
    flask_app.config.update({"TESTING": True})
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()

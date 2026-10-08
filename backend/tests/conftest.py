import cache
import pytest

from backend import db
from backend.app import app as flask_app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Give every test a fresh, empty SQLite DB so persisted matches from
    one test never leak into another."""
    monkeypatch.setenv("SPORTS_ANALYZER_DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def isolated_cache():
    """Give every test a fresh cache so a cached response from one test
    never leaks into another."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def idle_cv_jobs(monkeypatch):
    """Heavy CV jobs share one machine-wide slot; a job left 'running' by one test must not block the next."""
    from routes import var_analysis, var_fouls
    for module, name in ((var_analysis, "_job"), (var_analysis, "_crossview"), (var_fouls, "_job")):
        monkeypatch.setattr(module, name, None)


@pytest.fixture
def app():
    flask_app.config.update({"TESTING": True})
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()

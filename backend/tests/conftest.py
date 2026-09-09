import pytest

from backend.app import app as flask_app
from backend.app import _cache


@pytest.fixture
def app():
    flask_app.config.update({"TESTING": True})
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test should hit the (mocked) upstream API fresh, not a stale cache entry."""
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("FOOTBALL_API_KEY", "test-key")

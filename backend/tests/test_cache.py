"""The in-memory TTL cache sits in front of every upstream client."""

import pytest

import cache


def test_cache_separates_arguments_and_drops_expired_values(monkeypatch):
    clock = {"t": 1_000.0}
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock["t"])
    calls = []

    @cache.cached(ttl_seconds=30)
    def fetch(league, status="FINISHED"):
        calls.append((league, status))
        return (league, status)

    assert fetch("PD") == ("PD", "FINISHED")
    assert fetch("PL") == ("PL", "FINISHED")
    assert fetch("PD", status="TIMED") == ("PD", "TIMED")
    assert fetch("PD") == ("PD", "FINISHED")
    assert calls == [("PD", "FINISHED"), ("PL", "FINISHED"), ("PD", "TIMED")]

    clock["t"] += 30
    assert fetch("PD") == ("PD", "FINISHED")
    assert calls[-1] == ("PD", "FINISHED")
    assert len(calls) == 4


def test_cache_does_not_store_a_failure_and_a_permanent_entry_does_not_expire(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(cache.time, "monotonic", lambda: clock["t"])
    attempts = {"n": 0}

    @cache.cached(ttl_seconds=30)
    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("upstream")
        return "ok"

    with pytest.raises(RuntimeError):
        flaky()
    assert flaky() == "ok"
    assert flaky() == "ok"
    assert attempts["n"] == 2

    permanent = {"n": 0}

    @cache.cached(ttl_seconds=None)
    def lineup():
        permanent["n"] += 1
        return "xi"

    assert lineup() == "xi"
    clock["t"] += 10_000
    assert lineup() == "xi"
    assert permanent["n"] == 1

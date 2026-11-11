import threading
import time

import pytest

import cache


def test_repeat_call_is_served_until_the_ttl_and_a_forever_entry_does_not_expire(monkeypatch):
    calls = []

    @cache.cached(ttl_seconds=10)
    def fetch(n):
        calls.append(n)
        return n * 2

    @cache.cached(ttl_seconds=None)
    def permanent():
        calls.append("perm")
        return "kept"

    monkeypatch.setattr(cache.time, "monotonic", lambda: 1000.0)
    assert fetch(3) == 6
    assert fetch(3) == 6
    assert permanent() == "kept"
    monkeypatch.setattr(cache.time, "monotonic", lambda: 1009.9)
    assert fetch(3) == 6
    monkeypatch.setattr(cache.time, "monotonic", lambda: 1010.0)
    assert fetch(3) == 6
    assert fetch(4) == 8
    monkeypatch.setattr(cache.time, "monotonic", lambda: 10_000.0)
    assert permanent() == "kept"

    assert calls == [3, "perm", 3, 4]


def test_kwargs_order_shares_one_entry():
    calls = []

    @cache.cached(ttl_seconds=30)
    def fetch(**kwargs):
        calls.append(kwargs)
        return kwargs["b"]

    assert fetch(a=1, b=2) == 2
    assert fetch(b=2, a=1) == 2
    assert fetch(a=1, b=3) == 3
    assert calls == [{"a": 1, "b": 2}, {"a": 1, "b": 3}]


def test_a_failed_call_is_not_cached():
    calls = []

    @cache.cached(ttl_seconds=60)
    def fetch():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("upstream")
        return "ok"

    with pytest.raises(RuntimeError):
        fetch()
    assert fetch() == "ok"
    assert fetch() == "ok"
    assert calls == [1, 1]


def test_concurrent_callers_share_one_in_flight_fetch():
    calls = []
    release = threading.Event()
    errors = []

    @cache.cached(ttl_seconds=30)
    def fetch():
        calls.append(1)
        assert release.wait(2)
        return "shared"

    def run():
        try:
            assert fetch() == "shared"
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 2
    while len(calls) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(2)

    assert errors == []
    assert calls == [1]
    assert all(not thread.is_alive() for thread in threads)

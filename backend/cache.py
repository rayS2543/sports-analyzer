import json
import threading
import time
from functools import wraps

_store = {}
_locks = {}  # ponytail: one lock per key, never pruned; fine for a handful of leagues/paths


def clear():
    """Drop every cached entry. Used to isolate tests from each other."""
    _store.clear()
    try:
        import db
        db.cache_clear()
    except Exception:
        pass


def cached(ttl_seconds):
    """Simple in-memory TTL cache decorator, keyed by function + args.

    ttl_seconds=None caches forever (for immutable data, e.g. a finished
    match's lineup). Exists to keep API-Football calls inside its tight
    free-tier daily quota.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__qualname__, args, json.dumps(kwargs, sort_keys=True, default=str))

            def lookup():
                cached_entry = _store.get(key)
                if cached_entry is not None:
                    value, expires_at = cached_entry
                    if expires_at is None or expires_at > time.monotonic():
                        return value, True
                return None, False

            value, hit = lookup()
            if hit:
                return value

            # One in-flight fetch per key: concurrent identical requests (two
            # tabs, a double-mounted effect) wait and share the result instead
            # of each spending the upstream's tight rate limit.
            with _locks.setdefault(key, threading.Lock()):
                value, hit = lookup()
                if hit:
                    return value
                value = fn(*args, **kwargs)
                expires_at = None if ttl_seconds is None else time.monotonic() + ttl_seconds
                _store[key] = (value, expires_at)
                return value

        return wrapper

    return decorator

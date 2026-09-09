import time
from functools import wraps

_store = {}


def cached(ttl_seconds):
    """Simple in-memory TTL cache decorator, keyed by function + args.

    ttl_seconds=None caches forever (for immutable data, e.g. a finished
    match's lineup). Exists to keep API-Football calls inside its tight
    free-tier daily quota.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            cached_entry = _store.get(key)
            if cached_entry is not None:
                value, expires_at = cached_entry
                if expires_at is None or expires_at > now:
                    return value

            value = fn(*args, **kwargs)
            expires_at = None if ttl_seconds is None else now + ttl_seconds
            _store[key] = (value, expires_at)
            return value

        return wrapper

    return decorator

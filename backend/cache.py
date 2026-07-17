"""Small TTL cache used to avoid hammering upstream data providers."""
import time


class TTLCache:
    """Process-local cache for a single value with a time-to-live."""

    def __init__(self, ttl_seconds):
        self.ttl_seconds = ttl_seconds
        self._value = None
        self._stored_at = 0

    def get_fresh(self):
        """Return the cached value if it exists and hasn't expired, else None."""
        if self._value is not None and time.time() - self._stored_at < self.ttl_seconds:
            return self._value
        return None

    def get_stale(self):
        """Return the last cached value regardless of age, for use as a fallback."""
        return self._value

    def set(self, value):
        self._value = value
        self._stored_at = time.time()

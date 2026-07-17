"""Low-level HTTP client for the football-data.org API.

This is the single place that knows how to talk to football-data.org.
Everything above this layer (adapters, engines) should go through here
rather than calling `requests` directly, so adding another data
provider later doesn't ripple through the codebase.
"""
import requests

from backend.config import config


class FootballDataError(Exception):
    """Raised when the upstream API returns an error or unexpected shape."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class FootballDataClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or config.FOOTBALL_API_KEY
        self.base_url = base_url or config.FOOTBALL_API_BASE_URL

    def _headers(self):
        return {"X-Auth-Token": self.api_key}

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self._headers(), params=params)
        try:
            data = response.json()
        except ValueError:
            raise FootballDataError("Non-JSON response from football-data.org", response.status_code)

        if response.status_code != 200:
            raise FootballDataError(data.get("message", "football-data.org request failed"), response.status_code)

        return data

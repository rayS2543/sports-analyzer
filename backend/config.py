"""Centralized configuration loaded from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
    FOOTBALL_API_BASE_URL = os.getenv("FOOTBALL_API_BASE_URL", "https://api.football-data.org/v4")
    MATCHES_CACHE_TTL_SECONDS = int(os.getenv("MATCHES_CACHE_TTL_SECONDS", "180"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "info")


config = Config()

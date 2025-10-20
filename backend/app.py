"""Minimal FastAPI backend for the sports analyzer project."""
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, conint


class PlayerStats(BaseModel):
    """Incoming stats payload for a single player."""

    player: str
    points: conint(ge=0)
    assists: conint(ge=0)
    rebounds: conint(ge=0)


app = FastAPI(title="Sports Analyzer API")


@app.get("/")
async def healthcheck() -> dict[str, str]:
    """Simple healthcheck endpoint."""
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(stats: List[PlayerStats]) -> dict[str, dict[str, int]]:
    """Aggregate player stats into team totals."""
    if not stats:
        raise HTTPException(status_code=400, detail="stats payload cannot be empty")

    totals = {
        "points": sum(player.points for player in stats),
        "assists": sum(player.assists for player in stats),
        "rebounds": sum(player.rebounds for player in stats),
    }
    return {"totals": totals}


@app.post("/mvp")
async def detect_mvp(stats: List[PlayerStats]) -> dict[str, str]:
    """
    Pick a basic MVP based on weighted scoring.

    This is intentionally simple: scoring weight 3, assists 2, rebounds 1.
    """
    if not stats:
        raise HTTPException(status_code=400, detail="stats payload cannot be empty")

    def value(player: PlayerStats) -> int:
        return player.points * 3 + player.assists * 2 + player.rebounds

    top_player = max(stats, key=value)
    return {"mvp": top_player.player}

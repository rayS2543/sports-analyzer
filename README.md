# ⚽ Sports Analyzer

[![CI](https://github.com/rayS2543/sports-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/rayS2543/sports-analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A full-stack multi-league football analytics app: a modular Flask API
aggregating [football-data.org](https://www.football-data.org/) and
[API-Football](https://www.api-football.com/) data, and a React + Tailwind
dashboard for browsing today's fixtures, standings, match predictions, and
player detail across five top European leagues.

## Features

- **Today's games** across La Liga, Premier League, Serie A, Bundesliga, and
  Ligue 1 in one feed.
- **Match tracker & standings** per league, with recent results and the
  current table.
- **Match predictions** for upcoming fixtures, via a simple Elo rating model
  trained on the last 90 days of results.
- **Match detail pages** with real lineups and per-player stats (via
  API-Football), and **player profile pages**.
- **News feed** per query, pulled from Google News RSS.
- **Team form analytics**, built from a locally persisted match history that
  survives beyond football-data.org's rolling 10-day window.
- In-memory response caching to stay within free-tier API rate limits.
- Backend and frontend test suites wired into CI on every push and PR.

## Tech stack

| Layer    | Tools |
|----------|-------|
| Backend  | Python, Flask (blueprints/app factory), Flask-CORS, Requests, pytest |
| Frontend | React 18, React Router, Vite, Tailwind CSS, Vitest, Testing Library |
| CI       | GitHub Actions |

## Project structure

```
sports-analyzer/
├── backend/
│   ├── app.py                  # Flask app factory, registers all blueprints
│   ├── leagues.py               # supported competitions (PD, PL, SA, BL1, FL1)
│   ├── football_client.py       # football-data.org client
│   ├── api_football_client.py   # API-Football client (lineups, player stats)
│   ├── elo.py                   # Elo rating model for predictions
│   ├── cache.py                 # in-memory TTL cache decorator
│   ├── db.py                    # SQLite-persisted match history for analytics
│   ├── routes/
│   │   ├── football.py          # /leagues, /matches, /matches/today, /teams, /standings
│   │   ├── predictions.py       # /predictions
│   │   ├── matches_detail.py    # /matches/detail (lineups + player stats)
│   │   ├── players.py           # /players/<id>
│   │   ├── news.py              # /news
│   │   └── analytics.py         # /analytics/form/<team_name>
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── .env.example
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # routes: Dashboard / match detail / player detail
│   │   └── components/
│   ├── package.json
│   └── vite.config.mjs
└── .github/workflows/ci.yml
```

## Getting started

### Prerequisites

- Python 3.10+
- Node.js 18+ and npm 9+
- A free API key from [football-data.org](https://www.football-data.org/client/register)
- (Optional, for match/player detail pages) an [API-Football](https://www.api-football.com/) key

### Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example backend/.env   # then add your API keys

python -m flask --app backend.app run --debug
```

The API is available at `http://127.0.0.1:5000`.

| Endpoint              | Description                                          |
|------------------------|------------------------------------------------------|
| `GET /health`          | Liveness check                                        |
| `GET /leagues`         | Supported competitions                                 |
| `GET /matches/today`   | Today's fixtures across every supported league         |
| `GET /matches?league=` | Recent matches for a league (defaults to La Liga)      |
| `GET /teams?league=`   | Club directory for a league                            |
| `GET /standings?league=` | Current league table                                 |
| `GET /predictions?league=` | Upcoming fixtures with Elo-based win probabilities |
| `GET /matches/detail`  | Lineups + player stats for a specific fixture           |
| `GET /players/<id>`    | Player profile and season stats                         |
| `GET /news?query=`     | News headlines for a search query                        |
| `GET /analytics/form/<team_name>?league=&limit=` | Recent form (W/D/L), points, and match history for a team, from persisted history |

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://127.0.0.1:5173` and expects the backend
at `http://127.0.0.1:5000`.

## Testing

```bash
# backend
pip install -r backend/requirements-dev.txt
pytest

# frontend
cd frontend
npm test
npm run lint
```

Both suites run automatically in CI (see `.github/workflows/ci.yml`).

## Notes on secrets

`backend/.env` is git-ignored — never commit real API keys. Use
`backend/.env.example` as the template for local setup.

## Notes on persistence

Match history for `/analytics/form` is stored in a SQLite file at
`backend/data.db` by default (git-ignored). Override the path with the
`SPORTS_ANALYZER_DB_PATH` environment variable.

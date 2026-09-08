# ⚽ Sports Analyzer

[![CI](https://github.com/rayS2543/sports-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/rayS2543/sports-analyzer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A full-stack La Liga analytics app: a Flask API that normalizes data from
[football-data.org](https://www.football-data.org/) and a React + Tailwind
frontend for browsing recent results, the live table, and club info.

## Features

- **Recent matches** — last 10 days of finished La Liga fixtures, with
  computed winner and points earned per side.
- **Standings** — the current league table (played, W/D/L, goal difference,
  points).
- **Teams** — club directory with crests.
- In-memory response caching on the backend to stay within the upstream
  API's rate limit.
- Backend and frontend test suites wired into CI on every push and PR.

## Tech stack

| Layer    | Tools |
|----------|-------|
| Backend  | Python, Flask, Flask-CORS, Requests, pytest |
| Frontend | React 18, React Router, Vite, Tailwind CSS, Vitest, Testing Library |
| CI       | GitHub Actions |

## Project structure

```
sports-analyzer/
├── backend/
│   ├── app.py                # Flask app: /matches, /standings, /teams, /health
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── .env.example
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # routes: Matches / Standings / Teams
│   │   ├── api.js            # thin fetch client for the backend
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

### Backend setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example backend/.env   # then add your FOOTBALL_API_KEY

python -m flask --app backend.app run --debug
```

The API is available at `http://127.0.0.1:5000`.

| Endpoint     | Description                                  |
|--------------|-----------------------------------------------|
| `GET /health`| Liveness check                                |
| `GET /matches`  | Finished La Liga matches from the last 10 days |
| `GET /teams`    | Club directory                                |
| `GET /standings`| Current league table                          |

### Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://127.0.0.1:5173` and expects the backend
at `http://127.0.0.1:5000`. Override with `VITE_API_BASE_URL` in a
`frontend/.env.local` if needed.

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

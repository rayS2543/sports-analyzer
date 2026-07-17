# Sports Analyzer

A Flask backend paired with a Vite + React + Tailwind CSS frontend, working toward an AI-first soccer analysis platform (see [Project Vision](#project-vision) below).

## Prerequisites

- Python 3.10 or newer
- Node.js 18+ and npm 9+

## Backend setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Copy the env template and fill in your own key:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Get a free `FOOTBALL_API_KEY` from [football-data.org](https://www.football-data.org/). Never commit `backend/.env` — it's gitignored on purpose.
4. Start the Flask server from the project root (the package uses absolute `backend.*` imports, so it must run as a module, not as a loose script):
   ```bash
   python -m backend.app
   # or, for auto-reload:
   flask --app backend.app run --debug
   ```
5. The API is available at `http://127.0.0.1:5000`.

## Frontend setup

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```
2. Run the dev server:
   ```bash
   npm run dev
   ```
3. The Vite server defaults to `http://127.0.0.1:5173` and expects the backend at `http://127.0.0.1:5000`.

## Project structure

```
sports-analyzer/
├── backend/
│   ├── app.py                    # Flask app factory — wires everything together
│   ├── config.py                 # env-driven configuration
│   ├── cache.py                  # generic TTL cache
│   ├── data_ingestion/           # low-level HTTP client(s) for upstream providers
│   ├── competitions/             # registry of supported/target competitions
│   ├── adapters/                 # per-provider adapters implementing a common interface
│   ├── domain/                   # pure functions shaping raw payloads into API dicts
│   ├── databases/                # repositories over adapters (teams, matches, players)
│   ├── engines/                  # statistics (real), tactical/similarity/prediction/
│   │                              # betting/visualization (stubs — see below)
│   ├── conversation/              # session-scoped chat memory (not wired to a route yet)
│   ├── reports/                   # narrative report generator (stub)
│   ├── api/                       # Flask blueprints (HTTP layer only)
│   ├── requirements.txt
│   ├── .env.example
│   └── .env                       # local only, gitignored
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.jsx
│   │   ├── index.css
│   │   └── components/
│   ├── tailwind.config.js
│   └── vite.config.mjs
└── README.md
```

## Architecture

The backend is organized around the layers called out in the project vision (data ingestion → competition adapters → team/match/player databases → engines → API), so each future capability has an obvious place to land instead of growing inside a single `app.py`.

**Working today**, all backed by football-data.org's free tier and scoped to La Liga:
- `GET /` — health check
- `GET /matches` — recent finished matches (cached 3 minutes)
- `GET /standings` — league table
- `GET /standings/<team_name>` — team profile + last 5 results
- `GET /competitions` — every competition the vision targets, and whether it's wired up yet

**Scaffolded but not implemented** (each raises `NotImplementedError` with a docstring explaining what data source it's blocked on): `engines/tactical.py`, `engines/similarity.py`, `engines/prediction.py`, `engines/betting.py`, `engines/visualization.py`, `databases/players.py`, `reports/generator.py`. `conversation/memory.py` is functional but has no route yet — it's there for the future AI chat layer, since the long-term goal is a natural-language interface over all of this, not a stats dashboard with AI bolted on.

## Project Vision

See [`PROJECT_VISION.md`](./PROJECT_VISION.md) for the full target: an AI that understands soccer well enough to answer any question about players, teams, tactics, transfers, betting value, and predictions in natural language, across domestic leagues, international competitions, and women's football. Everything in this repo should move toward that.

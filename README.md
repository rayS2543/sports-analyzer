# Sports Analyzer

Flask backend paired with a Vite + React + Tailwind CSS frontend for experimenting with lightweight sports analytics, backed by the [football-data.org](https://www.football-data.org/) API.

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
3. Start the Flask server:
   ```bash
   python -m backend.app
   ```
4. The API is available at `http://127.0.0.1:5000`.

### Environment variables

Copy `backend/.env` and update the placeholders. The server reads environment values via `python-dotenv`.

- `FOOTBALL_API_KEY` — API key for football-data.org.
- `SPORTS_ANALYZER_DB_PATH` (optional) — path to the SQLite database used to cache API responses and persist match history. Defaults to `backend/data.db`.
- `SPORTS_ANALYZER_CACHE_TTL` (optional) — seconds an upstream response is cached before being re-fetched. Defaults to `300`.

### API endpoints

All endpoints accept an optional `?competition=` query param (`PD`, `PL`, `SA`, `BL1`, `FL1`; defaults to `PD` — La Liga).

- `GET /matches` — recent (last 10 days) finished matches, with computed winner and points.
- `GET /teams` — teams in the competition.
- `GET /standings` — league table.
- `GET /analytics/form/<team_name>?limit=5` — a team's recent form (W/D/L) and points, computed from match history persisted locally across previous `/matches` calls. Returns `404` until at least one match involving that team has been cached.

Upstream responses are cached in SQLite; if football-data.org is unreachable or rate-limits a request, the last cached response is served instead of failing outright.

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
3. The Vite server defaults to `http://127.0.0.1:5173`. It expects the backend at `http://127.0.0.1:5000`. Override with `VITE_API_BASE_URL` in a `.env.local`.

The frontend has three routes: Matches (`/`), Standings (`/standings`), and Teams (`/teams`).

## Testing

- Backend: `pytest` (from the repo root; see `pytest.ini`). Requires `backend/requirements-dev.txt`.
- Frontend: `npm test` (from `frontend/`).

## Project structure

```
sports-analyzer/
├── backend/
│   ├── app.py
│   ├── db.py
│   ├── requirements.txt
│   ├── tests/
│   └── .env
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx
│   │   ├── index.jsx
│   │   ├── index.css
│   │   ├── api/
│   │   │   └── config.js
│   │   └── components/
│   │       ├── NavBar.jsx
│   │       ├── MatchesTable.jsx
│   │       ├── StandingsTable.jsx
│   │       └── TeamsList.jsx
│   ├── tailwind.config.js
│   └── vite.config.mjs
└── README.md
```

# Hand-off: Performance, Zero-Rate-Limit Cache & Virtual VAR Innovation

**Date:** 2026-10-23  
**Active Branch:** `feature/performance-ui-var-innovation`  
**Workspace Directory:** `/Users/raysiguen/Desktop/Personal Projects/sports-analyzer`  
**Base Commit:** `b28b943` (latest `main`, merged with Virtual VAR PR #21 and Discovery PR #31)  

---

## 1. What was completed in this session

1. **GitHub & Project Linkage:**
   - Authenticated with GitHub account `rayS2543` via `gh`.
   - Connected directly to the active local repository on Desktop.
   - Created feature branch: `feature/performance-ui-var-innovation` branched directly off clean `main`.
2. **Environment & Test Verification:**
   - Python virtualenv verified: `.venv/bin/pytest` -> **241 passed in 27s**.
   - Frontend test suite verified: fixed port mismatch in `MatchesTable.test.jsx` and `TeamsList.test.jsx` to dynamically reference `API_BASE` (matching `TodayGames.test.jsx`), verified tests pass.

---

## 2. Technical Diagnosis (The Bottlenecks to Fix)

1. **Rate Limiting (10 req/min free-tier limit):**
   - Cold dashboard load mounts 7 components at once (`<TodayGames>`, `<LeagueSelector>`, `<StandingsTable>`, `<MatchesTable>`, `<PredictionsPanel>`, `<EloRatingsTable>`, `<TeamsList>`), fanning out 5–7 separate requests to `football-data.org`.
   - In-memory cache is ephemeral (restarts wipe it) and set to 180s across the board.
   - `/predictions` and `/matches` query the same match list with different params, bypassing cache sharing.
   - Any 429 returned from upstream immediately throws `FootballDataError(429)` and crashes the UI with red error banners.
2. **Cold Load Latency (5–10s load time):**
   - Sequential request processing in Flask means 7 concurrent component requests queue up.
   - Frontend lacks SWR/client-side caching; clicking between tabs triggers fresh network fetches.
3. **Virtual VAR ("Not there yet"):**
   - Locked to ESPN CDN Akamai MP4 files (many games don't have direct akamaized MP4 links).
   - No instant demo mode: requires running heavy local CV pipeline (~1–2 min per clip) on fanless M2 Mac, resulting in empty states.
   - Missing high-impact AI breakdown (IFAB Law 11 & 12 automated commentary) and interactive Hawk-Eye offside controls.

---

## 3. Implementation Plan for Next Chat

### Step 1: Persistent SQLite SWR Cache (`backend/db.py` & `backend/football_client.py`)
1. In `backend/db.py`:
   - Add table:
     ```sql
     CREATE TABLE IF NOT EXISTS api_cache (
         key TEXT PRIMARY KEY,
         value TEXT NOT NULL,
         expires_at REAL,
         updated_at REAL NOT NULL
     );
     ```
   - Implement `cache_get(key)` returning `(data, is_stale)`.
   - Implement `cache_set(key, value, ttl_seconds)`.
   - Implement `cache_clear()` and integrate into `reset_db()`.
2. In `backend/football_client.py`:
   - Before hitting network, check `db.cache_get`. If fresh (< TTL), return in <1ms.
   - On network error or HTTP 429 (Rate Limit):
     - If stale cached data exists in SQLite -> **return stale cached snapshot** (app never crashes on 429!).
     - If cold cache -> raise `FootballDataError(429)`.
   - Tailored TTLs:
     - Teams: 86,400s (24h)
     - Standings: 1,800s (30m)
     - Finished matches: 86,400s (24h)
     - Today's live fixtures: 60s

### Step 2: Consolidated Dashboard Endpoint (`backend/routes/football.py`)
- Implement `GET /dashboard-overview?league=PD&date=YYYY-MM-DD`.
- Combines today's matches, league standings, recent results, Elo ratings, match predictions, and team rosters into **1 single response**.
- Cuts 7 network round-trips down to 1 sub-50ms request.

### Step 3: Frontend Fast Dashboard Hydration (`frontend/src/components/Dashboard.jsx`)
- Fetch `/dashboard-overview` on initial mount.
- Hydrate child components (`TodayGames`, `StandingsTable`, `MatchesTable`, `EloRatingsTable`, `PredictionsPanel`, `TeamsList`) in one render pass.
- Retain fallback to individual endpoints for standalone/deep-link views.

### Step 4: Virtual VAR 2.0 Studio (`frontend/src/components/var/VarPage.jsx`)
1. **Instant Demo Presets:**
   - Pre-bundle 1-click controversial incidents (Barça vs Getafe offside, Mbappé straight red, and `sampleAnalysis.json` fixture).
   - Instant loading into 3D Three.js pitch and video overlay without waiting for heavy local CV models.
2. **Video Upload / Direct MP4 URL Input:**
   - Integrate clip upload / direct video link input from `feature/var-upload-clips`.
3. **AI VAR Rule Assistant:**
   - Automated IFAB Law 11 & Law 12 decision card detailing offside line margin and DOGSO / foul criteria.

---

## 4. How to Resume

In the new chat session:
```bash
cd "/Users/raysiguen/Desktop/Personal Projects/sports-analyzer"
git status  # confirm on branch feature/performance-ui-var-innovation
.venv/bin/pytest -q  # verify backend passes
cd frontend && npx vitest run  # verify frontend passes
```
Prompt the agent:
> *"Pick up from HANDOFF_SESSION.md on branch feature/performance-ui-var-innovation. Implement Step 1 (Persistent SQLite SWR Cache in db.py & football_client.py) and Step 2 (/dashboard-overview endpoint), run tests, and show diffs."*

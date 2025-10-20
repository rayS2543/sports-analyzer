# Sports Analyzer

FastAPI backend paired with a Vite + React + Tailwind CSS frontend for experimenting with lightweight sports analytics.

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
3. Start the FastAPI server:
   ```bash
   uvicorn backend.app:app --reload
   ```
4. The API is available at `http://127.0.0.1:8000` with automatic docs at `/docs`.

### Environment variables

Copy `backend/.env` and update the placeholders. The server reads environment values via `python-dotenv`.

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
3. The Vite server defaults to `http://127.0.0.1:5173`. It expects the backend at `http://127.0.0.1:8000`. Override with `VITE_API_BASE_URL` in a `.env.local`.

## Project structure

```
sports-analyzer/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── index.css
│   ├── tailwind.config.js
│   └── vite.config.js
└── README.md
```

Feel free to replace the sample stat payload in the React app with real data and extend the backend with richer analytics or persistence.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5000";

async function get(path) {
  const res = await fetch(`${API_BASE_URL}${path}`);
  return res.json();
}

export function fetchMatches() {
  return get("/matches");
}

export function fetchStandings() {
  return get("/standings");
}

export function fetchTeams() {
  return get("/teams");
}

import { API_BASE } from "./apiBase";

const cacheKey = "sports-analyzer:crests:v1";
let crests = {};
try { crests = JSON.parse(sessionStorage.getItem(cacheKey) || "{}") || {}; } catch { /* Storage is optional. */ }

export function cachedCrest(name) {
  const value = crests[name];
  return typeof value === "string" ? value : undefined;
}

export function rememberCrest(name, crest) {
  if (!name || !crest || crests[name] === crest) return;
  crests[name] = crest;
  try { sessionStorage.setItem(cacheKey, JSON.stringify(crests)); } catch { /* Use the in-memory cache. */ }
}

const leagueTeams = new Map();
export function getTeams(league) {
  if (!leagueTeams.has(league)) {
    const request = fetch(`${API_BASE}/teams?league=${league}`)
      .then((res) => res.json())
      .then((teams) => {
        if (!Array.isArray(teams)) throw new Error(teams.error || "Could not load clubs");
        teams.forEach((team) => {
          rememberCrest(team.name, team.crest);
          rememberCrest(team.shortName, team.crest);
        });
        return teams;
      })
      .catch((error) => { leagueTeams.delete(league); throw error; });
    leagueTeams.set(league, request);
  }
  return leagueTeams.get(league);
}

// Encodes (league, date, home, away) into a URL-safe opaque id for
// /match/:id routes, without needing a shared id from either data
// provider. Purely a frontend routing convenience — MatchDetailPage
// decodes it back and the backend resolves the real fixture by name+date.

export function encodeMatchId({ league, date, home, away }) {
  const raw = `${league}|${date}|${home}|${away}`;
  return btoa(unescape(encodeURIComponent(raw)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function decodeMatchId(id) {
  let base64 = id.replace(/-/g, "+").replace(/_/g, "/");
  while (base64.length % 4) base64 += "=";
  const raw = decodeURIComponent(escape(atob(base64)));
  const [league, date, home, away] = raw.split("|");
  return { league, date, home, away };
}

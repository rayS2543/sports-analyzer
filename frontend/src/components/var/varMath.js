// Pure helpers for the VAR viewer: frame selection, pitch geometry and camera framing.
// Kept free of three.js/DOM so they run (and are tested) in jsdom.

// Shot containing time t. Shots are [start, end); the final shot also owns its end instant.
export function shotAt(shots, t) {
  return shots.find((s, i) => t >= s.start && (t < s.end || (i === shots.length - 1 && t <= s.end))) ?? null;
}

// The analysed frame to show at video time t.
// Nearest sampled frame *within the same shot* (never across a cut, never interpolated).
// A frame further than two sample intervals away is treated as missing rather than shown stale.
// status: "ok" | "uncalibrated" | "no-frame" | "outside" (beyond the analysed window)
export function frameAt(analysis, t) {
  const w = analysis.window;
  if (w && (t < w.start - 1e-6 || t > w.end + 1e-6)) return { status: "outside", frame: null, shot: null };
  // The window is rounded to 0.1 s but shots start/end on real video frames (e.g. 1.001 at 59.94 fps),
  // so an instant inside the window just past the outer shot edges belongs to that edge shot.
  const shots = analysis.shots;
  const inShots = w && shots.length ? Math.min(Math.max(t, shots[0].start), shots[shots.length - 1].end) : t;
  const shot = shotAt(shots, inShots);
  if (!shot) return { status: "no-frame", frame: null, shot: null };
  let best = null;
  for (const f of analysis.frames) {
    if (f.shot !== shot.id) continue;
    if (!best || Math.abs(f.t - t) < Math.abs(best.t - t)) best = f;
  }
  const tolerance = 2 / (analysis.video?.sampled_fps || 4);
  if (!best || Math.abs(best.t - t) > tolerance + 1e-6) return { status: "no-frame", frame: null, shot };
  return { status: best.calibration?.ok ? "ok" : "uncalibrated", frame: best, shot };
}

export const MAX_WINDOW_S = 10;
const tenth = (v) => Math.round(v * 10) / 10;

// Seconds to analyse around moment t: [t - before, t + after], clamped to the clip,
// capped at MAX_WINDOW_S and rounded to 0.1 s (the backend's window key precision).
export function windowAround(t, { before = 3, after = 2, duration = Infinity } = {}) {
  const start = tenth(Math.max(0, t - before));
  let end = tenth(Math.min(duration, t + after));
  if (end - start > MAX_WINDOW_S) end = tenth(start + MAX_WINDOW_S);
  return end > start ? { start, end } : null;
}

// Window from URL params, or null if missing/invalid.
export function parseWindow(start, end) {
  if (start == null || end == null || start === "" || end === "") return null;
  const s = Number(start);
  const e = Number(end);
  if (!Number.isFinite(s) || !Number.isFinite(e) || s < 0 || e <= s || e - s > MAX_WINDOW_S + 1e-9) return null;
  return { start: tenth(s), end: tenth(e) };
}

// Neighbouring sampled frame time (dir = -1 | 1), for frame-accurate stepping.
export function stepFrameTime(frames, t, dir) {
  const eps = 1e-3;
  if (dir > 0) return frames.find((f) => f.t > t + eps)?.t ?? null;
  for (let i = frames.length - 1; i >= 0; i--) if (frames[i].t < t - eps) return frames[i].t;
  return null;
}

// Time of the closest calibrated frame anywhere in the clip (null if none).
export function nearestCalibratedTime(frames, t) {
  let best = null;
  for (const f of frames) {
    if (f.calibration?.ok && (!best || Math.abs(f.t - t) < Math.abs(best.t - t))) best = f;
  }
  return best?.t ?? null;
}

// Pitch metres (origin = top-left corner flag in broadcast view) -> three.js world (centred, y up).
// Broadcast "down the screen" (+y) maps to +z, i.e. towards the main camera.
export function toWorld(x, y, pitch) {
  return [x - pitch.length_m / 2, 0, y - pitch.width_m / 2];
}

const DEG = Math.PI / 180;

// IFAB markings in pitch metres. Arcs are angles in pitch space (0 = +x, 90° = +y).
export function pitchMarkings(pitch) {
  const L = pitch.length_m;
  const W = pitch.width_m;
  const cy = W / 2;
  const arcSpan = Math.acos(5.5 / 9.15); // where the D meets the penalty-area line
  const m = [
    { kind: "rect", x: 0, y: 0, w: L, h: W },
    { kind: "line", x1: L / 2, y1: 0, x2: L / 2, y2: W },
    { kind: "arc", cx: L / 2, cy, r: 9.15, start: 0, end: 2 * Math.PI },
    { kind: "spot", cx: L / 2, cy },
  ];
  for (const [edge, dir] of [[0, 1], [L, -1]]) {
    m.push({ kind: "rect", x: dir > 0 ? 0 : L - 16.5, y: cy - 20.16, w: 16.5, h: 40.32 });
    m.push({ kind: "rect", x: dir > 0 ? 0 : L - 5.5, y: cy - 9.16, w: 5.5, h: 18.32 });
    m.push({ kind: "spot", cx: edge + dir * 11, cy });
    const facing = dir > 0 ? 0 : Math.PI;
    m.push({ kind: "arc", cx: edge + dir * 11, cy, r: 9.15, start: facing - arcSpan, end: facing + arcSpan });
    m.push({ kind: "goal", x: edge, cy, width: 7.32, height: 2.44, depth: dir * -2 });
  }
  for (const [cx, cyy, start] of [[0, 0, 0], [L, 0, 90 * DEG], [L, W, 180 * DEG], [0, W, 270 * DEG]]) {
    m.push({ kind: "arc", cx, cy: cyy, r: 1, start, end: start + 90 * DEG });
  }
  return m;
}

// Camera placement for each preset. aspect = canvas width / height, fov in degrees (vertical).
// focusX is the pitch-metre x the behind-the-line view looks along.
export function cameraPreset(preset, pitch, { aspect = 16 / 9, fov = 40, focusX } = {}) {
  const L = pitch.length_m;
  const W = pitch.width_m;
  const tanHalf = Math.tan((fov * DEG) / 2);
  if (preset === "tactical") {
    const h = Math.max((L / 2 + 6) / (tanHalf * aspect), (W / 2 + 6) / tanHalf);
    return { position: [0, h, 0.01], target: [0, 0, 0] };
  }
  if (preset === "line") {
    const [x] = toWorld(focusX ?? L / 2, 0, pitch);
    return { position: [x, 17, W / 2 + 10], target: [x, 0, -8] };
  }
  // broadcast: elevated main-stand view that fits the full length
  const dist = (L / 2 + 4) / (tanHalf * aspect); // 4 m margin past each goal line
  const elev = 38 * DEG;
  return { position: [0, dist * Math.sin(elev), dist * Math.cos(elev)], target: [0, 0, 0] };
}

// Mix a #rrggbb colour towards white (amount 0..1).
export function lighten(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (255 - v) * amount));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

// Kit colours measured from broadcast video come out shadowed and muddy (Barça's stripes average to
// #5b4e5f), which vanishes on the dark pitch and reads as the grey referee. Keep the measured hue,
// floor saturation and lightness so it stays legible.
export function legible(hex, minS = 0.55, minL = 0.55) {
  const [r, g, b] = [16, 8, 0].map((s) => ((parseInt(hex.slice(1), 16) >> s) & 255) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  const h = d === 0 ? 0 : max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  const l = Math.max((max + min) / 2, minL);
  const s = Math.max(d === 0 ? 0 : d / (1 - Math.abs(max + min - 1)), minS);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h % 2) - 1));
  const rgb = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][Math.floor(h) % 6];
  return `#${rgb.map((v) => Math.round((v + l - c / 2) * 255).toString(16).padStart(2, "0")).join("")}`;
}

export const REFEREE_COLOR = "#8b9590";
export const FALLBACK_TEAM = { A: "#c8102e", B: "#1d3c8f" };

// Body + ground-ring colours for a tracked person. Goalkeepers get a lightened kit of their team.
export function personColors(p, teams) {
  if (p.role === "referee" || !p.team) return { body: REFEREE_COLOR, ring: REFEREE_COLOR };
  const measured = teams?.[p.team]?.color;
  const team = measured ? legible(measured) : FALLBACK_TEAM[p.team];
  return p.role === "goalkeeper" ? { body: lighten(team, 0.6), ring: team } : { body: team, ring: team };
}

export function formatClock(t) {
  if (!Number.isFinite(t)) return "0:00.0";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

// Identity that survives shot cuts when re-identification provides it (global_id), else the per-shot track.
export const personKey = (p) => p.global_id ?? p.track_id;
export const personLabel = (p) => (p.jersey_number != null ? `#${p.jersey_number}` : `ID ${personKey(p)}`);

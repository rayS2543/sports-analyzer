// Procedural three.js assets for the VAR scene: floodlit pitch, stadium bowl and stylised player figures.
// Everything is built from primitives and canvas textures (no model files). Callers dispose via the scene graph.
import * as THREE from "three";
import { pitchMarkings, toWorld } from "./varMath";

export const PALETTE = {
  grassA: "#2a5a36",
  grassB: "#244f30",
  surround: 0x0c1110,
  line: 0xf1f5f2,
  stand: "#121816",
  accent: 0xf2c14e,
  win: 0x4cc38a,
  loss: 0xe5534b,
  fg: 0xe8ece9,
  lamp: 0xfff3dc,
};
const RUNOFF = 6; // grass beyond the lines, metres
const LINE_W = 0.12;

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")];
}

function texture(c, { srgb = true, repeat } = {}) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(...repeat);
  }
  return t;
}

export function flat(geometry, material, x, z, y = 0.01) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(x, y, z);
  return mesh;
}

// Mowing stripes across the full grass area (lines + runoff), with fine noise and a floodlit falloff baked in.
function grassTexture(pitch, anisotropy) {
  const L = pitch.length_m + RUNOFF * 2;
  const W = pitch.width_m + RUNOFF * 2;
  const pxm = 18;
  const [c, g] = canvas(Math.round(L * pxm), Math.round(W * pxm));
  const stripe = pitch.length_m / 20;
  for (let i = -2; i * stripe < L; i++) {
    g.fillStyle = i % 2 ? PALETTE.grassA : PALETTE.grassB;
    g.fillRect(Math.round((RUNOFF + i * stripe) * pxm), 0, Math.ceil(stripe * pxm) + 1, c.height);
  }
  // Soft pool of light in the middle, darker toward the corners.
  const pool = g.createRadialGradient(c.width / 2, c.height / 2, c.height * 0.2, c.width / 2, c.height / 2, c.width * 0.62);
  pool.addColorStop(0, "rgba(255,255,240,0.05)");
  pool.addColorStop(1, "rgba(0,0,0,0.28)");
  g.fillStyle = pool;
  g.fillRect(0, 0, c.width, c.height);
  // Per-pixel grain so close-ups don't look like flat plastic.
  const img = g.getImageData(0, 0, c.width, c.height);
  const d = img.data;
  let seed = 7;
  for (let i = 0; i < d.length; i += 4) {
    seed = (seed * 16807) % 2147483647;
    const n = (seed / 2147483647 - 0.5) * 14;
    d[i] += n * 0.7;
    d[i + 1] += n;
    d[i + 2] += n * 0.6;
  }
  g.putImageData(img, 0, 0);
  const t = texture(c);
  t.anisotropy = anisotropy;
  return t;
}

// Diamond-mesh net cell, tiled.
function netTexture() {
  const [c, g] = canvas(64, 64);
  g.strokeStyle = "rgba(255,255,255,0.9)";
  g.lineWidth = 3;
  g.beginPath();
  g.moveTo(32, 0);
  g.lineTo(64, 32);
  g.lineTo(32, 64);
  g.lineTo(0, 32);
  g.closePath();
  g.stroke();
  return texture(c, { repeat: [1, 1] });
}

// Seated crowd in the dark: tiers lit from the pitch side (bottom of the texture), fading up into shadow.
function crowdTexture() {
  const [c, g] = canvas(1024, 256);
  const rows = 24;
  const rh = 256 / rows;
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let row = 0; row < rows; row++) {
    const lit = 1 - row / rows; // row 0 is the front row (bottom of the texture), nearest the lights
    const y = 256 - (row + 1) * rh;
    g.fillStyle = `hsl(150, 8%, ${3.5 + 5 * lit ** 1.5}%)`;
    g.fillRect(0, y, 1024, rh);
    g.fillStyle = "rgba(255,255,255,0.03)";
    g.fillRect(0, y + rh - 1, 1024, 1);
    for (let x = 0; x < 1024; x += 5) {
      if (rnd() < 0.3) continue;
      g.fillStyle = `hsla(${rnd() * 360}, 7%, ${12 + rnd() * 16 * (0.4 + lit)}%, ${0.2 + 0.35 * lit})`;
      g.fillRect(x + rnd() * 1.5, y + 2 + rnd() * 2, 3, rh * 0.45);
    }
  }
  return texture(c, { repeat: [4, 1] });
}

// Soft radial sprite (floodlight glow, ball shadow).
function radial(stops) {
  const [c, g] = canvas(128, 128);
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  stops.forEach(([o, col]) => grad.addColorStop(o, col));
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return texture(c);
}

// A player's contact shadow plus four faint streaks, one per floodlight bank: the look of a lit stadium, for one quad.
function floodShadowTexture() {
  const [c, g] = canvas(256, 256);
  g.translate(128, 128);
  for (const a of [0.8, 2.35, 3.95, 5.5]) {
    g.save();
    g.rotate(a);
    const lin = g.createLinearGradient(0, 0, 118, 0);
    lin.addColorStop(0, "rgba(0,0,0,0.34)");
    lin.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = lin;
    g.beginPath();
    g.ellipse(56, 0, 62, 11, 0, 0, Math.PI * 2);
    g.fill();
    g.restore();
  }
  const blob = g.createRadialGradient(0, 0, 0, 0, 0, 30);
  blob.addColorStop(0, "rgba(0,0,0,0.75)");
  blob.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = blob;
  g.fillRect(-32, -32, 64, 64);
  return texture(c);
}

function buildLines(pitch, group) {
  const lineMat = new THREE.MeshBasicMaterial({
    color: PALETTE.line,
    transparent: true,
    opacity: 0.88,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: -2,
  });
  const strip = (x1, y1, x2, y2) => {
    const len = Math.hypot(x2 - x1, y2 - y1) + LINE_W;
    const [x, , z] = toWorld((x1 + x2) / 2, (y1 + y2) / 2, pitch);
    const mesh = flat(new THREE.PlaneGeometry(len, LINE_W), lineMat, x, z, 0.012);
    mesh.rotation.z = -Math.atan2(y2 - y1, x2 - x1);
    group.add(mesh);
  };
  const goals = [];
  for (const m of pitchMarkings(pitch)) {
    if (m.kind === "rect") {
      strip(m.x, m.y, m.x + m.w, m.y);
      strip(m.x, m.y + m.h, m.x + m.w, m.y + m.h);
      strip(m.x, m.y, m.x, m.y + m.h);
      strip(m.x + m.w, m.y, m.x + m.w, m.y + m.h);
    } else if (m.kind === "line") {
      strip(m.x1, m.y1, m.x2, m.y2);
    } else if (m.kind === "arc") {
      // RingGeometry lies in XY; after the -90° X rotation, pitch angle φ maps to ring angle -φ.
      const geo = new THREE.RingGeometry(m.r - LINE_W / 2, m.r + LINE_W / 2, 128, 1, -m.end, m.end - m.start);
      const [x, , z] = toWorld(m.cx, m.cy, pitch);
      group.add(flat(geo, lineMat, x, z, 0.012));
    } else if (m.kind === "spot") {
      const [x, , z] = toWorld(m.cx, m.cy, pitch);
      group.add(flat(new THREE.CircleGeometry(0.15, 20), lineMat, x, z, 0.012));
    } else if (m.kind === "goal") {
      goals.push(m);
    }
  }
  return goals;
}

// Posts, crossbar and a box net behind the line. m.depth is signed toward the outside of the pitch.
function buildGoal(m, pitch, group, mats) {
  const [gx] = toWorld(m.x, 0, pitch);
  const hw = m.width / 2;
  const H = m.height;
  const D = m.depth;
  const r = 0.06;
  const post = new THREE.CylinderGeometry(r, r, H + r, 12);
  for (const s of [-1, 1]) {
    const p = new THREE.Mesh(post, mats.post);
    p.position.set(gx, (H + r) / 2, s * hw);
    group.add(p);
  }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(r, r, m.width + 2 * r, 12), mats.post);
  bar.rotation.x = Math.PI / 2;
  bar.position.set(gx, H, 0);
  group.add(bar);
  // Thin frame at the back of the net.
  const back = new THREE.CylinderGeometry(0.025, 0.025, 1, 6);
  const rod = (x1, y1, z1, x2, y2, z2) => {
    const a = new THREE.Vector3(x1, y1, z1);
    const b = new THREE.Vector3(x2, y2, z2);
    const mesh = new THREE.Mesh(back, mats.frame);
    mesh.position.copy(a).add(b).multiplyScalar(0.5);
    mesh.scale.y = a.distanceTo(b);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize());
    group.add(mesh);
  };
  const bx = gx + D;
  rod(bx, 0, -hw, bx, H * 0.8, -hw);
  rod(bx, 0, hw, bx, H * 0.8, hw);
  rod(bx, H * 0.8, -hw, bx, H * 0.8, hw);
  rod(gx, H, -hw, bx, H * 0.8, -hw);
  rod(gx, H, hw, bx, H * 0.8, hw);

  const cell = 0.22;
  const netPlane = (w, h) => {
    const geo = new THREE.PlaneGeometry(w, h);
    const uv = geo.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, (uv.getX(i) * w) / cell, (uv.getY(i) * h) / cell);
    return new THREE.Mesh(geo, mats.net);
  };
  const backNet = netPlane(m.width, H * 0.8);
  backNet.rotation.y = Math.PI / 2;
  backNet.position.set(bx, (H * 0.8) / 2, 0);
  group.add(backNet);
  const slope = Math.hypot(D, H * 0.2);
  const roof = netPlane(slope, m.width);
  // Lay flat (X), then tilt (Z) so it runs from the crossbar down to the back frame.
  roof.rotation.order = "ZXY";
  roof.rotation.set(-Math.PI / 2, 0, Math.atan2(-H * 0.2, D));
  roof.position.set(gx + D / 2, H * 0.9, 0);
  group.add(roof);
  for (const s of [-1, 1]) {
    // Side panels: a trapezoid from the posts (height H) to the back frame (0.8 H).
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.lineTo(D, 0);
    shape.lineTo(D, H * 0.8);
    shape.lineTo(0, H);
    shape.closePath();
    const geo = new THREE.ShapeGeometry(shape);
    const uv = geo.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) / cell, uv.getY(i) / cell);
    const side = new THREE.Mesh(geo, mats.net);
    side.position.set(gx, 0, s * hw);
    group.add(side);
  }
}

// Low perimeter boards, single-sided so a camera outside them (e.g. the matched broadcast camera) sees through.
function buildBoards(pitch, group) {
  const [c, g] = canvas(8, 64);
  const grad = g.createLinearGradient(0, 0, 0, 64);
  grad.addColorStop(0, "#3a4a44");
  grad.addColorStop(0.08, "#1b2522");
  grad.addColorStop(1, "#0e1412");
  g.fillStyle = grad;
  g.fillRect(0, 0, 8, 64);
  const mat = new THREE.MeshBasicMaterial({ map: texture(c) });
  const L = pitch.length_m / 2 + 5;
  const W = pitch.width_m / 2 + 4;
  const h = 0.9;
  for (const [len, x, z, ry] of [
    [L * 2, 0, -W, 0],
    [L * 2, 0, W, Math.PI],
    [W * 2, -L, 0, Math.PI / 2],
    [W * 2, L, 0, -Math.PI / 2],
  ]) {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(len, h), mat);
    mesh.position.set(x, h / 2, z);
    mesh.rotation.y = ry;
    group.add(mesh);
  }
}

// Stadium bowl: four raked stands (inward-facing, single-sided) and floodlight glows along the roof lines.
function buildStadium(pitch, group) {
  const crowd = crowdTexture();
  const standMat = new THREE.MeshBasicMaterial({ map: crowd });
  const glowMat = new THREE.SpriteMaterial({
    map: radial([
      [0, "rgba(255,248,230,1)"],
      [0.15, "rgba(255,240,210,0.55)"],
      [1, "rgba(255,240,210,0)"],
    ]),
    color: PALETTE.lamp,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    transparent: true,
    opacity: 0.8,
  });
  const lampMat = new THREE.MeshBasicMaterial({ color: PALETTE.lamp });
  const lampGeo = new THREE.BoxGeometry(1.6, 0.5, 0.5);
  const roofMat = new THREE.MeshBasicMaterial({ color: 0x080b0a, side: THREE.DoubleSide });
  const hl = pitch.length_m / 2;
  const hw = pitch.width_m / 2;
  const gap = 9;
  const depth = 32;
  const rise = 21;
  // Each stand runs past the corners so the bowl is closed from any angle.
  const long = { len: pitch.length_m + 2 * (gap + depth), span: pitch.length_m, off: hw + gap, lamps: 9 };
  const end = { len: pitch.width_m + 2 * (gap + depth), span: pitch.width_m, off: hl + gap, lamps: 5 };
  const sides = [
    { ...long, ry: 0 }, // far (-z)
    { ...long, ry: Math.PI }, // near (+z)
    { ...end, ry: Math.PI / 2 }, // left
    { ...end, ry: -Math.PI / 2 }, // right
  ];
  for (const s of sides) {
    const side = new THREE.Group();
    side.rotation.y = s.ry;
    const slope = Math.hypot(depth, rise);
    const stand = new THREE.Mesh(new THREE.PlaneGeometry(s.len, slope), standMat);
    // Plane faces +z by default; tilt it back so it faces the pitch and up.
    stand.rotation.x = -Math.atan2(depth, rise);
    stand.position.set(0, 1.2 + rise / 2, -(s.off + depth / 2));
    side.add(stand);
    const roof = new THREE.Mesh(new THREE.PlaneGeometry(s.len, 14), roofMat);
    roof.rotation.x = Math.PI / 2 - 0.12;
    roof.position.set(0, rise + 7, -(s.off + depth - 4));
    side.add(roof);
    for (let i = 0; i < s.lamps; i++) {
      const x = (i / (s.lamps - 1) - 0.5) * s.span;
      const lamp = new THREE.Mesh(lampGeo, lampMat);
      lamp.position.set(x, rise + 6.4, -(s.off + depth - 10));
      side.add(lamp);
      const glow = new THREE.Sprite(glowMat);
      glow.scale.setScalar(9);
      glow.position.copy(lamp.position);
      side.add(glow);
    }
    group.add(side);
  }
}

export function buildPitch(pitch, { anisotropy = 1 } = {}) {
  const group = new THREE.Group();
  const L = pitch.length_m;
  const W = pitch.width_m;
  group.add(flat(new THREE.PlaneGeometry(L + 140, W + 130), new THREE.MeshStandardMaterial({ color: PALETTE.surround, roughness: 1 }), 0, 0, -0.02));
  const grass = new THREE.MeshStandardMaterial({ map: grassTexture(pitch, anisotropy), roughness: 0.92, metalness: 0 });
  group.add(flat(new THREE.PlaneGeometry(L + RUNOFF * 2, W + RUNOFF * 2), grass, 0, 0, 0));

  const goals = buildLines(pitch, group);
  const mats = {
    post: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35, emissive: 0x333333 }),
    frame: new THREE.MeshStandardMaterial({ color: 0x9aa39f, roughness: 0.6 }),
    net: new THREE.MeshBasicMaterial({
      map: netTexture(),
      color: 0xe8ece9,
      transparent: true,
      opacity: 0.55,
      side: THREE.DoubleSide,
      depthWrite: false,
      alphaTest: 0.02,
    }),
  };
  goals.forEach((m) => buildGoal(m, pitch, group, mats));
  buildBoards(pitch, group);
  buildStadium(pitch, group);
  return group;
}

// ---------------------------------------------------------------------------------------------------------------
// Stylised figures. Ground position is measured; the body is assumed geometry (mannequin proportions, no pose).

const MANNEQUIN = 0xcfc6b8;

export function createFigureKit() {
  const torso = new THREE.CylinderGeometry(0.25, 0.19, 0.56, 7);
  torso.scale(1, 1, 0.66);
  const marker = new THREE.ConeGeometry(0.2, 0.34, 4);
  marker.rotateX(Math.PI);
  const geo = {
    leg: new THREE.CapsuleGeometry(0.085, 0.6, 2, 6),
    shorts: new THREE.CylinderGeometry(0.2, 0.22, 0.26, 7),
    torso,
    arm: new THREE.CapsuleGeometry(0.062, 0.46, 2, 6),
    head: new THREE.IcosahedronGeometry(0.125, 1),
    hit: new THREE.CylinderGeometry(0.65, 0.65, 2.2, 8),
    ring: new THREE.RingGeometry(0.5, 0.59, 48),
    halo: new THREE.RingGeometry(0.74, 0.9, 48),
    shadow: new THREE.PlaneGeometry(3.2, 3.2),
    marker,
  };
  const mats = new Map();
  const mat = (key, make) => {
    if (!mats.has(key)) mats.set(key, make());
    return mats.get(key);
  };
  const shadowMat = new THREE.MeshBasicMaterial({ map: floodShadowTexture(), transparent: true, depthWrite: false });
  const hitMat = new THREE.MeshBasicMaterial({ visible: false });

  // Colours for one person: kit parts are shared per (colour, role, faded) key.
  function kit(colors, role, faded) {
    const key = `${colors.body}|${colors.ring}|${role}|${faded}`;
    return mat(key, () => {
      const std = (color) =>
        new THREE.MeshStandardMaterial({ color, roughness: 0.7, flatShading: true, transparent: faded, opacity: faded ? 0.45 : 1 });
      const shirt = new THREE.Color(colors.body);
      const dark = role === "referee" ? new THREE.Color(0x151816) : shirt.clone().multiplyScalar(0.32);
      return {
        shirt: std(shirt),
        shorts: std(dark),
        legs: std(role === "referee" ? 0x151816 : shirt.clone().multiplyScalar(0.78)),
        skin: std(MANNEQUIN),
        ring: new THREE.MeshBasicMaterial({ color: colors.ring, transparent: true, opacity: faded ? 0.45 : 0.85, depthWrite: false }),
      };
    });
  }
  const haloMat = (color) => mat(`halo${color}`, () => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, depthWrite: false }));
  const markerMat = mat("marker", () => new THREE.MeshBasicMaterial({ color: PALETTE.accent }));

  function makeFigure() {
    const root = new THREE.Group();
    const shadow = flat(geo.shadow, shadowMat, 0, 0, 0.015);
    const ring = flat(geo.ring, hitMat, 0, 0, 0.02); // real materials are assigned by dress()
    const halo = flat(geo.halo, hitMat, 0, 0, 0.025);
    const hit = new THREE.Mesh(geo.hit, hitMat);
    hit.position.y = 1.1;
    const pin = new THREE.Mesh(geo.marker, markerMat);
    pin.position.y = 2.45;
    const yaw = new THREE.Group();
    const lean = new THREE.Group();
    yaw.add(lean);
    const part = (g, x, y, z = 0) => {
      const m = new THREE.Mesh(g);
      m.position.set(x, y, z);
      lean.add(m);
      return m;
    };
    const legs = [part(geo.leg, -0.1, 0.43), part(geo.leg, 0.1, 0.43)];
    const shorts = part(geo.shorts, 0, 0.86);
    const torsoM = part(geo.torso, 0, 1.27);
    const arms = [part(geo.arm, -0.3, 1.2, 0.03), part(geo.arm, 0.3, 1.2, 0.03)];
    arms[0].rotation.set(-0.18, 0, -0.14);
    arms[1].rotation.set(-0.18, 0, 0.14);
    const head = part(geo.head, 0, 1.7, 0.02);
    root.add(shadow, ring, halo, hit, pin, yaw);
    root.userData = { hit, ring, halo, pin, yaw, lean, parts: { legs, shorts, torso: torsoM, arms, head }, kitKey: null };
    return root;
  }

  // Apply kit colours and the selection state to a figure (cheap; only swaps material references).
  function dress(fig, colors, role, faded, haloColor) {
    const u = fig.userData;
    const k = kit(colors, role, faded);
    if (u.kit !== k) {
      u.kit = k;
      u.parts.legs.forEach((m) => (m.material = k.legs));
      u.parts.arms.forEach((m) => (m.material = k.shirt));
      u.parts.torso.material = k.shirt;
      u.parts.shorts.material = k.shorts;
      u.parts.head.material = k.skin;
      u.ring.material = k.ring;
    }
    u.halo.visible = haloColor != null;
    if (haloColor != null) u.halo.material = haloMat(haloColor);
  }

  function dispose() {
    Object.values(geo).forEach((g) => g.dispose());
    mats.forEach((v) => (v.isMaterial ? [v] : Object.values(v)).forEach((m) => m.dispose()));
    shadowMat.map.dispose();
    shadowMat.dispose();
    hitMat.dispose();
  }

  return { makeFigure, dress, dispose };
}

// Ball, its ground shadow, a drop line and a ± height-uncertainty sleeve, and a short fading trail.
export const TRAIL_POINTS = 48;
export function createBall() {
  const group = new THREE.Group();
  const ball = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.2, 1),
    new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0x555555, roughness: 0.35, flatShading: true })
  );
  const shadow = flat(
    new THREE.PlaneGeometry(0.9, 0.9),
    new THREE.MeshBasicMaterial({
      map: radial([
        [0, "rgba(0,0,0,0.6)"],
        [1, "rgba(0,0,0,0)"],
      ]),
      transparent: true,
      depthWrite: false,
    }),
    0,
    0,
    0.018
  );
  const drop = new THREE.Mesh(
    new THREE.CylinderGeometry(0.018, 0.018, 1, 6),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.55, depthWrite: false })
  );
  const sleeve = new THREE.Mesh(
    new THREE.CylinderGeometry(0.11, 0.11, 1, 10, 1, true),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide })
  );
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3), 3));
  trailGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3), 3));
  const trail = new THREE.Line(
    trailGeo,
    new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false })
  );
  trail.frustumCulled = false;
  group.add(shadow, drop, sleeve, ball, trail);
  return { group, ball, shadow, drop, sleeve, trail };
}

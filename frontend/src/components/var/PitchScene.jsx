import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { cameraPreset, personColors, toWorld } from "./varMath";
import { cameraFromHomography, fitFov } from "./broadcastCamera";
import { bracket, displayFrame } from "./displayFrame";
import { PALETTE as C, TRAIL_POINTS, buildPitch, createBall, createFigureKit, flat } from "./sceneAssets";

const FOV = 40;
const BG = 0x0b0e0d;
const BALL_R = 0.2;
const TRAIL_S = 1.6; // seconds of ball path drawn behind the ball
const UP = new THREE.Vector3(0, 1, 0);

function disposeTree(root) {
  root.traverse((o) => {
    o.geometry?.dispose();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    mats.forEach((mat) => {
      Object.values(mat).forEach((v) => v?.isTexture && v.dispose());
      mat.dispose();
    });
  });
}

function clearGroup(group) {
  while (group.children.length) group.remove(group.children[0]);
}

const easeOut = (k) => 1 - Math.pow(1 - k, 3);
// Shortest signed angle from a to b.
const angleTo = (a, b) => Math.atan2(Math.sin(b - a), Math.cos(b - a));

/**
 * Orbitable 3D reconstruction of the analysed frame at `time`.
 * Ground positions are measured; bodies are ASSUMED geometry (stylised mannequins, no pose).
 * preset "match" matches the broadcast camera recovered from `homography` (falls back to "broadcast").
 */
export default function PitchScene({
  pitch,
  teams,
  frame,
  preset,
  focusX,
  overlay,
  selectedTrackId,
  highlightTrackId,
  onSelectPlayer,
  reducedMotion,
  homography = null,
  imageSize = null,
  shotFrames = null,
  time = null,
}) {
  const hostRef = useRef(null);
  const ctxRef = useRef(null);
  const selectRef = useRef(onSelectPlayer);
  selectRef.current = onSelectPlayer;
  const [moved, setMoved] = useState(false);

  // Mount: renderer, camera, controls, static stadium. Everything is torn down on unmount.
  useEffect(() => {
    const host = hostRef.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(BG, 0); // transparent: the host div paints the night-sky backdrop
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NeutralToneMapping;
    host.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.touchAction = "none";

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(BG, 150, 340);
    scene.add(new THREE.HemisphereLight(0xdde8f0, 0x0b0e0d, 1.3));
    const key = new THREE.DirectionalLight(0xfff2de, 2.1);
    key.position.set(-40, 70, 55);
    const fill = new THREE.DirectionalLight(0xcfe0ff, 0.7);
    fill.position.set(50, 40, -45);
    scene.add(key, fill);
    scene.add(buildPitch(pitch, { anisotropy: renderer.capabilities.getMaxAnisotropy() }));

    const people = new THREE.Group();
    const overlayGroup = new THREE.Group();
    const ball = createBall();
    scene.add(people, overlayGroup, ball.group);

    const camera = new THREE.PerspectiveCamera(FOV, 16 / 9, 0.5, 700);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.maxPolarAngle = Math.PI / 2 - 0.04;
    controls.minDistance = 3;
    controls.maxDistance = 240;
    controls.screenSpacePanning = false;

    const kit = createFigureKit();
    const V = () => new THREE.Vector3();
    const ctx = {
      renderer,
      scene,
      camera,
      controls,
      people,
      overlayGroup,
      ball,
      kit,
      pitch,
      figures: new Map(), // `${shot}:${track_id}` -> figure
      free: [],
      hits: [], // every figure's (invisible) click proxy
      stamp: 0,
      size: [16, 9],
      reduced: false,
      turnK: 1,
      input: null,
      follow: false, // camera glued to the preset's goal pose (until the user orbits)
      placed: false,
      anim: null,
      goal: { pos: V(), quat: new THREE.Quaternion(), target: V(), fov: FOV, live: false, kind: null },
      from: { pos: V(), quat: new THREE.Quaternion(), target: V(), fov: FOV },
      tmp: { m: new THREE.Matrix4(), a: V(), b: V(), c: V(), pos: V(), quat: new THREE.Quaternion(), target: V() },
      recovered: new WeakMap(), // homography array -> recovered camera (per imageSize)
    };
    ctxRef.current = ctx;

    ctx.home = (animate) => {
      ctx.follow = true;
      ctx.anim = null;
      if (animate && ctx.placed) {
        ctx.from.pos.copy(camera.position);
        ctx.from.quat.copy(camera.quaternion);
        ctx.from.target.copy(controls.target);
        ctx.from.fov = camera.fov;
        ctx.anim = { t0: performance.now(), ms: 750 };
      }
      ctx.placed = true;
    };

    const resize = () => {
      const w = host.clientWidth || 1;
      const h = host.clientHeight || 1;
      ctx.size = [w, h];
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      updateGoal(ctx);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    // The user takes the camera: stop following the preset. A click without a drag doesn't count.
    let userActive = false;
    const onStart = () => (userActive = true);
    const onEnd = () => (userActive = false);
    const onChange = () => {
      if (!userActive || !ctx.follow) return;
      ctx.follow = false;
      ctx.anim = null;
      setMoved(true);
    };
    controls.addEventListener("start", onStart);
    controls.addEventListener("end", onEnd);
    controls.addEventListener("change", onChange);

    // Raycast picking: a click (not a drag) on a figure selects that track.
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let down = null;
    const pick = (e) => {
      const r = renderer.domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      // Raycasting ignores visibility, so skip pooled figures that are currently hidden.
      const hit = ray.intersectObjects(ctx.hits, false).find((h) => h.object.parent.visible);
      return hit?.object.userData ?? null;
    };
    const onDown = (e) => (down = [e.clientX, e.clientY]);
    const onUp = (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const hit = pick(e);
      if (hit?.selectable) selectRef.current?.(hit.trackId);
    };
    const onMove = (e) => {
      if (e.buttons) return;
      renderer.domElement.style.cursor = pick(e)?.selectable ? "pointer" : "grab";
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointermove", onMove);

    let last = null;
    const turnFigure = (fig) => {
      const u = fig.userData;
      if (ctx.reduced) {
        u.yaw.rotation.y = u.yawTarget;
        u.lean.rotation.x = u.leanTarget;
        return;
      }
      u.yaw.rotation.y += angleTo(u.yaw.rotation.y, u.yawTarget) * ctx.turnK;
      u.lean.rotation.x += (u.leanTarget - u.lean.rotation.x) * ctx.turnK;
    };
    renderer.setAnimationLoop((now) => {
      const dt = last == null ? 0 : Math.min(0.1, (now - last) / 1000);
      last = now;
      if (ctx.follow) {
        const g = ctx.goal;
        const a = ctx.anim;
        if (a) {
          const e = easeOut(Math.min(1, (now - a.t0) / a.ms));
          camera.position.lerpVectors(ctx.from.pos, g.pos, e);
          camera.quaternion.slerpQuaternions(ctx.from.quat, g.quat, e);
          controls.target.lerpVectors(ctx.from.target, g.target, e);
          camera.fov = ctx.from.fov + (g.fov - ctx.from.fov) * e;
          if (e >= 1) ctx.anim = null;
        } else {
          camera.position.copy(g.pos);
          camera.quaternion.copy(g.quat);
          controls.target.copy(g.target);
          camera.fov = g.fov;
        }
        camera.updateProjectionMatrix();
        // Static presets hand back to the orbit controls once reached; "match" keeps tracking the broadcast.
        if (!ctx.anim && !g.live) ctx.follow = false;
      } else {
        controls.update();
      }
      ctx.turnK = 1 - Math.exp(-dt * 9);
      ctx.figures.forEach(turnFigure);
      renderer.render(scene, camera);
    });

    return () => {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      controls.removeEventListener("start", onStart);
      controls.removeEventListener("end", onEnd);
      controls.removeEventListener("change", onChange);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMove);
      controls.dispose();
      clearGroup(overlayGroup); // overlay geometries are disposed by the overlay effect's cleanup
      disposeTree(scene);
      kit.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      ctxRef.current = null;
    };
  }, [pitch]);

  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    ctx.reduced = !!reducedMotion;
    ctx.controls.enableDamping = !reducedMotion;
  }, [reducedMotion]);

  // Inputs to the camera goal. For "match" this changes every frame as the broadcast camera pans.
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    ctx.input = { preset, focusX, homography, imageSize, frame, shotFrames, time };
    updateGoal(ctx);
  }, [preset, focusX, homography, imageSize, frame, shotFrames, time, pitch]);

  // Preset changes fly the camera to the new goal (instantly when the viewer prefers reduced motion).
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    ctx.home(!ctx.reduced);
    setMoved(false);
  }, [preset, focusX, pitch]);

  // People and ball at `time`, smoothed between sampled frames where that's honest (see displayFrame).
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    syncPeople(ctx, { frame, shotFrames, time, teams, selectedTrackId, highlightTrackId });
  }, [frame, shotFrames, time, teams, pitch, selectedTrackId, highlightTrackId]);

  // Offside overlay: line + translucent sheet at offside_line_x, ± uncertainty band, attacker line.
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx || !overlay) return;
    const { overlayGroup } = ctx;
    const W = pitch.width_m + 4;
    const [lx] = toWorld(overlay.lineX, 0, pitch);
    const basic = (color, opacity) =>
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4 });
    if (overlay.uncertainty > 0) {
      overlayGroup.add(flat(new THREE.PlaneGeometry(overlay.uncertainty * 2, W), basic(C.accent, 0.2), lx, 0, 0.03));
    }
    overlayGroup.add(flat(new THREE.PlaneGeometry(0.16, W), basic(C.accent, 1), lx, 0, 0.035));
    const sheet = new THREE.Mesh(new THREE.PlaneGeometry(W, 2.2), basic(C.accent, 0.13));
    sheet.rotation.y = Math.PI / 2;
    sheet.position.set(lx, 1.1, 0);
    overlayGroup.add(sheet);
    if (overlay.attackerX != null) {
      const color = overlay.verdict === "offside" ? C.loss : overlay.verdict === "onside" ? C.win : C.fg;
      const [ax] = toWorld(overlay.attackerX, 0, pitch);
      overlayGroup.add(flat(new THREE.PlaneGeometry(0.1, W), basic(color, 0.95), ax, 0, 0.04));
    }
    return () => {
      overlayGroup.children.forEach((o) => {
        o.geometry.dispose();
        o.material.dispose();
      });
      clearGroup(overlayGroup);
    };
  }, [overlay, pitch]);

  return (
    <div className="absolute inset-0">
      <div
        ref={hostRef}
        role="img"
        aria-label="3D reconstruction. Player positions are estimated from the broadcast video; bodies are assumed, stylised figures."
        className="absolute inset-0"
        style={{ background: "radial-gradient(130% 80% at 50% 0%, rgb(var(--raised)) 0%, rgb(var(--canvas)) 62%)" }}
      />
      {moved && (
        <button
          type="button"
          onClick={() => {
            ctxRef.current?.home(!reducedMotion);
            setMoved(false);
          }}
          className="pressable absolute top-2 right-2 rounded-md bg-canvas/85 backdrop-blur-sm border border-line px-2.5 h-7 text-xs text-muted hover:text-fg"
        >
          Reset camera
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------

function recover(ctx, H, imageSize) {
  if (!H || !imageSize) return null;
  const hit = ctx.recovered.get(H);
  if (hit && hit.w === imageSize[0] && hit.h === imageSize[1]) return hit.cam;
  const cam = cameraFromHomography(H, imageSize, ctx.pitch);
  ctx.recovered.set(H, { w: imageSize[0], h: imageSize[1], cam });
  return cam;
}

// Recovered camera -> position, orientation (keeping the broadcast's roll) and orbit pivot.
function poseOf(ctx, cam, pos, quat, target) {
  const { m, a, b, c } = ctx.tmp;
  m.makeBasis(a.fromArray(cam.right), b.fromArray(cam.up), c.fromArray(cam.forward).negate());
  quat.setFromRotationMatrix(m);
  pos.fromArray(cam.position);
  target.fromArray(cam.target);
}

// Match the broadcast: the current frame's camera or, between two sampled frames, a blend of both.
function setMatchGoal(ctx, inp, aspect) {
  const g = ctx.goal;
  const imageAspect = inp.imageSize ? inp.imageSize[0] / inp.imageSize[1] : 16 / 9;
  const br = bracket(inp.frame, inp.shotFrames, inp.time);
  const ca = br && recover(ctx, br.a.calibration?.homography, inp.imageSize);
  const cb = br && recover(ctx, br.b.calibration?.homography, inp.imageSize);
  if (ca && cb) {
    const t = ctx.tmp;
    poseOf(ctx, ca, g.pos, g.quat, g.target);
    poseOf(ctx, cb, t.pos, t.quat, t.target);
    g.pos.lerp(t.pos, br.k);
    g.quat.slerp(t.quat, br.k);
    g.target.lerp(t.target, br.k);
    g.fov = fitFov(ca.fov + (cb.fov - ca.fov) * br.k, imageAspect, aspect);
    return true;
  }
  const cam = recover(ctx, inp.homography, inp.imageSize);
  if (!cam) return false;
  poseOf(ctx, cam, g.pos, g.quat, g.target);
  g.fov = fitFov(cam.fov, imageAspect, aspect);
  return true;
}

function updateGoal(ctx) {
  const inp = ctx.input;
  if (!inp) return;
  const g = ctx.goal;
  const aspect = ctx.size[0] / ctx.size[1];
  let kind = inp.preset;
  if (kind === "match" && !setMatchGoal(ctx, inp, aspect)) kind = "broadcast"; // no usable homography
  if (kind !== "match") {
    const { position, target } = cameraPreset(kind, ctx.pitch, { aspect, fov: FOV, focusX: inp.focusX });
    g.pos.fromArray(position);
    g.target.fromArray(target);
    g.fov = FOV;
    ctx.tmp.m.lookAt(g.pos, g.target, UP);
    g.quat.setFromRotationMatrix(ctx.tmp.m);
  }
  g.live = inp.preset === "match";
  // Losing (or regaining) the broadcast calibration mid-follow: glide rather than jump.
  if (g.kind && g.kind !== kind && ctx.follow && !ctx.anim) ctx.home(!ctx.reduced);
  g.kind = kind;
}

function syncPeople(ctx, { frame, shotFrames, time, teams, selectedTrackId, highlightTrackId }) {
  const { figures, free, kit, people, pitch, ball } = ctx;
  const df = displayFrame(frame, shotFrames, time);
  const stamp = ++ctx.stamp;
  const b = df?.ball && df.ball.x != null && df.ball.y != null ? df.ball : null;
  const [bx, , bz] = b ? toWorld(b.x, b.y, pitch) : [0, 0, 0];

  for (const p of df?.players ?? []) {
    if (p.x == null || p.y == null) continue;
    const key = `${df.shot}:${p.track_id}`;
    let fig = figures.get(key);
    const fresh = !fig;
    if (fresh) {
      fig = free.pop();
      if (!fig) {
        fig = kit.makeFigure();
        people.add(fig);
        ctx.hits.push(fig.userData.hit);
      }
      fig.visible = true;
      figures.set(key, fig);
    }
    const u = fig.userData;
    const [x, , z] = toWorld(p.x, p.y, pitch);

    // Facing and lean come from ground velocity: measured vx/vy when present, else the displayed motion.
    let speed = null;
    let heading = null;
    if (Number.isFinite(p.vx) && Number.isFinite(p.vy)) {
      speed = Math.hypot(p.vx, p.vy);
      if (speed > 0.5) heading = Math.atan2(p.vx, p.vy);
    } else if (!fresh && Number.isFinite(time) && Number.isFinite(u.lastTime)) {
      const dtv = time - u.lastTime;
      const d = Math.hypot(x - u.x, z - u.z);
      if (Math.abs(dtv) > 1e-3 && Math.abs(dtv) < 0.6 && d > 0.005) {
        speed = d / Math.abs(dtv);
        const s = Math.sign(dtv);
        if (speed > 0.5) heading = Math.atan2((x - u.x) * s, (z - u.z) * s);
      }
    }
    if (fresh) {
      // Unknown facing: assume the player is watching the ball.
      u.yawTarget = heading ?? (b ? Math.atan2(bx - x, bz - z) : 0);
      u.leanTarget = 0;
    } else if (heading != null) {
      u.yawTarget = heading;
    }
    if (speed != null) u.leanTarget = Math.min(speed / 8, 1) * 0.2; // up to ~11° at a sprint
    if (fresh) {
      u.yaw.rotation.y = u.yawTarget;
      u.lean.rotation.x = u.leanTarget;
    }
    fig.position.set(x, 0, z);
    u.x = x;
    u.z = z;
    u.lastTime = time;
    u.stamp = stamp;

    const selected = p.track_id === selectedTrackId;
    const halo = selected ? C.accent : p.track_id === highlightTrackId ? C.fg : null;
    kit.dress(fig, personColors(p, teams), p.role, (p.confidence ?? 1) < 0.6, halo);
    u.pin.visible = selected;
    u.hit.userData = { trackId: p.track_id, selectable: p.role !== "referee" };
  }
  figures.forEach((fig, key) => {
    if (fig.userData.stamp === stamp) return;
    fig.visible = false;
    figures.delete(key);
    free.push(fig);
  });

  syncBall(ball, b, bx, bz, df, shotFrames, time, pitch);
}

function syncBall(ball, b, x, z, df, shotFrames, time, pitch) {
  ball.group.visible = !!b;
  if (!b) return;
  const h = Math.max(0, Number.isFinite(b.z) ? b.z : 0);
  const airborne = b.airborne ?? h > 0.05;
  ball.ball.position.set(x, BALL_R + h, z);
  ball.shadow.position.set(x, 0.018, z);
  ball.shadow.scale.setScalar(1 + h * 0.12);
  ball.shadow.material.opacity = 1 / (1 + h * 0.35);
  ball.drop.visible = airborne && h > 0.05;
  if (ball.drop.visible) {
    ball.drop.position.set(x, h / 2, z);
    ball.drop.scale.y = h;
  }
  const unc = b.height_uncertainty_m;
  ball.sleeve.visible = airborne && Number.isFinite(unc) && unc > 0.02;
  if (ball.sleeve.visible) {
    const lo = Math.max(0, h - unc);
    const hi = h + unc;
    ball.sleeve.position.set(x, BALL_R + (lo + hi) / 2, z);
    ball.sleeve.scale.y = hi - lo;
  }

  // Trail: the ball's sampled path in this shot over the last TRAIL_S seconds, broken at gaps, ending at the ball.
  const pos = ball.trail.geometry.attributes.position;
  const col = ball.trail.geometry.attributes.color;
  let n = 0;
  const put = (px, py, pz, age) => {
    const k = Math.max(0, 1 - age / TRAIL_S) ** 1.6 * 0.85;
    pos.setXYZ(n, px, py, pz);
    col.setXYZ(n, k, k * 0.97, k * 0.9);
    n++;
  };
  put(x, BALL_R + h, z, 0);
  if (shotFrames && Number.isFinite(time)) {
    let interval = Infinity;
    for (let i = 1; i < shotFrames.length; i++) interval = Math.min(interval, shotFrames[i].t - shotFrames[i - 1].t || Infinity);
    let prevT = time;
    for (let i = shotFrames.length - 1; i >= 0 && n < TRAIL_POINTS; i--) {
      const f = shotFrames[i];
      if (f.shot !== df.shot || f.t > time + 1e-6) continue;
      if (time - f.t > TRAIL_S || prevT - f.t > 1.5 * interval + 1e-6) break;
      const fb = f.ball;
      if (!fb || fb.x == null || fb.y == null) break;
      const [fx, , fz] = toWorld(fb.x, fb.y, pitch);
      put(fx, BALL_R + Math.max(0, fb.z ?? 0), fz, time - f.t);
      prevT = f.t;
    }
  }
  ball.trail.visible = n > 1;
  ball.trail.geometry.setDrawRange(0, n);
  pos.needsUpdate = true;
  col.needsUpdate = true;
}

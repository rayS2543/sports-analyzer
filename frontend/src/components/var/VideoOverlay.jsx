import React, { useEffect, useRef, useState } from "react";
import { clipSegmentToRect, containRect, frontSign, groundCircle, offsideShapes, projectPath, toScreen } from "./projection";

// Broadcast graphics palette (matches the app tokens).
const AMBER = "242,193,78";
const VERDICT_RGB = { offside: "229,83,75", onside: "76,195,138", inconclusive: "232,236,233" };
const FONT = '600 11px "Geist Variable", ui-sans-serif, system-ui, sans-serif';

function path(ctx, pts, closed) {
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
  if (closed) ctx.closePath();
}

// Glow pass, then a crisp core on top: reads like a TV graphic without going soft.
function glowLine(ctx, pts, rgb, width) {
  if (pts.length < 2) return;
  ctx.save();
  ctx.lineCap = "round";
  ctx.shadowColor = `rgba(${rgb},0.85)`;
  ctx.shadowBlur = 10;
  ctx.strokeStyle = `rgba(${rgb},0.55)`;
  ctx.lineWidth = width + 2;
  path(ctx, pts);
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = `rgb(${rgb})`;
  ctx.lineWidth = width;
  path(ctx, pts);
  ctx.stroke();
  ctx.restore();
}

function pill(ctx, x, y, text, rgb) {
  ctx.save();
  ctx.font = FONT;
  const w = ctx.measureText(text).width + 14;
  const h = 20;
  const left = Math.max(4, Math.min(x - w / 2, ctx.canvas.clientWidth - w - 4));
  const top = Math.max(4, y - h - 6);
  ctx.fillStyle = "rgba(11,14,13,0.88)";
  ctx.strokeStyle = `rgba(${rgb},0.9)`;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(left, top, w, h, 5);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = `rgb(${rgb})`;
  ctx.textBaseline = "middle";
  ctx.fillText(text, left + 7, top + h / 2 + 0.5);
  ctx.restore();
}

/**
 * Draws the offside graphic onto the real broadcast frame using that frame's pitch calibration.
 * Sits exactly over an object-fit: contain <video>, including letterboxing and device pixel ratio.
 * `overlay` is only passed on the assessed frame; `markers` (tracked positions) is an opt-in check.
 */
export default function VideoOverlay({ videoRef, imageSize, homography, pitch, overlay, markers }) {
  const canvasRef = useRef(null);
  const [box, setBox] = useState({ w: 0, h: 0, dpr: 1, vw: 0, vh: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas.parentElement;
    const video = videoRef?.current;
    const measure = () =>
      setBox({
        w: host.clientWidth,
        h: host.clientHeight,
        dpr: window.devicePixelRatio || 1,
        vw: video?.videoWidth || imageSize[0],
        vh: video?.videoHeight || imageSize[1],
      });
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(host);
    video?.addEventListener("loadedmetadata", measure);
    return () => {
      ro?.disconnect();
      video?.removeEventListener("loadedmetadata", measure);
    };
  }, [videoRef, imageSize]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext?.("2d");
    if (!ctx) return;
    canvas.width = Math.round(box.w * box.dpr);
    canvas.height = Math.round(box.h * box.dpr);
    ctx.setTransform(box.dpr, 0, 0, box.dpr, 0, 0);
    ctx.clearRect(0, 0, box.w, box.h);
    if (!homography || (!overlay && !markers)) return;

    const rect = containRect(box.vw, box.vh, box.w, box.h);
    const sign = frontSign(homography, pitch);
    const project = (pts, closed) => projectPath(homography, pts, { closed, sign }).map((p) => toScreen(p, imageSize, rect));
    ctx.save();
    ctx.beginPath();
    ctx.rect(rect.x, rect.y, rect.w, rect.h); // never paint on the letterbox bars
    ctx.clip();

    if (markers) {
      for (const m of markers.players) {
        const [p] = project([[m.x, m.y]]);
        if (!p) continue;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 3.5, 0, Math.PI * 2);
        ctx.fillStyle = m.color;
        ctx.fill();
        ctx.lineWidth = 1.25;
        ctx.strokeStyle = "rgba(11,14,13,0.9)";
        ctx.stroke();
      }
      const b = markers.ball;
      if (b && b.x != null) {
        const ring = project(groundCircle(b.x, b.y, 0.45, 20), true);
        if (ring.length > 2) {
          path(ctx, ring, true);
          ctx.strokeStyle = "rgba(255,255,255,0.9)";
          ctx.lineWidth = 1.5;
          ctx.stroke();
          if (b.z > 0.05) {
            const top = ring.reduce((a, q) => (q[1] < a[1] ? q : a));
            pill(ctx, top[0], top[1], `Ball ${b.z.toFixed(1)} m up`, "255,255,255");
          }
        }
      }
    }

    if (overlay) {
      const rgb = VERDICT_RGB[overlay.verdict] || VERDICT_RGB.inconclusive;
      const shapes = offsideShapes(pitch, overlay);
      if (shapes.band) {
        const band = project(shapes.band, true);
        if (band.length > 2) {
          path(ctx, band, true);
          ctx.fillStyle = `rgba(${AMBER},0.2)`;
          ctx.fill();
          ctx.strokeStyle = `rgba(${AMBER},0.45)`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
      for (const who of [overlay.defender && { ...overlay.defender, rgb: "255,255,255" }, overlay.attacker && { ...overlay.attacker, rgb }]) {
        if (!who) continue;
        const ring = project(groundCircle(who.x, who.y, 1.1), true);
        if (ring.length < 3) continue;
        path(ctx, ring, true);
        ctx.fillStyle = `rgba(${who.rgb},0.14)`;
        ctx.fill();
        glowLine(ctx, [...ring, ring[0]], who.rgb, 1.75);
      }
      const line = shapes.line && project(shapes.line);
      if (line?.length === 2) glowLine(ctx, line, AMBER, 2.5);
      const att = shapes.attacker && project(shapes.attacker);
      if (att?.length === 2) {
        glowLine(ctx, att, rgb, 2);
        // Tag at the visible far end of the attacker's line, like the TV graphic.
        const seg = clipSegmentToRect(att[0], att[1], box.w, box.h);
        if (seg && overlay.label) {
          const top = seg[0][1] < seg[1][1] ? seg[0] : seg[1];
          pill(ctx, top[0], top[1] + 26, overlay.label, rgb);
        }
      }
    }
    ctx.restore();
  }, [box, homography, imageSize, pitch, overlay, markers]);

  return <canvas ref={canvasRef} aria-hidden="true" className="absolute inset-0 w-full h-full pointer-events-none" />;
}

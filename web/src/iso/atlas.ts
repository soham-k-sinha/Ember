/**
 * One sprite sheet painted in code (Canvas 2D) for everything drawn many times: people (8 looks ×
 * 4 poses, plus a white clothing layer tinted per person so status colour reads without losing the
 * figure), trees and shrubs, a street lamp and a soft glow. One texture → one batch.
 */

import { CanvasSource, Rectangle, Texture } from "pixi.js";
import { rgba, type RGB } from "./palette";
import { KZ } from "./project";

export const RES = 26; // atlas px per metre on the ground plane
const V = KZ * RES; // atlas px per vertical metre

export type Pose = "stand" | "walkA" | "walkB" | "wave";
export const POSES: Pose[] = ["stand", "walkA", "walkB", "wave"];
export const LOOKS = 8;
export type TreeKind = "oak" | "oakDark" | "elm" | "pine" | "shrub";
export const TREES: TreeKind[] = ["oak", "oakDark", "elm", "pine", "shrub"];

export type Frame = { tex: Texture; ax: number; ay: number; w: number; h: number };
export type Atlas = {
  person: Frame[][]; // [look][pose]
  cloth: Frame[]; // [pose]
  tree: Record<TreeKind, Frame>;
  lamp: Frame;
  glow: Frame;
  figureM: number; // figure height in metres
};

const SKIN: RGB[] = [[226, 188, 158], [196, 150, 116], [158, 110, 78], [112, 76, 54], [234, 200, 172], [180, 130, 98], [138, 94, 68], [208, 168, 134]];
const HAIR: RGB[] = [[40, 30, 24], [94, 66, 40], [22, 20, 20], [152, 122, 82], [70, 50, 36], [182, 174, 162], [32, 26, 24], [122, 84, 50]];
const LEGS: RGB[] = [[46, 52, 66], [72, 66, 58], [38, 40, 46], [94, 88, 76], [54, 62, 74], [86, 76, 66], [62, 58, 54], [42, 48, 60]];

const RIM = "rgba(14,14,16,0.88)";

function body(_pose: Pose) {
  const hip = 0.85 * V;
  const shoulder = hip + 0.55 * V;
  return { hip, shoulder, head: shoulder + 0.2 * V, headR: 0.135 * V, w: 0.52 * RES };
}

function torso(ctx: CanvasRenderingContext2D, fx: number, fy: number, pose: Pose, grow: number) {
  const g = body(pose);
  const top = fy - g.shoulder - grow;
  const bottom = fy - g.hip + 0.08 * V + grow;
  ctx.beginPath();
  ctx.moveTo(fx - g.w * 0.5 - grow, top + 0.1 * V);
  ctx.quadraticCurveTo(fx - g.w * 0.5 - grow, top, fx - g.w * 0.2, top);
  ctx.lineTo(fx + g.w * 0.2, top);
  ctx.quadraticCurveTo(fx + g.w * 0.5 + grow, top, fx + g.w * 0.5 + grow, top + 0.1 * V);
  ctx.lineTo(fx + g.w * 0.36 + grow, bottom);
  ctx.lineTo(fx - g.w * 0.38 - grow, bottom);
  ctx.closePath();
}

function arms(fx: number, fy: number, pose: Pose): Array<[number, number, number, number]> {
  const g = body(pose);
  const swing = pose === "walkA" ? 0.13 * V : pose === "walkB" ? -0.13 * V : 0;
  const near: [number, number, number, number] = pose === "wave"
    ? [fx + g.w * 0.42, fy - g.shoulder + 0.08 * V, fx + g.w * 0.75, fy - g.shoulder - 0.32 * V]
    : [fx + g.w * 0.42, fy - g.shoulder + 0.08 * V, fx + g.w * 0.44 + swing * 0.6, fy - g.hip + 0.06 * V];
  return [[fx - g.w * 0.42, fy - g.shoulder + 0.08 * V, fx - g.w * 0.46 - swing * 0.6, fy - g.hip + 0.04 * V], near];
}

function person(ctx: CanvasRenderingContext2D, fx: number, fy: number, pose: Pose, look: number) {
  const g = body(pose);
  const skin = SKIN[look % 8];
  const hair = HAIR[(look * 3) % 8];
  const legs = LEGS[(look * 5) % 8];
  const legW = 0.15 * RES;
  ctx.lineCap = "round";
  ctx.fillStyle = RIM;
  torso(ctx, fx, fy, pose, 1.3);
  ctx.fill();
  ctx.strokeStyle = RIM;
  ctx.lineWidth = 0.13 * RES + 2.6;
  for (const [ax, ay, bx, by] of arms(fx, fy, pose)) {
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
  }
  const leg = (hx: number, footX: number, lift: number, col: RGB) => {
    ctx.strokeStyle = RIM;
    ctx.lineWidth = legW + 2.4;
    ctx.beginPath();
    ctx.moveTo(fx + hx, fy - g.hip);
    ctx.lineTo(fx + footX, fy - lift);
    ctx.stroke();
    ctx.strokeStyle = rgba(col);
    ctx.lineWidth = legW;
    ctx.beginPath();
    ctx.moveTo(fx + hx, fy - g.hip);
    ctx.lineTo(fx + footX, fy - lift);
    ctx.stroke();
    ctx.fillStyle = "rgb(28,26,26)";
    ctx.beginPath();
    ctx.ellipse(fx + footX + legW * 0.3, fy - lift, legW * 0.7, legW * 0.42, 0, 0, Math.PI * 2);
    ctx.fill();
  };
  const dark: RGB = [legs[0] * 0.7, legs[1] * 0.7, legs[2] * 0.75];
  const sp = 0.07 * RES;
  if (pose === "walkA") {
    leg(-sp * 0.5, -0.2 * RES, 2.5, dark);
    leg(sp * 0.5, 0.2 * RES, 2, legs);
  } else if (pose === "walkB") {
    leg(-sp * 0.5, 0.17 * RES, 2, dark);
    leg(sp * 0.5, -0.19 * RES, 3, legs);
  } else {
    leg(-sp, -sp * 1.1, 2, dark);
    leg(sp, sp, 2, legs);
  }
  ctx.fillStyle = rgba([skin[0] * 0.9, skin[1] * 0.88, skin[2] * 0.86]);
  for (const [, , bx, by] of arms(fx, fy, pose)) {
    ctx.beginPath();
    ctx.arc(bx, by + 0.03 * V, 0.055 * RES, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = RIM;
  ctx.beginPath();
  ctx.arc(fx, fy - g.head, g.headR + 1.2, 0, Math.PI * 2);
  ctx.fill();
  const lit = ctx.createRadialGradient(fx - g.headR * 0.35, fy - g.head - g.headR * 0.3, g.headR * 0.2, fx, fy - g.head, g.headR * 1.1);
  lit.addColorStop(0, rgba([skin[0] * 1.08, skin[1] * 1.06, skin[2] * 1.04]));
  lit.addColorStop(1, rgba([skin[0] * 0.7, skin[1] * 0.66, skin[2] * 0.64]));
  ctx.fillStyle = lit;
  ctx.beginPath();
  ctx.arc(fx, fy - g.head, g.headR, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = rgba(hair);
  ctx.beginPath();
  ctx.ellipse(fx - g.headR * 0.2, fy - g.head - g.headR * 0.3, g.headR * 1.02, g.headR * 0.78, 0, Math.PI * 0.85, Math.PI * 2.1);
  ctx.fill();
  if (look % 3 === 1) {
    ctx.beginPath();
    ctx.ellipse(fx - g.headR * 0.7, fy - g.head + g.headR * 0.3, g.headR * 0.5, g.headR * 0.95, 0, 0, Math.PI * 2);
    ctx.fill();
  }
}

function cloth(ctx: CanvasRenderingContext2D, fx: number, fy: number, pose: Pose) {
  const g = body(pose);
  const grad = ctx.createLinearGradient(fx - g.w / 2, fy - g.shoulder, fx + g.w / 2, fy - g.hip);
  grad.addColorStop(0, "rgb(255,255,255)");
  grad.addColorStop(0.5, "rgb(224,224,224)");
  grad.addColorStop(1, "rgb(146,146,154)");
  ctx.fillStyle = grad;
  torso(ctx, fx, fy, pose, 0);
  ctx.fill();
  ctx.fillStyle = "rgba(0,0,0,0.22)";
  ctx.fillRect(fx - g.w * 0.38, fy - g.hip + 0.01 * V, g.w * 0.74, 0.06 * V);
  ctx.lineCap = "round";
  ctx.lineWidth = 0.13 * RES;
  const [far, near] = arms(fx, fy, pose);
  ctx.strokeStyle = "rgb(150,150,158)";
  ctx.beginPath();
  ctx.moveTo(far[0], far[1]);
  ctx.lineTo(far[2], far[3]);
  ctx.stroke();
  ctx.strokeStyle = "rgb(208,208,212)";
  ctx.beginPath();
  ctx.moveTo(near[0], near[1]);
  ctx.lineTo(near[2], near[3]);
  ctx.stroke();
}

function leafClump(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, base: RGB, rnd: () => number) {
  const g = ctx.createRadialGradient(x - r * 0.4, y - r * 0.45, r * 0.1, x, y, r * 1.05);
  g.addColorStop(0, rgba([base[0] * 1.5, base[1] * 1.42, base[2] * 1.28]));
  g.addColorStop(0.55, rgba(base));
  g.addColorStop(1, rgba([base[0] * 0.5, base[1] * 0.55, base[2] * 0.62]));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  for (let i = 0; i < r * 1.5; i++) {
    const a = rnd() * Math.PI * 2;
    const d = Math.sqrt(rnd()) * r * 0.9;
    const px = x + Math.cos(a) * d;
    const py = y + Math.sin(a) * d;
    ctx.fillStyle = px - x + (py - y) < 0 ? "rgba(196,206,146,0.16)" : "rgba(10,20,10,0.2)";
    ctx.beginPath();
    ctx.arc(px, py, 1 + rnd() * 1.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

function tree(ctx: CanvasRenderingContext2D, bx: number, by: number, kind: TreeKind, seed: number) {
  let s = seed * 7919 + 104729;
  const rnd = () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
  if (kind === "pine") {
    const h = 7.5 * V;
    const w = 2.0 * RES;
    ctx.fillStyle = "rgb(60,44,34)";
    ctx.fillRect(bx - 0.12 * RES, by - 1.2 * V, 0.24 * RES, 1.2 * V);
    for (let i = 0; i < 5; i++) {
      const t0 = 0.12 + (i / 5) * 0.8;
      const yb = by - h * t0;
      const yt = by - h * Math.min(1, t0 + 0.34);
      const ww = w * (1 - i / 5.6);
      const g = ctx.createLinearGradient(bx - ww, 0, bx + ww, 0);
      g.addColorStop(0, "rgb(68,94,66)");
      g.addColorStop(0.45, "rgb(40,62,46)");
      g.addColorStop(1, "rgb(22,36,30)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(bx - ww, yb);
      ctx.quadraticCurveTo(bx, yb + 0.25 * RES, bx + ww, yb);
      ctx.lineTo(bx, yt);
      ctx.closePath();
      ctx.fill();
    }
    return;
  }
  if (kind === "shrub") {
    const r = 0.7 * RES;
    for (const [dx, dz] of [[-0.7, 0.55], [0.6, 0.6], [0, 0.9], [-0.2, 0.3]]) leafClump(ctx, bx + dx * r, by - dz * r * 1.3, r * (0.75 + rnd() * 0.3), [58, 78, 46], rnd);
    return;
  }
  const base: RGB = kind === "oak" ? [62, 84, 46] : kind === "oakDark" ? [46, 64, 40] : [76, 90, 48];
  const trunk = 2.2 * V;
  ctx.strokeStyle = "rgb(62,48,38)";
  ctx.lineCap = "round";
  ctx.lineWidth = 0.32 * RES;
  ctx.beginPath();
  ctx.moveTo(bx, by);
  ctx.lineTo(bx + 0.05 * RES, by - trunk);
  ctx.stroke();
  ctx.lineWidth = 0.14 * RES;
  ctx.beginPath();
  ctx.moveTo(bx, by - trunk * 0.7);
  ctx.lineTo(bx - 0.6 * RES, by - trunk * 1.15);
  ctx.moveTo(bx, by - trunk * 0.8);
  ctx.lineTo(bx + 0.7 * RES, by - trunk * 1.2);
  ctx.stroke();
  const R = (kind === "elm" ? 2.1 : 2.4) * RES;
  const cy = by - trunk - R * 0.75;
  const clumps: Array<[number, number, number]> = [];
  for (let i = 0; i < 9; i++) {
    const a = (i / 9) * Math.PI * 2 + rnd() * 0.5;
    const d = (0.35 + rnd() * 0.4) * R;
    clumps.push([bx + Math.cos(a) * d, cy + Math.sin(a) * d * 0.7, R * (0.42 + rnd() * 0.2)]);
  }
  clumps.sort((p, q) => p[1] - q[1]);
  clumps.push([bx - R * 0.05, cy - R * 0.3, R * 0.55]);
  for (const [x, y, r] of clumps) leafClump(ctx, x, y, r, base, rnd);
}

export function buildAtlas(): Atlas {
  const canvas = document.createElement("canvas");
  canvas.width = 2048;
  canvas.height = 1024;
  const ctx = canvas.getContext("2d")!;
  type Cell = { x: number; y: number; w: number; h: number; ax: number; ay: number };
  const cells: Record<string, Cell> = {};
  let cx = 4;
  let cy = 4;
  let rowH = 0;
  const alloc = (key: string, w: number, h: number, ax: number, ay: number) => {
    if (cx + w + 4 > canvas.width) {
      cx = 4;
      cy += rowH + 6;
      rowH = 0;
    }
    cells[key] = { x: cx, y: cy, w, h, ax, ay };
    cx += w + 6;
    rowH = Math.max(rowH, h);
    return cells[key];
  };
  TREES.forEach((kind, i) => {
    const w = Math.ceil(6 * RES);
    const h = Math.ceil(10.5 * V);
    const c = alloc(`tree:${kind}`, w, h, w / 2, h - 0.6 * RES);
    tree(ctx, c.x + c.ax, c.y + c.ay, kind, i + 3);
  });
  cx = 4;
  cy += rowH + 6;
  rowH = 0;
  const fw = Math.ceil(1.1 * RES);
  const fh = Math.ceil(2.05 * V);
  for (let look = 0; look < LOOKS; look++) {
    for (const pose of POSES) {
      const c = alloc(`person:${look}:${pose}`, fw, fh, fw / 2, fh - 3);
      person(ctx, c.x + c.ax, c.y + c.ay, pose, look);
    }
  }
  for (const pose of POSES) {
    const c = alloc(`cloth:${pose}`, fw, fh, fw / 2, fh - 3);
    cloth(ctx, c.x + c.ax, c.y + c.ay, pose);
  }
  {
    const w = Math.ceil(0.9 * RES);
    const h = Math.ceil(4.4 * V);
    const c = alloc("lamp", w, h, w / 2, h - 3);
    const fx = c.x + c.ax;
    const fy = c.y + c.ay;
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.beginPath();
    ctx.ellipse(fx + 2, fy, 0.25 * RES, 0.12 * RES, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#24272b";
    ctx.fillRect(fx - 0.1 * RES, fy - 0.35 * V, 0.2 * RES, 0.35 * V);
    ctx.fillStyle = "#2e3236";
    ctx.fillRect(fx - 0.05 * RES, fy - 3.6 * V, 0.1 * RES, 3.3 * V);
    ctx.fillStyle = "#4b5157";
    ctx.fillRect(fx - 0.05 * RES, fy - 3.6 * V, 0.035 * RES, 3.3 * V);
    ctx.fillStyle = "#1f2226";
    ctx.beginPath();
    ctx.moveTo(fx - 0.22 * RES, fy - 4.0 * V);
    ctx.lineTo(fx + 0.22 * RES, fy - 4.0 * V);
    ctx.lineTo(fx, fy - 4.2 * V);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#8f8064";
    ctx.fillRect(fx - 0.15 * RES, fy - 4.0 * V, 0.3 * RES, 0.42 * V);
  }
  {
    const w = 64;
    const c = alloc("glow", w, w, w / 2, w / 2);
    const g = ctx.createRadialGradient(c.x + w / 2, c.y + w / 2, 0, c.x + w / 2, c.y + w / 2, w / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.18, "rgba(255,255,255,0.65)");
    g.addColorStop(0.5, "rgba(255,255,255,0.16)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(c.x, c.y, w, w);
  }
  const source = new CanvasSource({ resource: canvas, autoGenerateMipmaps: true, scaleMode: "linear" });
  const frame = (key: string): Frame => {
    const c = cells[key];
    return { tex: new Texture({ source, frame: new Rectangle(c.x, c.y, c.w, c.h) }), ax: c.ax / c.w, ay: c.ay / c.h, w: c.w, h: c.h };
  };
  return {
    person: Array.from({ length: LOOKS }, (_, look) => POSES.map((pose) => frame(`person:${look}:${pose}`))),
    cloth: POSES.map((pose) => frame(`cloth:${pose}`)),
    tree: Object.fromEntries(TREES.map((kind) => [kind, frame(`tree:${kind}`)])) as Record<TreeKind, Frame>,
    lamp: frame("lamp"),
    glow: frame("glow"),
    figureM: 1.75,
  };
}

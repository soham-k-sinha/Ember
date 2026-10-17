/**
 * Real buildings as flat-shaded isometric volumes (Pixi Graphics), from their actual footprints:
 * walls facing the viewer shaded by direction (shadows drift cool), a dark band where walls meet
 * the ground, a bright top edge, windows per floor in the building's style (some lit after dusk on
 * an additive glow layer), and roofs from the city's roof type (gables along the long axis,
 * parapets and rooftop units on flat roofs). Each building returns its cast-shadow outline.
 * Materials are rules from the research palette (synthetic, labelled): measured geometry, styled colour.
 */

import { Container, Graphics } from "pixi.js";
import { LANDMARKS, type DioBuilding } from "./data";
import { SUN_SHADOW } from "./ground";
import { BUILD, hashN, mix, shade } from "./palette";
import type { Projector } from "./project";

type AB = [number, number];
type P3 = [number, number, number];

export type Material = { wall: number; roof: number; style: "house" | "brick" | "modern" | "concrete" | "civic"; label?: string };

function area(ab: AB[]): number {
  let s = 0;
  for (let i = 0; i < ab.length; i++) {
    const [x1, y1] = ab[i];
    const [x2, y2] = ab[(i + 1) % ab.length];
    s += x1 * y2 - x2 * y1;
  }
  return s / 2;
}

export function hull(points: AB[]): AB[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o: AB, a: AB, b: AB) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: AB[] = [];
  const upper: AB[] = [];
  for (const q of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop();
    lower.push(q);
  }
  for (let i = pts.length - 1; i >= 0; i--) {
    const q = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop();
    upper.push(q);
  }
  upper.pop();
  lower.pop();
  return lower.concat(upper);
}

export function materialFor(b: DioBuilding, id: number, footArea: number): Material {
  const lm = b.name ? LANDMARKS.find((item) => item.match.test(b.name!)) : undefined;
  const cambridge = b.src.startsWith("cambridge");
  if (lm) {
    const style = lm.wall === 0x9c3d2c ? "brick" : b.h > 30 ? "concrete" : "civic";
    return { wall: lm.wall, roof: lm.roof ?? (style === "brick" ? BUILD.slate : BUILD.membrane), style, label: lm.label };
  }
  if ((b.use === "residential" || b.use === "other") && b.roof === "pitched" && footArea < 420) {
    const accent = hashN(id, 3) < 0.12;
    return { wall: accent ? BUILD.clapAccent[id % 3] : BUILD.clapboard[Math.floor(hashN(id, 5) * BUILD.clapboard.length)], roof: hashN(id, 7) < 0.5 ? BUILD.shingle : BUILD.slate, style: "house" };
  }
  if (b.use === "education") return { wall: [BUILD.brick, BUILD.brickDark, BUILD.brickLight][id % 3], roof: b.roof === "pitched" ? BUILD.slate : BUILD.membrane, style: "brick" };
  if (b.h > 32) return { wall: hashN(id, 9) < 0.5 ? BUILD.concrete : BUILD.concreteDark, roof: BUILD.membrane, style: "concrete" };
  if (b.use === "commercial" || b.use === "industrial") return { wall: hashN(id, 11) < 0.5 ? BUILD.steel : 0xb4ab9a, roof: BUILD.membrane, style: "modern" };
  if (cambridge && footArea < 900) {
    return hashN(id, 13) < 0.5
      ? { wall: [BUILD.brick, BUILD.brickDark, BUILD.brickLight][id % 3], roof: BUILD.membrane, style: "brick" }
      : { wall: BUILD.clapboard[Math.floor(hashN(id, 15) * BUILD.clapboard.length)], roof: BUILD.shingle, style: "house" };
  }
  return hashN(id, 17) < 0.55
    ? { wall: [BUILD.brick, BUILD.brickDark, BUILD.brickLight][id % 3], roof: BUILD.membrane, style: "brick" }
    : { wall: hashN(id, 19) < 0.5 ? 0xb4ab9a : BUILD.stone, roof: BUILD.membrane, style: "modern" };
}

/** Wall brightness by outward normal (unit, a = east, b = south): south faces catch more of the evening light. */
const faceShade = (na: number, nb: number) => 0.6 * na * na + 0.84 * nb * nb + 0.72 * Math.max(0, 1 - na * na - nb * nb);

export type Built = { node: Container; depth: number; shadow: AB[]; foot: AB[]; topM: number; label?: string; labelAt?: P3 };

export function drawBuilding(p: Projector, b: DioBuilding, id: number, detail = true): Built {
  let foot: AB[] = b.ring.map(([lon, lat]) => p.toAB(lon, lat));
  const A = area(foot);
  if (A < 0) foot = [...foot].reverse(); // positive signed area in (a, b) → outward normal of edge (da, db) is (db, −da)
  const footArea = Math.abs(A);
  const mat = materialFor(b, id, footArea);
  const pitched = b.roof === "pitched";
  const eave = pitched ? b.eave ?? b.h * 0.78 : b.h;
  const body = new Graphics();
  const glow = new Graphics();
  glow.blendMode = "add";
  const iso = (x: number, y: number, z: number) => p.iso(x, y, z);
  const poly = (g: Graphics, pts: P3[], color: number, alpha = 1) => {
    const flat: number[] = [];
    for (const [x, y, z] of pts) {
      const [sx, sy] = iso(x, y, z);
      flat.push(sx, sy);
    }
    g.poly(flat).fill({ color, alpha });
  };
  const line = (pts: P3[], color: number, width: number, alpha = 1) => {
    const [x0, y0] = iso(...pts[0]);
    body.moveTo(x0, y0);
    for (let i = 1; i < pts.length; i++) {
      const [x, y] = iso(...pts[i]);
      body.lineTo(x, y);
    }
    body.stroke({ color, width, alpha, cap: "round", join: "round" });
  };

  // walls facing the viewer, far to near
  type Wall = { i: number; d: number; na: number; nb: number; len: number };
  const walls: Wall[] = [];
  for (let i = 0; i < foot.length; i++) {
    const [a1, b1] = foot[i];
    const [a2, b2] = foot[(i + 1) % foot.length];
    const da = a2 - a1;
    const db = b2 - b1;
    const len = Math.hypot(da, db);
    if (len < 0.05) continue;
    const na = db / len;
    const nb = -da / len;
    if (na + nb <= 0.001) continue;
    walls.push({ i, d: a1 + b1 + a2 + b2, na, nb, len });
  }
  walls.sort((x, y) => x.d - y.d);
  const glass = mat.style === "modern" || mat.style === "concrete" ? BUILD.glass : BUILD.glassDark;
  for (const w of walls) {
    const [a1, b1] = foot[w.i];
    const [a2, b2] = foot[(w.i + 1) % foot.length];
    const f = faceShade(w.na, w.nb);
    poly(body, [[a1, b1, 0], [a2, b2, 0], [a2, b2, eave], [a1, b1, eave]], shade(mat.wall, f));
    if (eave > 1) {
      const ao = Math.min(0.7, eave * 0.08);
      poly(body, [[a1, b1, 0], [a2, b2, 0], [a2, b2, ao], [a1, b1, ao]], 0x000000, 0.22);
      poly(body, [[a1, b1, 0], [a2, b2, 0], [a2, b2, 0.45], [a1, b1, 0.45]], shade(mix(mat.wall, BUILD.stoneDark, 0.5), f), 0.9);
    }
    // windows (full detail only: the district view draws plain volumes)
    const floors = Math.max(0, Math.floor((eave - 0.8) / 3.3));
    if (!detail || floors < 1 || w.len < 3) continue;
    const ua = (a2 - a1) / w.len;
    const ub = (b2 - b1) / w.len;
    const off = 0.06;
    const at = (s: number, z: number): P3 => [a1 + ua * s + w.na * off, b1 + ub * s + w.nb * off, z];
    for (let fl = 0; fl < floors; fl++) {
      const z0 = fl * 3.3 + 1.0;
      if (mat.style === "modern" || (mat.style === "concrete" && b.h < 45)) {
        const z1 = z0 + 1.7;
        poly(body, [at(0.5, z0), at(w.len - 0.5, z0), at(w.len - 0.5, z1), at(0.5, z1)], shade(glass, f * 1.05), 0.92);
        if (hashN(id * 31 + fl * 7 + w.i, 5) < 0.45) poly(glow, [at(0.5, z0), at(w.len - 0.5, z0), at(w.len - 0.5, z1), at(0.5, z1)], 0xffb766, 0.55);
        continue;
      }
      const spacing = mat.style === "house" ? 2.9 : 2.5;
      const ww = mat.style === "house" ? 0.9 : 0.85;
      const wh = mat.style === "house" ? 1.3 : 1.45;
      const k = Math.max(1, Math.floor((w.len - 1.2) / spacing));
      const start = (w.len - (k - 1) * spacing) / 2;
      for (let n = 0; n < k; n++) {
        const c = start + n * spacing;
        const q: P3[] = [at(c - ww / 2, z0), at(c + ww / 2, z0), at(c + ww / 2, z0 + wh), at(c - ww / 2, z0 + wh)];
        if (mat.style === "brick" || mat.style === "house") {
          poly(body, [at(c - ww / 2 - 0.12, z0 - 0.1), at(c + ww / 2 + 0.12, z0 - 0.1), at(c + ww / 2 + 0.12, z0 + wh + 0.1), at(c - ww / 2 - 0.12, z0 + wh + 0.1)], shade(0xeee8dc, f), 0.85);
        }
        const lit = hashN(id * 977 + fl * 131 + w.i * 17 + n, 9) < (mat.style === "house" ? 0.42 : 0.32);
        poly(body, q, lit ? shade(0x4a5258, f * 1.1) : shade(glass, f), 0.92);
        if (lit) poly(glow, q, 0xffb766, 0.9);
      }
    }
    // a door on the longest south-facing wall of houses
  }
  const front = walls.filter((w) => w.nb > 0.5).sort((x, y) => y.len - x.len)[0];
  if (detail && front && (mat.style === "house" || mat.style === "brick") && front.len > 3) {
    const [a1, b1] = foot[front.i];
    const [a2, b2] = foot[(front.i + 1) % foot.length];
    const ua = (a2 - a1) / front.len;
    const ub = (b2 - b1) / front.len;
    const m = front.len / 2 + 0.35;
    const at = (s: number, z: number): P3 => [a1 + ua * s + front.na * 0.07, b1 + ub * s + front.nb * 0.07, z];
    poly(body, [at(m - 0.55, 0), at(m + 0.55, 0), at(m + 0.55, 2.2), at(m - 0.55, 2.2)], 0x2a2420);
    poly(glow, [at(m - 0.55, 1.5), at(m + 0.55, 1.5), at(m + 0.55, 2.2), at(m - 0.55, 2.2)], 0xffc27a, 0.6);
  }

  // roof
  let topM = b.h;
  const gable = pitched ? obb(foot) : null;
  if (gable && gable.fill > 0.72 && gable.halfV > 1.5) {
    const { c, u, v, halfU, halfV } = gable;
    const o = 0.35;
    const rise = Math.min(5.5, Math.max(1.2, b.h - eave), halfV * 0.95);
    topM = eave + rise;
    const pt = (s: number, t: number, z: number): P3 => [c[0] + u[0] * s + v[0] * t, c[1] + u[1] * s + v[1] * t, z];
    const slopes = [
      { n: [-v[0], -v[1]] as AB, pts: [pt(-halfU - o, -halfV - o, eave), pt(halfU + o, -halfV - o, eave), pt(halfU + o, 0, topM), pt(-halfU - o, 0, topM)] },
      { n: [v[0], v[1]] as AB, pts: [pt(-halfU - o, halfV + o, eave), pt(halfU + o, halfV + o, eave), pt(halfU + o, 0, topM), pt(-halfU - o, 0, topM)] },
    ];
    const ends = [
      { n: [-u[0], -u[1]] as AB, pts: [pt(-halfU, -halfV, eave), pt(-halfU, halfV, eave), pt(-halfU, 0, topM)] },
      { n: [u[0], u[1]] as AB, pts: [pt(halfU, -halfV, eave), pt(halfU, halfV, eave), pt(halfU, 0, topM)] },
    ];
    const toward = (n: AB) => n[0] + n[1];
    const [far, near] = [...slopes].sort((x, y) => toward(x.n) - toward(y.n));
    poly(body, far.pts, shade(mat.roof, 1.08));
    for (const e of ends) if (toward(e.n) > 0) poly(body, e.pts, shade(mat.wall, faceShade(Math.abs(e.n[0]), Math.abs(e.n[1])) * 0.95));
    poly(body, near.pts, shade(mat.roof, toward(near.n) > 0.6 ? 0.78 : 0.92));
    line([pt(-halfU - o, 0, topM), pt(halfU + o, 0, topM)], shade(mat.roof, 1.35), 0.12, 0.85);
    line([near.pts[0], near.pts[1]], shade(mat.roof, 0.45), 0.1, 0.8);
    // chimney on some houses
    if (detail && mat.style === "house" && hashN(id, 21) < 0.45) {
      const s = halfU * 0.45;
      const t = -halfV * 0.35;
      box(body, poly, pt(s - 0.4, t - 0.4, 0), pt(s + 0.4, t + 0.4, 0), u, v, topM - 1.2, topM + 1.0, 0x7a4a3c);
    }
  } else {
    const roofColor = mat.roof === BUILD.membrane && b.tone != null ? shade(BUILD.membrane, 0.78 + (b.tone / 100) * 0.5) : mat.roof;
    poly(body, foot.map(([a, bb]) => [a, bb, b.h] as P3), roofColor);
    // parapet lip: a slightly darker inset ring
    const cen = foot.reduce((acc, q) => [acc[0] + q[0] / foot.length, acc[1] + q[1] / foot.length], [0, 0]);
    const inset = foot.map(([a, bb]) => {
      const d = Math.hypot(a - cen[0], bb - cen[1]) || 1;
      const k = Math.max(0, (d - 0.7) / d);
      return [cen[0] + (a - cen[0]) * k, cen[1] + (bb - cen[1]) * k, b.h] as P3;
    });
    if (footArea > 60) poly(body, inset, shade(roofColor, 0.9));
    // rooftop units on big flat roofs
    if (detail && footArea > 700 && mat.style !== "house") {
      const n = Math.min(4, Math.floor(footArea / 900) + 1);
      for (let k = 0; k < n; k++) {
        const ox = (hashN(id * 13 + k, 31) - 0.5) * Math.sqrt(footArea) * 0.35;
        const oy = (hashN(id * 17 + k, 37) - 0.5) * Math.sqrt(footArea) * 0.35;
        const s = 1.4 + hashN(id + k, 41) * 1.6;
        box(body, poly, [cen[0] + ox - s, cen[1] + oy - s * 0.7, 0], [cen[0] + ox + s, cen[1] + oy + s * 0.7, 0], [1, 0], [0, 1], b.h, b.h + 1.3, 0x9a9c9c);
      }
    }
  }
  // top edges of the viewer-facing walls catch the light
  for (const w of walls) {
    const [a1, b1] = foot[w.i];
    const [a2, b2] = foot[(w.i + 1) % foot.length];
    line([[a1, b1, eave], [a2, b2, eave]], shade(mat.wall, 1.3), 0.14, 0.55);
  }

  const node = new Container();
  node.addChild(body, glow);
  (node as Container & { glow?: Graphics }).glow = glow;
  const shadowPts: AB[] = [...foot];
  for (const [a, bb] of foot) shadowPts.push([a + SUN_SHADOW[0] * topM * 1.1, bb + SUN_SHADOW[1] * topM * 1.1]);
  const cen = foot.reduce((acc, q) => [acc[0] + q[0] / foot.length, acc[1] + q[1] / foot.length], [0, 0]);
  return {
    node,
    depth: Math.max(...foot.map(([a, bb]) => a + bb)),
    shadow: hull(shadowPts),
    foot,
    topM,
    label: mat.label,
    labelAt: [cen[0], cen[1], topM],
  };
}

/** Small oriented box (rooftop unit, chimney): only the two viewer-facing walls and the top. */
function box(g: Graphics, poly: (g: Graphics, pts: P3[], color: number, alpha?: number) => void, lo: P3, hi: P3, u: AB, v: AB, z0: number, z1: number, color: number) {
  const corners: AB[] = [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]];
  void u;
  void v;
  for (let i = 0; i < 4; i++) {
    const [a1, b1] = corners[i];
    const [a2, b2] = corners[(i + 1) % 4];
    const na = b2 - b1;
    const nb = -(a2 - a1);
    if (na + nb <= 0) continue;
    const len = Math.hypot(na, nb) || 1;
    poly(g, [[a1, b1, z0], [a2, b2, z0], [a2, b2, z1], [a1, b1, z1]], shade(color, faceShade(na / len, nb / len)));
  }
  poly(g, corners.map(([a, b]) => [a, b, z1] as P3), shade(color, 1.1));
}

/** Oriented bounding box via the footprint's principal axis; `fill` = footprint area / box area. */
function obb(foot: AB[]): { c: AB; u: AB; v: AB; halfU: number; halfV: number; fill: number } | null {
  if (foot.length < 4) return null;
  let cx = 0;
  let cy = 0;
  for (const [x, y] of foot) {
    cx += x;
    cy += y;
  }
  cx /= foot.length;
  cy /= foot.length;
  // longest edge direction is a steadier ridge direction than PCA for building outlines
  let best = 0;
  let dir: AB = [1, 0];
  for (let i = 0; i < foot.length; i++) {
    const [x1, y1] = foot[i];
    const [x2, y2] = foot[(i + 1) % foot.length];
    const l = Math.hypot(x2 - x1, y2 - y1);
    if (l > best) {
      best = l;
      dir = [(x2 - x1) / l, (y2 - y1) / l];
    }
  }
  let u: AB = dir;
  let v: AB = [-dir[1], dir[0]];
  const span = (ax: AB) => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const [x, y] of foot) {
      const s = (x - cx) * ax[0] + (y - cy) * ax[1];
      lo = Math.min(lo, s);
      hi = Math.max(hi, s);
    }
    return [lo, hi];
  };
  let [ulo, uhi] = span(u);
  let [vlo, vhi] = span(v);
  if (vhi - vlo > uhi - ulo) {
    [u, v] = [v, [-v[0], -v[1]] as AB];
    [ulo, uhi] = span(u);
    [vlo, vhi] = span(v);
  }
  const c: AB = [cx + u[0] * (ulo + uhi) / 2 + v[0] * (vlo + vhi) / 2, cy + u[1] * (ulo + uhi) / 2 + v[1] * (vlo + vhi) / 2];
  const halfU = (uhi - ulo) / 2;
  const halfV = (vhi - vlo) / 2;
  const fill = Math.abs(area(foot)) / Math.max(1e-6, 4 * halfU * halfV);
  return { c, u, v, halfU, halfV, fill };
}

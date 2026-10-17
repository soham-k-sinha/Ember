/**
 * Street furniture the open data implies but does not draw (D71):
 *  - parked cars in surface car-park bays (along OSM/Overture parking aisles) — illustrative fill;
 *  - the Enterprise Research Campus construction site (Overture land use "construction"): a site fence on
 *    its boundary, cabins, material piles and tower cranes — illustrative dressing of a real site.
 * Each piece is its own depth-sorted object so buildings, people and vehicles pass in front and behind.
 */

import { Graphics } from "pixi.js";
import type { Diorama } from "./data";
import { hashN, shade } from "./palette";
import type { Projector } from "./project";

type AB = [number, number];
export type Prop = { node: Graphics; a: number; b: number; bounds: { x0: number; y0: number; x1: number; y1: number } };

const CAR_COLORS = [0xd8d8d4, 0x2b2e33, 0x8d9299, 0x6b1f22, 0x24395c, 0xe9e6dc, 0x4a4f55, 0x7c8a6a, 0xb7aa92, 0x3e5f7a, 0xa03a2a, 0x16181b];

/** Oriented box at ground centre (ca, cb) facing `ang` (radians, in a/b), drawn into g around the origin (ox, oy). */
function obox(g: Graphics, p: Projector, ox: number, oy: number, ca: number, cb: number, ang: number, L: number, W: number, z0: number, z1: number, color: number, edge = 0x101010) {
  const fa = Math.cos(ang);
  const fb = Math.sin(ang);
  const corner = (u: number, v: number): AB => [ca + fa * u - fb * v, cb + fb * u + fa * v];
  const base = [corner(L / 2, -W / 2), corner(L / 2, W / 2), corner(-L / 2, W / 2), corner(-L / 2, -W / 2)];
  const iso = (a: number, b: number, z: number): [number, number] => {
    const [x, y] = p.iso(a, b, z);
    return [x - ox, y - oy];
  };
  // signed area → make outward normals consistent
  let area = 0;
  for (let i = 0; i < 4; i++) {
    const [a1, b1] = base[i];
    const [a2, b2] = base[(i + 1) % 4];
    area += a1 * b2 - a2 * b1;
  }
  const order = area > 0 ? base : [...base].reverse();
  for (let i = 0; i < 4; i++) {
    const [a1, b1] = order[i];
    const [a2, b2] = order[(i + 1) % 4];
    const na = b2 - b1;
    const nb = -(a2 - a1);
    if (na + nb <= 0) continue; // faces away from the viewer
    const len = Math.hypot(na, nb) || 1;
    const k = 0.62 * (na / len) ** 2 + 0.86 * (nb / len) ** 2 + 0.08;
    g.poly([...iso(a1, b1, z0), ...iso(a2, b2, z0), ...iso(a2, b2, z1), ...iso(a1, b1, z1)]).fill(shade(color, k)).stroke({ width: 0.06, color: edge, alpha: 0.5 });
  }
  g.poly(base.flatMap(([a, b]) => iso(a, b, z1))).fill(shade(color, 1.06)).stroke({ width: 0.06, color: edge, alpha: 0.5 });
}

function boundsOf(g: Graphics, x: number, y: number) {
  const b = g.getLocalBounds();
  return { x0: x + b.minX, y0: y + b.minY, x1: x + b.maxX, y1: y + b.maxY };
}

export function car(p: Projector, a: number, b: number, ang: number, color: number): Graphics {
  const [ox, oy] = p.iso(a, b);
  const g = new Graphics();
  // soft contact shadow, then body, cabin, glass
  const fa = Math.cos(ang);
  const fb = Math.sin(ang);
  const sh: AB[] = [[2.4, -1.05], [2.4, 1.05], [-2.4, 1.05], [-2.4, -1.05]].map(([u, v]) => [a + fa * u - fb * v + 0.35, b + fb * u + fa * v - 0.15]);
  g.poly(sh.flatMap(([sa, sb]) => { const [x, y] = p.iso(sa, sb); return [x - ox, y - oy]; })).fill({ color: 0x000000, alpha: 0.28 });
  obox(g, p, ox, oy, a, b, ang, 4.4, 1.8, 0.18, 0.9, color);
  obox(g, p, ox, oy, a - fa * 0.25, b - fb * 0.25, ang, 2.3, 1.62, 0.9, 1.42, shade(color, 0.92));
  obox(g, p, ox, oy, a - fa * 0.25, b - fb * 0.25, ang, 2.1, 1.66, 0.98, 1.34, 0x1f2a33, 0x0b0f12);
  obox(g, p, ox, oy, a - fa * 0.25, b - fb * 0.25, ang, 2.0, 1.5, 1.34, 1.44, shade(color, 1.0));
  g.position.set(ox, oy);
  return g;
}

/** Bay centres along every parking aisle, both sides, 2.6 m apart, ~70 % occupied. */
function bays(data: Diorama, p: Projector, insideBuilding: (a: number, b: number) => boolean): Array<{ a: number; b: number; ang: number; color: number }> {
  const out: Array<{ a: number; b: number; ang: number; color: number }> = [];
  const { a0, a1, b0, b1 } = p.bounds;
  let n = 0;
  const taken = new Set<string>();
  for (const road of data.roads) {
    if (road.k !== "parking_aisle") continue;
    const pts = road.path.map(([lon, lat]) => p.toAB(lon, lat));
    let carry = 1.3;
    for (let i = 1; i < pts.length; i++) {
      const [pa, pb] = pts[i - 1];
      const [qa, qb] = pts[i];
      const len = Math.hypot(qa - pa, qb - pb);
      if (len < 0.01) continue;
      const ua = (qa - pa) / len;
      const ub = (qb - pb) / len;
      for (; carry < len; carry += 2.6) {
        for (const side of [1, -1]) {
          n++;
          if (hashN(n, 71) > 0.7) continue;
          const a = pa + ua * carry - ub * 5.25 * side + ua * 1.3;
          const b = pb + ub * carry + ua * 5.25 * side + ub * 1.3;
          if (a < a0 + 3 || a > a1 - 3 || b < b0 + 3 || b > b1 - 3 || insideBuilding(a, b)) continue;
          // where aisles meet or run close, keep one car per spot
          const key = `${Math.round(a / 2.4)},${Math.round(b / 2.4)}`;
          if (taken.has(key)) continue;
          taken.add(key);
          // nose in or tail in
          const ang = Math.atan2(ua * side, -ub * side) + (hashN(n, 72) > 0.5 ? Math.PI : 0);
          out.push({ a, b, ang, color: CAR_COLORS[Math.floor(hashN(n, 73) * CAR_COLORS.length)] });
        }
      }
      carry -= len;
    }
  }
  return out;
}

function inPoly(ring: AB[], a: number, b: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ai, bi] = ring[i];
    const [aj, bj] = ring[j];
    if (bi > b !== bj > b && a < ((aj - ai) * (b - bi)) / (bj - bi) + ai) inside = !inside;
  }
  return inside;
}

function crane(p: Projector, a: number, b: number, ang: number, h: number): Graphics {
  const [ox, oy] = p.iso(a, b);
  const g = new Graphics();
  const Y = 0xe7b416;
  const iso = (pa: number, pb: number, z: number): [number, number] => {
    const [x, y] = p.iso(pa, pb, z);
    return [x - ox, y - oy];
  };
  obox(g, p, ox, oy, a, b, 0, 4.5, 4.5, 0, 1.2, 0x8f8f8a); // footing
  obox(g, p, ox, oy, a, b, 0, 1.7, 1.7, 1.2, h, Y, 0x5a4708); // mast
  // lattice on the mast's two visible faces
  for (let z = 1.2; z < h - 1; z += 1.7) {
    const [x1, y1] = iso(a + 0.85, b - 0.85, z);
    const [x2, y2] = iso(a + 0.85, b + 0.85, z + 1.7);
    const [x3, y3] = iso(a - 0.85, b + 0.85, z);
    g.moveTo(x1, y1).lineTo(x2, y2).lineTo(x3, y3).stroke({ width: 0.1, color: 0x6b5410, alpha: 0.8 });
  }
  const fa = Math.cos(ang);
  const fb = Math.sin(ang);
  const jib = 36;
  const counter = 11;
  const [tx, ty] = iso(a, b, h + 4.5);
  const [jx, jy] = iso(a + fa * jib, b + fb * jib, h + 0.8);
  const [jx2, jy2] = iso(a + fa * jib, b + fb * jib, h);
  const [cx, cy] = iso(a - fa * counter, b - fb * counter, h + 0.8);
  const [bx, by] = iso(a, b, h);
  const [bx2, by2] = iso(a, b, h + 0.8);
  // jib and counter-jib (top and bottom chords + zigzag), tie lines to the tower top
  g.moveTo(bx2, by2).lineTo(jx, jy).moveTo(bx, by).lineTo(jx2, jy2).stroke({ width: 0.22, color: Y });
  for (let s = 0; s < jib; s += 2.4) {
    const [x1, y1] = iso(a + fa * s, b + fb * s, h);
    const [x2, y2] = iso(a + fa * (s + 1.2), b + fb * (s + 1.2), h + 0.8);
    const [x3, y3] = iso(a + fa * (s + 2.4), b + fb * (s + 2.4), h);
    g.moveTo(x1, y1).lineTo(x2, y2).lineTo(x3, y3).stroke({ width: 0.1, color: 0xb8900f });
  }
  g.moveTo(bx2, by2).lineTo(cx, cy).stroke({ width: 0.3, color: Y });
  obox(g, p, ox, oy, a - fa * (counter - 1.5), b - fb * (counter - 1.5), ang, 3, 2.2, h - 1.6, h + 0.6, 0x9a9a94); // counterweight
  g.moveTo(tx, ty).lineTo(jx, jy).moveTo(tx, ty).lineTo(cx, cy).stroke({ width: 0.08, color: 0x3a3a3a });
  obox(g, p, ox, oy, a + fa * 1.6, b + fb * 1.6, ang, 2, 1.8, h - 2.2, h, 0xe9e6dc); // cab
  // trolley, cable and hook
  const hook = h * 0.42;
  const [hx, hy] = iso(a + fa * jib * 0.55, b + fb * jib * 0.55, h);
  const [hx2, hy2] = iso(a + fa * jib * 0.55, b + fb * jib * 0.55, hook);
  g.moveTo(hx, hy).lineTo(hx2, hy2).stroke({ width: 0.07, color: 0x222222 });
  g.rect(hx2 - 0.35, hy2, 0.7, 0.9).fill(0xd8a412);
  g.position.set(ox, oy);
  return g;
}

export function buildProps(data: Diorama, p: Projector, insideBuilding: (a: number, b: number) => boolean): { props: Prop[]; labels: Array<{ text: string; at: [number, number, number] }> } {
  const props: Prop[] = [];
  const labels: Array<{ text: string; at: [number, number, number] }> = [];
  for (const c of bays(data, p, insideBuilding)) {
    const g = car(p, c.a, c.b, c.ang, c.color);
    props.push({ node: g, a: c.a, b: c.b, bounds: boundsOf(g, g.x, g.y) });
  }

  // construction sites
  data.land.forEach((item, si) => {
    if (item.k !== "construction") return;
    const ring = item.ring.map(([lon, lat]) => p.toAB(lon, lat));
    let area = 0;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) area += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    area = Math.abs(area) / 2;
    if (area < 1500) return;
    // fence: chain-link panels on posts along the boundary, in short depth-sorted runs
    for (let i = 0; i < ring.length; i++) {
      const [pa, pb] = ring[i];
      const [qa, qb] = ring[(i + 1) % ring.length];
      const len = Math.hypot(qa - pa, qb - pb);
      const parts = Math.max(1, Math.ceil(len / 10));
      for (let k = 0; k < parts; k++) {
        const sa = pa + ((qa - pa) * k) / parts;
        const sb = pb + ((qb - pb) * k) / parts;
        const ea = pa + ((qa - pa) * (k + 1)) / parts;
        const eb = pb + ((qb - pb) * (k + 1)) / parts;
        if (insideBuilding((sa + ea) / 2, (sb + eb) / 2)) continue;
        const ma = (sa + ea) / 2;
        const mb = (sb + eb) / 2;
        const [ox, oy] = p.iso(ma, mb);
        const g = new Graphics();
        const iso = (a: number, b: number, z: number) => {
          const [x, y] = p.iso(a, b, z);
          return [x - ox, y - oy];
        };
        g.poly([...iso(sa, sb, 0), ...iso(ea, eb, 0), ...iso(ea, eb, 2), ...iso(sa, sb, 2)]).fill({ color: 0x8e979c, alpha: 0.38 });
        g.poly([...iso(sa, sb, 0.05), ...iso(ea, eb, 0.05), ...iso(ea, eb, 0.6), ...iso(sa, sb, 0.6)]).fill({ color: 0x2f5d7c, alpha: 0.55 }); // site banner
        g.moveTo(...(iso(sa, sb, 2) as [number, number])).lineTo(...(iso(ea, eb, 2) as [number, number])).stroke({ width: 0.12, color: 0x5c6468 });
        for (const [a, b] of [[sa, sb], [ea, eb]]) g.moveTo(...(iso(a, b, 0) as [number, number])).lineTo(...(iso(a, b, 2.1) as [number, number])).stroke({ width: 0.14, color: 0x4a5054 });
        g.position.set(ox, oy);
        props.push({ node: g, a: ma, b: mb, bounds: boundsOf(g, ox, oy) });
      }
    }
    // inside: cabins, material piles, cranes on open ground (never inside a finished building)
    let minA = Infinity, maxA = -Infinity, minB = Infinity, maxB = -Infinity;
    for (const [a, b] of ring) {
      minA = Math.min(minA, a); maxA = Math.max(maxA, a); minB = Math.min(minB, b); maxB = Math.max(maxB, b);
    }
    const spots: AB[] = [];
    for (let i = 1; spots.length < 40 && i < 600; i++) {
      const a = minA + (maxA - minA) * hashN(i, 300 + si);
      const b = minB + (maxB - minB) * hashN(i, 400 + si);
      if (!inPoly(ring, a, b) || insideBuilding(a, b) || insideBuilding(a + 6, b) || insideBuilding(a, b + 6) || insideBuilding(a - 6, b) || insideBuilding(a, b - 6)) continue;
      if (spots.some(([sa, sb]) => Math.hypot(sa - a, sb - b) < 14)) continue;
      spots.push([a, b]);
    }
    const cranes = Math.min(3, Math.max(1, Math.round(area / 18000)));
    spots.forEach(([a, b], i) => {
      let g: Graphics;
      if (i < cranes) g = crane(p, a, b, hashN(i, 77 + si) * Math.PI * 2, 38 + hashN(i, 78) * 10);
      else if (i < cranes + 4) {
        const [ox, oy] = p.iso(a, b);
        g = new Graphics();
        const ang = Math.round(hashN(i, 79) * 2) * (Math.PI / 2);
        obox(g, p, ox, oy, a, b, ang, 6, 2.4, 0, 2.6, i % 2 ? 0xe9e6dc : 0x3f6f9a);
        if (i % 3 === 0) obox(g, p, ox, oy, a, b, ang, 6, 2.4, 2.6, 5.2, 0xe9e6dc);
        g.position.set(ox, oy);
      } else if (i < cranes + 12) {
        const [ox, oy] = p.iso(a, b);
        g = new Graphics();
        const ang = hashN(i, 80) * Math.PI;
        const kind = i % 3;
        obox(g, p, ox, oy, a, b, ang, 4 + 2 * hashN(i, 81), 2.2, 0, kind === 0 ? 0.9 : 0.6, kind === 0 ? 0x8c7a5c : kind === 1 ? 0x9a9c9e : 0x6e5136);
        g.position.set(ox, oy);
      } else return;
      props.push({ node: g, a, b, bounds: boundsOf(g, g.x, g.y) });
    });
    const [la, lb] = spots[0] ?? [(minA + maxA) / 2, (minB + maxB) / 2];
    labels.push({ text: "ERC · UNDER CONSTRUCTION", at: [la, lb, 8] });
  });
  return { props, labels };
}

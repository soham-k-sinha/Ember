/**
 * The static stage, drawn once: a white-clay model of the real district (D52). The city is the setting,
 * so it is quiet on purpose: off-white buildings, sage parks, a thin tree layer, strong blue water.
 * The resources and the flood (drawn by IsoView) carry the colour.
 */

import { Container, Graphics, Sprite, type Renderer, type Texture } from "pixi.js";
import type { Diorama, DioBuilding } from "../diorama";
import type { Projector } from "./project";

export const CLAY = {
  bg: 0x0b0e14,
  slabLeft: 0x7a6249,
  slabRight: 0x5f4b37,
  ground: 0xe2ddd3,
  grass: 0xc6d2ad,
  field: 0xb9cc9b,
  park: 0xbfcfa4,
  plaza: 0xebe7df,
  play: 0xe6d9bd,
  water: 0x5d9cc9,
  waterEdge: 0x3f7fb0,
  road: 0xc9c4b9,
  path: 0xeeeae2,
  roof: 0xfbfaf6,
  wallLight: 0xe8e4dc,
  wallDark: 0xd0cabf,
  outline: 0xa29c90,
  tree: [0xa9bb8f, 0x9cb083, 0xb3c49a],
  treeDark: 0x7f9468,
} as const;

const SLAB_DEPTH = 34;

const ROAD_W: Record<string, number> = {
  motorway: 15, trunk: 13, primary: 12, secondary: 10, tertiary: 9, residential: 7, unclassified: 7, living_street: 6, service: 4, unknown: 5,
};
const FOOT = new Set(["footway", "cycleway", "pedestrian", "path", "steps", "track", "bridleway"]);

function landFill(k: string): number | null {
  if (k === "grass" || k === "village_green" || k === "meadow") return CLAY.grass;
  if (k === "pitch" || k === "stadium" || k === "track") return CLAY.field;
  if (k === "park" || k === "recreation_ground" || k === "garden" || k === "protected_landscape_seascape" || k === "dog_park" || k === "cemetery") return CLAY.park;
  if (k === "playground") return CLAY.play;
  if (k === "pedestrian" || k === "plaza" || k === "university" || k === "school" || k === "college") return CLAY.plaza;
  return null;
}

function hash(n: number): number {
  let x = Math.imul(n | 0, 2654435761) >>> 0;
  x = Math.imul(x ^ (x >>> 15), 0x2c1b3c6d) >>> 0;
  return ((x ^ (x >>> 13)) >>> 0) / 4294967296;
}

export type StaticScene = {
  ground: Container; // slab, land, water, roads (below the flood)
  sorted: Container; // buildings + trees, back to front (above the flood and trails)
  slabMask: Graphics; // clip for ground-level dynamic layers
  slabPoly: number[];
};

/** Flat ring → screen polygon at height z. */
function ringPoly(p: Projector, ring: [number, number][], z = 0): number[] {
  const out: number[] = [];
  for (const [lon, lat] of ring) {
    const [x, y] = p.lonlat(lon, lat, z);
    out.push(x, y);
  }
  return out;
}

function treeTexture(renderer: Renderer): Texture {
  const g = new Graphics();
  g.ellipse(0, 9, 9, 4.2).fill({ color: 0x000000, alpha: 0.13 });
  g.rect(-0.9, 2, 1.8, 7).fill(0x8a7258);
  g.circle(0, -2, 8).fill(0xffffff);
  g.circle(-2.4, -4.4, 4.2).fill({ color: 0xffffff, alpha: 0.55 });
  g.circle(2.2, 0.5, 5).fill({ color: 0x000000, alpha: 0.08 });
  return renderer.generateTexture({ target: g, resolution: 3, antialias: true });
}

function building(p: Projector, b: DioBuilding, accent?: number): Graphics {
  const g = new Graphics();
  const top = b.h;
  const ab = b.ring.map(([lon, lat]) => p.toAB(lon, lat));
  // orientation in (a, b): positive area = clockwise on screen
  let area = 0;
  for (let i = 0; i < ab.length; i++) {
    const [a1, b1] = ab[i];
    const [a2, b2] = ab[(i + 1) % ab.length];
    area += a1 * b2 - a2 * b1;
  }
  const sign = area >= 0 ? 1 : -1;
  // walls facing the viewer (outward normal · (1, 1) > 0), far ones first
  const walls: Array<{ d: number; poly: number[]; shade: number }> = [];
  for (let i = 0; i < ab.length; i++) {
    const [a1, b1] = ab[i];
    const [a2, b2] = ab[(i + 1) % ab.length];
    const da = a2 - a1;
    const db = b2 - b1;
    const na = sign * db;
    const nb = -sign * da;
    if (na + nb <= 0) continue;
    const [x1, y1] = p.iso(a1, b1, 0);
    const [x2, y2] = p.iso(a2, b2, 0);
    const [x3, y3] = p.iso(a2, b2, top);
    const [x4, y4] = p.iso(a1, b1, top);
    const len = Math.hypot(na, nb) || 1;
    walls.push({ d: a1 + b1 + a2 + b2, poly: [x1, y1, x2, y2, x3, y3, x4, y4], shade: na / len > nb / len ? CLAY.wallLight : CLAY.wallDark });
  }
  walls.sort((x, y) => x.d - y.d);
  for (const wall of walls) {
    g.poly(wall.poly).fill(accent != null ? mix(accent, wall.shade, 0.35) : wall.shade).stroke({ width: 0.45, color: CLAY.outline, alpha: 0.9 });
  }
  g.poly(ringPoly(p, b.ring, top)).fill(accent != null ? mix(accent, 0xffffff, 0.15) : CLAY.roof).stroke({ width: 0.45, color: CLAY.outline, alpha: 0.9 });
  return g;
}

export function mix(a: number, b: number, t: number): number {
  const ar = (a >> 16) & 255, ag = (a >> 8) & 255, ab = a & 255;
  const br = (b >> 16) & 255, bg = (b >> 8) & 255, bb = b & 255;
  return (Math.round(ar + (br - ar) * t) << 16) | (Math.round(ag + (bg - ag) * t) << 8) | Math.round(ab + (bb - ab) * t);
}

/** Buildings that host a resource (shelter, substation…) get a faint tint so the base reads as a place. */
export type Accent = { lon: number; lat: number; color: number };

export function buildStatic(renderer: Renderer, data: Diorama, p: Projector, accents: Accent[] = []): StaticScene {
  const { a0, a1, b0, b1 } = p.bounds;
  const corners = [p.iso(a0, b0), p.iso(a1, b0), p.iso(a1, b1), p.iso(a0, b1)];
  const slabPoly = corners.flat();

  const ground = new Container();
  const slab = new Graphics();
  // sides: the two faces toward the viewer (a = a1 edge and b = b1 edge)
  const down = (pt: [number, number]): [number, number] => [pt[0], pt[1] + SLAB_DEPTH];
  const [ne, se, sw] = [corners[1], corners[2], corners[3]];
  slab.poly([...ne, ...se, ...down(se), ...down(ne)]).fill(CLAY.slabRight);
  slab.poly([...se, ...sw, ...down(sw), ...down(se)]).fill(CLAY.slabLeft);
  slab.poly(slabPoly).fill(CLAY.ground);
  ground.addChild(slab);

  const land = new Graphics();
  for (const item of data.land) {
    const fill = landFill(item.k);
    if (fill == null) continue;
    land.poly(ringPoly(p, item.ring)).fill(fill);
  }
  ground.addChild(land);

  const water = new Graphics();
  for (const item of data.water) {
    if (!item.ring) continue;
    water.poly(ringPoly(p, item.ring)).fill(CLAY.water);
    for (const hole of item.holes) water.poly(ringPoly(p, hole)).cut();
  }
  ground.addChild(water);

  const roads = new Graphics();
  const draw = (filter: (k: string) => boolean, width: (k: string) => number, color: number, alpha = 1) => {
    const byWidth = new Map<number, typeof data.roads>();
    for (const road of data.roads) {
      if (!filter(road.k)) continue;
      const w = width(road.k);
      byWidth.set(w, [...(byWidth.get(w) ?? []), road]);
    }
    for (const [w, list] of byWidth) {
      for (const road of list) {
        const pts = road.path.map(([lon, lat]) => p.lonlat(lon, lat));
        roads.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) roads.lineTo(pts[i][0], pts[i][1]);
      }
      roads.stroke({ width: w, color, alpha, cap: "round", join: "round" });
    }
  };
  draw((k) => FOOT.has(k) && k !== "steps", () => 1.4, CLAY.path, 0.9);
  draw((k) => !FOOT.has(k), (k) => (ROAD_W[k] ?? 5) * 0.62, CLAY.road);
  ground.addChild(roads);

  const slabMask = new Graphics().poly(slabPoly).fill(0xffffff);

  // buildings and trees, back to front
  const sorted = new Container();
  sorted.sortableChildren = true;
  const near = (b: DioBuilding) => {
    let best: Accent | undefined;
    let dist = 40;
    for (const accent of accents) {
      for (const [lon, lat] of b.ring) {
        const [x1, y1] = p.toAB(lon, lat);
        const [x2, y2] = p.toAB(accent.lon, accent.lat);
        const d = Math.hypot(x1 - x2, y1 - y2);
        if (d < dist) {
          dist = d;
          best = accent;
        }
      }
    }
    return best;
  };
  for (const b of data.buildings) {
    const g = building(p, b, near(b)?.color);
    const ab = b.ring.map(([lon, lat]) => p.toAB(lon, lat));
    g.zIndex = Math.max(...ab.map(([a, bb]) => a + bb));
    sorted.addChild(g);
  }
  const tex = treeTexture(renderer);
  data.trees.forEach((tree, i) => {
    if (hash(i) > 0.45) return; // a thin tree layer: the trees are setting, not subject
    const [a, b] = p.toAB(tree[0], tree[1]);
    if (a < a0 || a > a1 || b < b0 || b > b1) return;
    const [x, y] = p.iso(a, b);
    const s = new Sprite(tex);
    s.anchor.set(0.5, 0.8);
    const r = Math.min(7, Math.max(2.4, tree[3] * 0.75));
    s.scale.set(r / 8);
    s.position.set(x, y);
    s.tint = CLAY.tree[i % 3];
    s.zIndex = a + b + 0.5;
    sorted.addChild(s);
  });
  return { ground, sorted, slabMask, slabPoly };
}

/**
 * Bakes the stage's ground into one top-down image (P px per metre) from the real data: land use,
 * the Charles, roads (asphalt, kerbs, sidewalks, markings) and paths, each filled with a small
 * procedural texture. Building cast shadows and tree shadows go on their own blurred layer, street
 * lamp light pools on another, so the lighting can fade them over the evening. The scene lays these
 * images onto the isometric ground plane with one affine transform (groundMatrix).
 */

import type { Diorama } from "./data";
import { GROUND, hash2, noise, rgba, type RGB } from "./palette";
import type { Projector } from "./project";

export const P = 2; // texture px per metre
export const SHADOW_P = 1; // shadow / light layers px per metre
/** Late-afternoon sun in the west-south-west: shadows fall east-north-east (a = east, b = south). */
export const SUN_SHADOW: [number, number] = [0.95, -0.32];

const T = 40; // tile size in metres (textures repeat every 40 m)

function tile(P: number, paint: (img: ImageData, n: number) => void): HTMLCanvasElement {
  const n = T * P;
  const c = document.createElement("canvas");
  c.width = n;
  c.height = n;
  const ctx = c.getContext("2d")!;
  const img = ctx.createImageData(n, n);
  paint(img, n);
  ctx.putImageData(img, 0, 0);
  return c;
}

const put = (img: ImageData, i: number, r: number, g: number, b: number) => {
  const d = img.data;
  d[i] = r;
  d[i + 1] = g;
  d[i + 2] = b;
  d[i + 3] = 255;
};

function grass(P: number, base0: RGB, base1: RGB, seed: number, stripes = false) {
  return tile(P, (img, n) => {
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const v = 0.45 * noise(x / (P * 2.5), y / (P * 2.5), seed, n / (P * 2.5)) + 0.35 * noise(x / (P * 0.5), y / (P * 0.5), seed + 1, n / (P * 0.5)) + 0.2 * hash2(x, y, seed + 2);
        let t = Math.max(0, Math.min(1, (v - 0.2) / 0.65));
        if (stripes) t = t * 0.6 + (Math.floor(y / (P * 4)) % 2 ? 0.32 : 0.05);
        let r = base0[0] + (base1[0] - base0[0]) * t;
        let g = base0[1] + (base1[1] - base0[1]) * t;
        let b = base0[2] + (base1[2] - base0[2]) * t;
        const blade = hash2(x, y, seed + 3);
        if (blade > 0.93) {
          r *= 1.16;
          g *= 1.15;
        } else if (blade < 0.06) {
          r *= 0.82;
          g *= 0.84;
          b *= 0.86;
        }
        put(img, (y * n + x) * 4, r, g, b);
      }
    }
  });
}

function speckle(P: number, base: RGB, amount: number, seed: number) {
  return tile(P, (img, n) => {
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const v = 0.6 * noise(x / (P * 3), y / (P * 3), seed, n / (P * 3)) + 0.4 * hash2(x, y, seed + 1);
        const k = 1 - amount / 2 + v * amount;
        put(img, (y * n + x) * 4, base[0] * k, base[1] * k, base[2] * k);
      }
    }
  });
}

/** Rectangular units in running bond (slabs, bricks), lit from the upper left. */
function bond(P: number, base: RGB, seam: RGB, wM: number, hM: number, seed: number, toneVar = 0.18) {
  return tile(P, (img, n) => {
    const bw = n / Math.round(n / (wM * P));
    const bh = n / Math.round(n / (hM * P));
    for (let y = 0; y < n; y++) {
      const row = Math.floor(y / bh);
      const off = row % 2 ? bw / 2 : 0;
      for (let x = 0; x < n; x++) {
        const xx = (x + off) % n;
        const col = Math.floor(xx / bw);
        const fx = xx - col * bw;
        const fy = y - row * bh;
        const grain = 0.94 + hash2(x, y, seed + 3) * 0.12;
        const tone = 1 - toneVar / 2 + hash2(col, row, seed) * toneVar;
        const seamPx = Math.max(1, P / 4);
        if (fx < seamPx || fy < seamPx) put(img, (y * n + x) * 4, seam[0] * grain, seam[1] * grain, seam[2] * grain);
        else {
          const lit = fx < seamPx * 2 || fy < seamPx * 2 ? 1.07 : 1;
          const k = tone * grain * lit;
          put(img, (y * n + x) * 4, base[0] * k, base[1] * k, base[2] * k);
        }
      }
    }
  });
}

function water(P: number) {
  return tile(P, (img, n) => {
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const v = 0.6 * noise(x / (P * 5), y / (P * 1.6), 21, n / (P * 5)) + 0.4 * noise(x / (P * 1.2), y / (P * 0.5), 22, n / (P * 1.2));
        const hl = v > 0.7 ? (v - 0.7) * 2.4 : 0;
        const a = GROUND.water;
        put(img, (y * n + x) * 4, a[0] + 34 * hl + (v - 0.5) * 10, a[1] + 46 * hl + (v - 0.5) * 12, a[2] + 48 * hl + (v - 0.5) * 12);
      }
    }
  });
}

export const ROAD_W: Record<string, number> = {
  parking_aisle: 5.5, motorway: 15, trunk: 13, primary: 12, secondary: 10, tertiary: 9, residential: 7.5, unclassified: 7, living_street: 6, service: 4.5, unknown: 5,
};
export const FOOT = new Set(["footway", "cycleway", "pedestrian", "path", "steps", "track", "bridleway"]);
const MARKED = new Set(["motorway", "trunk", "primary", "secondary", "tertiary"]);

export type Lamp = { a: number; b: number };
export type GroundBake = {
  ground: HTMLCanvasElement;
  shadow: HTMLCanvasElement;
  pools: HTMLCanvasElement;
  lamps: Lamp[];
  width: number;
  height: number;
};

export type ShadowShape = Array<[number, number]>; // (a, b) metres
export type TreeSpot = { a: number; b: number; r: number; h: number };

type Textures = Record<"lot" | "yard" | "grass" | "field" | "plaza" | "brick" | "concrete" | "asphalt" | "path" | "play" | "water" | "earth" | "parking", HTMLCanvasElement>;
const TEXTURES = new Map<number, Textures>();

function texturesAt(P: number): Textures {
  let tex = TEXTURES.get(P);
  if (tex) return tex;
  tex = {
    lot: speckle(P, GROUND.lot, 0.18, 5),
    yard: grass(P, GROUND.yard, GROUND.grassLight, 11),
    grass: grass(P, GROUND.grassDark, GROUND.grassLight, 13),
    field: grass(P, GROUND.field, [104, 138, 74], 17, true),
    plaza: bond(P, GROUND.plaza, GROUND.plazaSeam, 1.2, 0.8, 7),
    brick: bond(P, GROUND.brickWalk, [96, 56, 44], 0.4, 0.2, 9, 0.24),
    concrete: bond(P, GROUND.concrete, GROUND.concreteSeam, 1.6, 1.6, 3, 0.1),
    asphalt: speckle(P, GROUND.asphalt, 0.16, 23),
    path: speckle(P, GROUND.path, 0.22, 29),
    play: speckle(P, GROUND.play, 0.2, 31),
    water: water(P),
    earth: speckle(P, GROUND.earth, 0.34, 41),
    parking: speckle(P, GROUND.parking, 0.12, 43),
  };
  TEXTURES.set(P, tex);
  return tex;
}

export type GroundInputs = { data: Diorama; p: Projector; trees: TreeSpot[]; footprints: Array<Array<[number, number]>> };

/**
 * Paint the ground (land use, the Charles, streets, paths, pads, tree contact) for the stage area
 * [ra0, ra0 + W/P] × [rb0, rb0 + H/P] at P px per metre. Patterns are anchored to the stage origin,
 * so tiles painted separately meet without seams.
 */
function paintGround(ctx: CanvasRenderingContext2D, inputs: GroundInputs, P: number, ra0: number, rb0: number, W: number, H: number) {
  const { data, p, trees, footprints } = inputs;
  const { a0, b0 } = p.bounds;
  ctx.save();
  ctx.translate(-(ra0 - a0) * P, -(rb0 - b0) * P);
  const x0 = (ra0 - a0) * P;
  const y0 = (rb0 - b0) * P;
  const U = (lon: number, lat: number): [number, number] => {
    const [a, b] = p.toAB(lon, lat);
    return [(a - a0) * P, (b - b0) * P];
  };
  const ringPath = (c: CanvasRenderingContext2D, ring: [number, number][]) => {
    ring.forEach(([lon, lat], i) => {
      const [x, y] = U(lon, lat);
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    });
    c.closePath();
  };
  const pattern = (c: HTMLCanvasElement) => ctx.createPattern(c, "repeat")!;
  const tex = texturesAt(P);
  // 1) urban ground everywhere (lots, courtyards), then land use on top
  ctx.fillStyle = pattern(tex.lot);
  ctx.fillRect(x0, y0, W, H);
  const fill = (k: string): CanvasPattern | null => {
    if (k === "residential") return pattern(tex.yard);
    if (k === "grass" || k === "village_green" || k === "meadow" || k === "park" || k === "recreation_ground" || k === "garden" || k === "protected_landscape_seascape" || k === "dog_park" || k === "cemetery" || k === "flowerbed" || k === "allotments") return pattern(tex.grass);
    if (k === "pitch" || k === "stadium" || k === "track") return pattern(tex.field);
    if (k === "playground") return pattern(tex.play);
    if (k === "pedestrian" || k === "plaza") return pattern(tex.plaza);
    // campuses are mostly lawn crossed by real paths (drawn on top), not paving
    if (k === "university" || k === "school" || k === "college") return pattern(tex.yard);
    if (k === "construction") return pattern(tex.earth);
    if (k === "parking") return pattern(tex.parking);
    return null;
  };
  const order = ["residential", "university", "school", "college", "park", "recreation_ground", "protected_landscape_seascape", "garden", "grass", "cemetery", "pitch", "stadium", "track", "playground", "construction", "parking", "pedestrian", "plaza", "flowerbed"];
  const land = [...data.land].sort((x, y) => order.indexOf(x.k) - order.indexOf(y.k));
  for (const item of land) {
    const f = fill(item.k);
    if (!f) continue;
    ctx.fillStyle = f;
    ctx.beginPath();
    ringPath(ctx, item.ring);
    ctx.fill();
  }

  // 2) the Charles: water, a soft shallow band along the shore, a stone coping edge
  ctx.save();
  ctx.beginPath();
  for (const item of data.water) {
    if (!item.ring) continue;
    ringPath(ctx, item.ring);
    for (const hole of item.holes) ringPath(ctx, hole);
  }
  ctx.fillStyle = pattern(tex.water);
  ctx.fill("evenodd");
  ctx.clip("evenodd");
  ctx.filter = `blur(${P * 2.5}px)`;
  ctx.strokeStyle = rgba(GROUND.shallow, 0.6);
  ctx.lineWidth = P * 9;
  ctx.stroke();
  ctx.filter = "none";
  ctx.restore();
  ctx.beginPath();
  for (const item of data.water) if (item.ring) ringPath(ctx, item.ring);
  ctx.strokeStyle = "rgba(8,16,20,0.45)";
  ctx.lineWidth = P * 1.6;
  ctx.stroke();
  ctx.strokeStyle = rgba(GROUND.coping);
  ctx.lineWidth = P * 0.8;
  ctx.stroke();

  // 3) streets: sidewalk band, kerb lip, asphalt, then markings
  const roads = data.roads.filter((road) => !FOOT.has(road.k));
  const strokeRoads = (width: (k: string) => number, style: string | CanvasPattern, list = roads, dash?: number[]) => {
    const byW = new Map<number, typeof list>();
    for (const road of list) byW.set(width(road.k), [...(byW.get(width(road.k)) ?? []), road]);
    for (const [w, group] of byW) {
      if (w <= 0) continue;
      ctx.beginPath();
      for (const road of group) {
        road.path.forEach(([lon, lat], i) => {
          const [x, y] = U(lon, lat);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
      }
      ctx.lineWidth = w * P;
      ctx.strokeStyle = style;
      ctx.setLineDash(dash ?? []);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  };
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const aisle = (k: string) => k === "parking_aisle";
  strokeRoads((k) => (aisle(k) ? 0 : (ROAD_W[k] ?? 5) + 5.2), "rgba(10,14,8,0.35)");
  strokeRoads((k) => (aisle(k) ? 0 : (ROAD_W[k] ?? 5) + 4.6), pattern(tex.concrete));
  strokeRoads((k) => (aisle(k) ? 0 : (ROAD_W[k] ?? 5) + 0.7), rgba(GROUND.kerb, 0.95));
  strokeRoads((k) => ROAD_W[k] ?? 5, pattern(tex.asphalt));
  // car-park bays: white lines square to each aisle, both sides, every 2.6 m
  ctx.strokeStyle = "rgba(232,230,220,0.78)";
  ctx.lineWidth = 0.13 * P;
  ctx.lineCap = "butt";
  ctx.beginPath();
  for (const road of roads) {
    if (!aisle(road.k)) continue;
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
        const ca = pa + ua * carry;
        const cb = pb + ub * carry;
        for (const side of [1, -1]) {
          const x0 = (ca - ub * 2.9 * side - a0) * P;
          const y0 = (cb + ua * 2.9 * side - b0) * P;
          const x1 = (ca - ub * 7.6 * side - a0) * P;
          const y1 = (cb + ua * 7.6 * side - b0) * P;
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
        }
      }
      carry -= len;
    }
  }
  ctx.stroke();
  ctx.lineCap = "round";
  ctx.lineCap = "butt";
  strokeRoads((k) => (MARKED.has(k) ? 0.18 : 0), rgba(GROUND.marking, 0.85), roads, [3 * P, 4 * P]);
  ctx.lineCap = "round";

  // 4) footpaths: brick near campus plazas, gravel elsewhere
  const paths = data.roads.filter((road) => FOOT.has(road.k) && road.k !== "steps");
  strokeRoads(() => 2.4, "rgba(10,14,8,0.25)", paths);
  strokeRoads(() => 1.9, pattern(tex.path), paths);

  // 5) building pads + ambient occlusion around every footprint
  ctx.save();
  ctx.filter = `blur(${P * 1.2}px)`;
  ctx.strokeStyle = "rgba(0,0,0,0.32)";
  ctx.lineWidth = P * 2.2;
  ctx.beginPath();
  for (const ring of footprints) {
    ring.forEach(([a, b], i) => (i === 0 ? ctx.moveTo((a - a0) * P, (b - b0) * P) : ctx.lineTo((a - a0) * P, (b - b0) * P)));
    ctx.closePath();
  }
  ctx.stroke();
  ctx.restore();

  // 6) tree contact darkening
  for (const t of trees) {
    const x = (t.a - a0) * P;
    const y = (t.b - b0) * P;
    const g = ctx.createRadialGradient(x, y, 0, x, y, P * t.r * 0.9);
    g.addColorStop(0, "rgba(10,14,8,0.3)");
    g.addColorStop(1, "rgba(10,14,8,0)");
    ctx.fillStyle = g;
    ctx.fillRect(x - P * t.r, y - P * t.r, P * t.r * 2, P * t.r * 2);
  }

  ctx.restore();
}

export function bakeGround(data: Diorama, p: Projector, shadows: ShadowShape[], trees: TreeSpot[], footprints: Array<Array<[number, number]>>): GroundBake {
  const { a0, a1, b0, b1 } = p.bounds;
  const W = Math.ceil((a1 - a0) * P);
  const H = Math.ceil((b1 - b0) * P);
  const ground = document.createElement("canvas");
  ground.width = W;
  ground.height = H;
  paintGround(ground.getContext("2d")!, { data, p, trees, footprints }, P, a0, b0, W, H);
  const roads = data.roads.filter((road) => !FOOT.has(road.k));

  // 7) cast shadows on their own blurred layer
  const SW = Math.ceil((a1 - a0) * SHADOW_P);
  const SH = Math.ceil((b1 - b0) * SHADOW_P);
  const shadow = document.createElement("canvas");
  shadow.width = SW;
  shadow.height = SH;
  paintShadows(shadow.getContext("2d")!, p, shadows, trees, SHADOW_P, a0, b0);

  // 8) street lamps every ~32 m along real roads, alternating sides; warm pools on their own layer
  const lamps: Lamp[] = [];
  for (const road of roads) {
    const w = (ROAD_W[road.k] ?? 5) / 2 + 2.2;
    let carry = 12 + hash2(road.path.length, Math.round(road.path[0][0] * 1e5), 3) * 20;
    let side = 1;
    for (let i = 1; i < road.path.length; i++) {
      const [pa, pb] = p.toAB(road.path[i - 1][0], road.path[i - 1][1]);
      const [qa, qb] = p.toAB(road.path[i][0], road.path[i][1]);
      const len = Math.hypot(qa - pa, qb - pb);
      if (len < 0.01) continue;
      const ua = (qa - pa) / len;
      const ub = (qb - pb) / len;
      while (carry < len) {
        const la = pa + ua * carry - ub * w * side;
        const lb = pb + ub * carry + ua * w * side;
        if (la > a0 + 4 && la < a1 - 4 && lb > b0 + 4 && lb < b1 - 4 && !lamps.some((l) => Math.abs(l.a - la) + Math.abs(l.b - lb) < 14)) lamps.push({ a: la, b: lb });
        side = -side;
        carry += 32;
      }
      carry -= len;
    }
  }
  const pools = document.createElement("canvas");
  pools.width = SW;
  pools.height = SH;
  const pctx = pools.getContext("2d")!;
  pctx.globalCompositeOperation = "lighter";
  for (const l of lamps) {
    const x = (l.a - a0) * SHADOW_P;
    const y = (l.b - b0) * SHADOW_P;
    const r = 9 * SHADOW_P;
    const g = pctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(255,196,120,0.8)");
    g.addColorStop(0.35, "rgba(240,160,90,0.36)");
    g.addColorStop(1, "rgba(200,120,60,0)");
    pctx.fillStyle = g;
    pctx.fillRect(x - r, y - r, r * 2, r * 2);
  }

  return { ground, shadow, pools, lamps, width: W, height: H };
}

/** Cast shadows of buildings and trees for the area starting at (ra0, rb0), at SP px per metre, softly blurred. */
function paintShadows(sctx: CanvasRenderingContext2D, p: Projector, shadows: ShadowShape[], trees: TreeSpot[], SP: number, ra0: number, rb0: number) {
  sctx.filter = `blur(${Math.max(1, SP * 1.4)}px)`;
  sctx.fillStyle = "#000";
  sctx.beginPath();
  for (const poly of shadows) {
    poly.forEach(([a, b], i) => (i === 0 ? sctx.moveTo((a - ra0) * SP, (b - rb0) * SP) : sctx.lineTo((a - ra0) * SP, (b - rb0) * SP)));
    sctx.closePath();
  }
  sctx.fill("nonzero");
  const ang = Math.atan2(SUN_SHADOW[1], SUN_SHADOW[0]);
  for (const t of trees) {
    sctx.beginPath();
    sctx.ellipse((t.a + SUN_SHADOW[0] * t.h * 0.7 - ra0) * SP, (t.b + SUN_SHADOW[1] * t.h * 0.7 - rb0) * SP, t.r * SP * 1.25, t.r * SP * 0.85, ang, 0, Math.PI * 2);
    sctx.fill();
  }
  sctx.filter = "none";
  void p;
}

/** Hi-resolution ground for zoomed-in views: one square tile of the stage, with its own cast-shadow layer. */
export const TILE_M = 128;
export const TILE_P = 8;
export const TILE_SP = 4;
export function bakeTile(inputs: GroundInputs, shadows: ShadowShape[], ra0: number, rb0: number): { ground: HTMLCanvasElement; shadow: HTMLCanvasElement; wM: number; hM: number } {
  const { a1, b1 } = inputs.p.bounds;
  const wM = Math.min(TILE_M, a1 - ra0);
  const hM = Math.min(TILE_M, b1 - rb0);
  const ground = document.createElement("canvas");
  ground.width = Math.ceil(wM * TILE_P);
  ground.height = Math.ceil(hM * TILE_P);
  paintGround(ground.getContext("2d")!, inputs, TILE_P, ra0, rb0, ground.width, ground.height);
  const shadow = document.createElement("canvas");
  shadow.width = Math.ceil(wM * TILE_SP);
  shadow.height = Math.ceil(hM * TILE_SP);
  // only the shadows that can reach this tile
  const near = shadows.filter((poly) => poly.some(([a, b]) => a > ra0 - 80 && a < ra0 + wM + 80 && b > rb0 - 80 && b < rb0 + hM + 80));
  const trees = inputs.trees.filter((t) => t.a > ra0 - 30 && t.a < ra0 + wM + 30 && t.b > rb0 - 30 && t.b < rb0 + hM + 30);
  paintShadows(shadow.getContext("2d")!, inputs.p, near, trees, TILE_SP, ra0, rb0);
  return { ground, shadow, wM, hM };
}

/** Affine (a, b, c, d, tx, ty) mapping a top-down image at `px` per metre onto the iso ground plane. */
export function groundMatrix(p: Projector, px: number, origin?: [number, number]): [number, number, number, number, number, number] {
  const [a0, b0] = origin ?? [p.bounds.a0, p.bounds.b0];
  // screen = ((a − b), (a + b)/2) with a = a0 + u/px, b = b0 + v/px
  return [1 / px, 0.5 / px, -1 / px, 0.5 / px, a0 - b0, (a0 + b0) / 2];
}

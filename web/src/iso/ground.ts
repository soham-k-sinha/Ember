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

function tile(paint: (img: ImageData, n: number) => void): HTMLCanvasElement {
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

function grass(base0: RGB, base1: RGB, seed: number, stripes = false) {
  return tile((img, n) => {
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

function speckle(base: RGB, amount: number, seed: number) {
  return tile((img, n) => {
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
function bond(base: RGB, seam: RGB, wM: number, hM: number, seed: number, toneVar = 0.18) {
  return tile((img, n) => {
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
        if (fx < 1 || fy < 1) put(img, (y * n + x) * 4, seam[0] * grain, seam[1] * grain, seam[2] * grain);
        else {
          const lit = fx < 2 || fy < 2 ? 1.07 : 1;
          const k = tone * grain * lit;
          put(img, (y * n + x) * 4, base[0] * k, base[1] * k, base[2] * k);
        }
      }
    }
  });
}

function water() {
  return tile((img, n) => {
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
  motorway: 15, trunk: 13, primary: 12, secondary: 10, tertiary: 9, residential: 7.5, unclassified: 7, living_street: 6, service: 4.5, unknown: 5,
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

export function bakeGround(data: Diorama, p: Projector, shadows: ShadowShape[], trees: TreeSpot[], footprints: Array<Array<[number, number]>>): GroundBake {
  const { a0, a1, b0, b1 } = p.bounds;
  const W = Math.ceil((a1 - a0) * P);
  const H = Math.ceil((b1 - b0) * P);
  const ground = document.createElement("canvas");
  ground.width = W;
  ground.height = H;
  const ctx = ground.getContext("2d")!;
  const U = (lon: number, lat: number): [number, number] => {
    const [a, b] = p.toAB(lon, lat);
    return [(a - a0) * P, (b - b0) * P];
  };
  const ringPath = (c: CanvasRenderingContext2D, ring: [number, number][], scale = P) => {
    ring.forEach(([lon, lat], i) => {
      const [a, b] = p.toAB(lon, lat);
      const x = (a - a0) * scale;
      const y = (b - b0) * scale;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    });
    c.closePath();
  };
  const pattern = (c: HTMLCanvasElement) => ctx.createPattern(c, "repeat")!;
  const tex = {
    lot: speckle(GROUND.lot, 0.18, 5),
    yard: grass(GROUND.yard, GROUND.grassLight, 11),
    grass: grass(GROUND.grassDark, GROUND.grassLight, 13),
    field: grass(GROUND.field, [104, 138, 74], 17, true),
    plaza: bond(GROUND.plaza, GROUND.plazaSeam, 1.2, 0.8, 7),
    brick: bond(GROUND.brickWalk, [96, 56, 44], 0.4, 0.2, 9, 0.24),
    concrete: bond(GROUND.concrete, GROUND.concreteSeam, 1.6, 1.6, 3, 0.1),
    asphalt: speckle(GROUND.asphalt, 0.16, 23),
    path: speckle(GROUND.path, 0.22, 29),
    play: speckle(GROUND.play, 0.2, 31),
    water: water(),
  };

  // 1) urban ground everywhere (lots, courtyards), then land use on top
  ctx.fillStyle = pattern(tex.lot);
  ctx.fillRect(0, 0, W, H);
  const fill = (k: string): CanvasPattern | null => {
    if (k === "residential") return pattern(tex.yard);
    if (k === "grass" || k === "village_green" || k === "meadow" || k === "park" || k === "recreation_ground" || k === "garden" || k === "protected_landscape_seascape" || k === "dog_park" || k === "cemetery" || k === "flowerbed" || k === "allotments") return pattern(tex.grass);
    if (k === "pitch" || k === "stadium" || k === "track") return pattern(tex.field);
    if (k === "playground") return pattern(tex.play);
    if (k === "pedestrian" || k === "plaza") return pattern(tex.plaza);
    if (k === "university" || k === "school" || k === "college") return pattern(tex.plaza);
    return null;
  };
  const order = ["residential", "university", "school", "college", "park", "recreation_ground", "protected_landscape_seascape", "garden", "grass", "cemetery", "pitch", "stadium", "track", "playground", "pedestrian", "plaza", "flowerbed"];
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
  strokeRoads((k) => (ROAD_W[k] ?? 5) + 5.2, "rgba(10,14,8,0.35)");
  strokeRoads((k) => (ROAD_W[k] ?? 5) + 4.6, pattern(tex.concrete));
  strokeRoads((k) => (ROAD_W[k] ?? 5) + 0.7, rgba(GROUND.kerb, 0.95));
  strokeRoads((k) => ROAD_W[k] ?? 5, pattern(tex.asphalt));
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

  // 7) cast shadows on their own blurred layer
  const SW = Math.ceil((a1 - a0) * SHADOW_P);
  const SH = Math.ceil((b1 - b0) * SHADOW_P);
  const shadow = document.createElement("canvas");
  shadow.width = SW;
  shadow.height = SH;
  const sctx = shadow.getContext("2d")!;
  sctx.filter = `blur(${Math.max(1, SHADOW_P * 1.4)}px)`;
  sctx.fillStyle = "#000";
  sctx.beginPath();
  for (const poly of shadows) {
    poly.forEach(([a, b], i) => (i === 0 ? sctx.moveTo((a - a0) * SHADOW_P, (b - b0) * SHADOW_P) : sctx.lineTo((a - a0) * SHADOW_P, (b - b0) * SHADOW_P)));
    sctx.closePath();
  }
  sctx.fill("nonzero");
  for (const t of trees) {
    sctx.beginPath();
    const ang = Math.atan2(SUN_SHADOW[1], SUN_SHADOW[0]);
    sctx.ellipse((t.a + SUN_SHADOW[0] * t.h * 0.7 - a0) * SHADOW_P, (t.b + SUN_SHADOW[1] * t.h * 0.7 - b0) * SHADOW_P, t.r * SHADOW_P * 1.25, t.r * SHADOW_P * 0.85, ang, 0, Math.PI * 2);
    sctx.fill();
  }
  sctx.filter = "none";

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

  for (const c of Object.values(tex)) {
    c.width = 0;
    c.height = 0;
  }
  return { ground, shadow, pools, lamps, width: W, height: H };
}

/** Affine (a, b, c, d, tx, ty) mapping a top-down image at `px` per metre onto the iso ground plane. */
export function groundMatrix(p: Projector, px: number): [number, number, number, number, number, number] {
  const { a0, b0 } = p.bounds;
  // screen = ((a − b), (a + b)/2) with a = a0 + u/px, b = b0 + v/px
  return [1 / px, 0.5 / px, -1 / px, 0.5 / px, a0 - b0, (a0 + b0) / 2];
}

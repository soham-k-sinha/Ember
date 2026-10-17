/**
 * The diorama (D52): the real district as a clean, toy-model 3D scene, in the style of the MHacks
 * Physical Realities park but built from measured data (engine `ember diorama` → public/diorama/*.json).
 *
 * Geometry is real (city footprints + heights, roof type, LiDAR tree crowns, land use, the Charles,
 * paths). Appearance is rules + a researched palette (synthetic, labelled): wall colour by use and
 * neighbourhood, brick for HBS / the river houses, siding colours for Allston and Cambridgeport
 * houses, and hand-styled landmarks.
 */

import { PathLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { AmbientLight, DirectionalLight, LightingEffect, type Layer } from "@deck.gl/core";

export type DioBuilding = {
  ring: [number, number][];
  h: number;
  eave?: number;
  roof: "flat" | "pitched" | "hybrid";
  tone?: number;
  use: string;
  name?: string;
  src: string;
};

export type Diorama = {
  version: string;
  bbox: [number, number, number, number];
  origin: [number, number];
  attribution: string;
  buildings: DioBuilding[];
  trees: [number, number, number, number, number][];
  land: { ring: [number, number][]; k: string; sub?: string }[];
  water: { ring: [number, number][]; holes: [number, number][][] }[];
  roads: { path: [number, number][]; k: string }[];
};

type RGB = [number, number, number];

let pending: Promise<Diorama | null> | null = null;
export function loadDiorama(name = "test"): Promise<Diorama | null> {
  if (!pending) {
    pending = fetch(`${import.meta.env.BASE_URL}diorama/${name}.json`)
      .then((response) => (response.ok ? (response.json() as Promise<Diorama>) : null))
      .catch(() => null);
  }
  return pending;
}

// ---------- palette (research catalogue; hex → rgb) ----------
const hex = (value: string): RGB => [parseInt(value.slice(1, 3), 16), parseInt(value.slice(3, 5), 16), parseInt(value.slice(5, 7), 16)];
const P = {
  brick: ["#9C3D2C", "#8A3528", "#A84B36"].map(hex),
  siding: ["#ECEAE3", "#E8D8A4", "#B7BBB6", "#9CAD8E", "#7E92A5", "#C8B699", "#E6DCC3", "#8E9C88"].map(hex),
  sidingAccent: ["#8C3B32", "#7E3A33", "#3E4E66"].map(hex),
  modern: ["#C9CDD1", "#B9BEC2", "#D9D3C4", "#CBBFA8"].map(hex),
  concrete: ["#BDB5A6", "#A7A39A"].map(hex),
  shingle: hex("#4A4B4E"),
  slate: hex("#4D5359"),
  membrane: hex("#7B7E80"),
  glassRoof: hex("#6F8A96"),
  ground: hex("#BDB6A6"),
  slabTop: hex("#A9A08E"),
  slabSide: hex("#5E4632"),
  grass: hex("#86AE5A"),
  lawn: hex("#7FA653"),
  field: hex("#6A9F46"),
  park: hex("#78A24E"),
  play: hex("#D8C49A"),
  plaza: hex("#D7CFBF"),
  yard: hex("#A7B48C"),
  water: hex("#4E7C8C"),
  asphalt: hex("#54565B"),
  sidewalk: hex("#D2CCBE"),
  path: hex("#DCCFAE"),
  trunk: hex("#6B4F36"),
  trees: ["#3F6B35", "#557F3E", "#6E9A4A", "#4C7A3A"].map(hex),
};

// Landmarks by name (Overture / OSM names): wall, roof colours from the research catalogue.
const LANDMARKS: Array<{ match: RegExp; wall: RGB; roof?: RGB; label?: string }> = [
  { match: /treehouse/i, wall: hex("#D6B07A"), roof: hex("#8FA36B"), label: "RUBENSTEIN TREEHOUSE" },
  { match: /science and engineering/i, wall: hex("#C9CDD1"), roof: hex("#7E9F5A"), label: "SCIENCE & ENGINEERING COMPLEX" },
  { match: /atlas hotel/i, wall: hex("#C6AE88"), roof: hex("#6F90A8"), label: "ATLAS HOTEL" },
  { match: /verra/i, wall: hex("#3F8F6E"), label: "VERRA" },
  { match: /milestone/i, wall: hex("#A8653F") },
  { match: /district energy/i, wall: hex("#B9BEC2") },
  { match: /baker library/i, wall: hex("#9C3D2C"), roof: hex("#4D5359"), label: "BAKER LIBRARY" },
  { match: /1959 chapel/i, wall: hex("#6FA58C"), roof: hex("#6FA58C") },
  { match: /klarman/i, wall: hex("#9C3D2C"), roof: hex("#7B7E80"), label: "KLARMAN HALL" },
  { match: /tata hall/i, wall: hex("#D9D3C4") },
  { match: /innovation lab|batten/i, wall: hex("#D8DADB"), label: "HARVARD i-LAB" },
  { match: /newell/i, wall: hex("#8E4A3E"), roof: hex("#5F7A68"), label: "NEWELL BOATHOUSE" },
  { match: /weld boat/i, wall: hex("#E3D6BC"), roof: hex("#A65A3A"), label: "WELD BOATHOUSE" },
  { match: /dunster/i, wall: hex("#9C3D2C"), roof: hex("#4D5359"), label: "DUNSTER HOUSE" },
  { match: /mather house tower/i, wall: hex("#A7A39A"), label: "MATHER TOWER" },
  { match: /mather/i, wall: hex("#A7A39A") },
  { match: /leverett .*tower/i, wall: hex("#D9D3C4") },
  { match: /peabody terrace/i, wall: hex("#A9A59C"), label: "PEABODY TERRACE" },
  { match: /soldiers field park/i, wall: hex("#9A5A44") },
  { match: /one western/i, wall: hex("#B9B3A8") },
  { match: /stadium/i, wall: hex("#BDB5A6"), label: "HARVARD STADIUM" },
  { match: /doubletree/i, wall: hex("#C8B699") },
];

function hash(n: number, salt = 0): number {
  let x = (Math.imul(n | 0, 2654435761) ^ (salt * 40503)) >>> 0;
  x = Math.imul(x ^ (x >>> 15), 0x2c1b3c6d) >>> 0;
  x = Math.imul(x ^ (x >>> 12), 0x297a2d39) >>> 0;
  return ((x ^ (x >>> 15)) >>> 0) / 4294967296;
}

const shade = (c: RGB, k: number): RGB => [Math.round(c[0] * k), Math.round(c[1] * k), Math.round(c[2] * k)];

type Styled = DioBuilding & { id: number; wall: RGB; roofColor: RGB; label?: string; cambridge: boolean };

function style(b: DioBuilding, id: number): Styled {
  const lm = b.name ? LANDMARKS.find((item) => item.match.test(b.name!)) : undefined;
  const cambridge = b.src.startsWith("cambridge");
  const area = footprintArea(b.ring);
  let wall: RGB;
  if (lm) wall = lm.wall;
  else if (b.use === "education" && !cambridge) wall = P.brick[id % 3]; // HBS neo-Georgian brick
  else if (b.use === "education") wall = P.brick[id % 3];
  else if ((b.use === "residential" || b.use === "other") && b.roof === "pitched" && area < 450) {
    wall = hash(id, 3) < 0.12 ? P.sidingAccent[id % 3] : P.siding[Math.floor(hash(id, 5) * P.siding.length)]; // wood houses
  } else if (b.h > 30) wall = P.concrete[id % 2];
  else if (b.use === "commercial" || b.use === "industrial") wall = P.modern[id % 4];
  else if (cambridge && area < 900) wall = hash(id, 7) < 0.5 ? P.brick[id % 3] : P.siding[Math.floor(hash(id, 9) * P.siding.length)];
  else wall = hash(id, 11) < 0.55 ? P.brick[id % 3] : P.modern[id % 4];
  const roofColor = lm?.roof ?? (b.roof === "pitched" ? (wall === P.brick[0] || wall === P.brick[1] || wall === P.brick[2] ? P.slate : P.shingle)
    : b.tone != null ? shade(P.membrane, 0.75 + (b.tone / 100) * 0.6) : P.membrane);
  return { ...b, id, wall, roofColor, label: lm?.label, cambridge };
}

// ---------- local metres around the diorama origin ----------
function toLocal(origin: [number, number]) {
  const kx = 111_320 * Math.cos((origin[1] * Math.PI) / 180);
  const ky = 110_540;
  return (p: [number, number]): [number, number] => [(p[0] - origin[0]) * kx, (p[1] - origin[1]) * ky];
}

function footprintArea(ring: [number, number][]): number {
  const kx = 111_320 * Math.cos((42.36 * Math.PI) / 180);
  let a = 0;
  for (let i = 0; i < ring.length; i++) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    a += x1 * kx * y2 * 110_540 - x2 * kx * y1 * 110_540;
  }
  return Math.abs(a / 2);
}

/** Hip / gable roofs for pitched buildings, as one flat-shaded mesh (one draw call for all roofs). */
function roofMesh(buildings: Styled[], origin: [number, number]) {
  const local = toLocal(origin);
  const pos: number[] = [];
  const nor: number[] = [];
  const col: number[] = [];
  const tri = (a: number[], b: number[], c: number[], color: RGB) => {
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
    const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    if (nz < 0) {
      [b, c] = [c, b];
      nx = -nx; ny = -ny; nz = -nz;
    }
    const len = Math.hypot(nx, ny, nz) || 1;
    for (const p of [a, b, c]) {
      pos.push(p[0], p[1], p[2]);
      nor.push(nx / len, ny / len, nz / len);
      col.push(color[0] / 255, color[1] / 255, color[2] / 255);
    }
  };
  for (const b of buildings) {
    if (b.roof !== "pitched") continue;
    const pts = b.ring.map(local);
    const n = pts.length;
    if (n < 3) continue;
    // principal axis of the footprint → ridge direction
    let cx = 0, cy = 0;
    for (const [x, y] of pts) { cx += x; cy += y; }
    cx /= n; cy /= n;
    let sxx = 0, syy = 0, sxy = 0;
    for (const [x, y] of pts) { sxx += (x - cx) ** 2; syy += (y - cy) ** 2; sxy += (x - cx) * (y - cy); }
    const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy);
    const ca = Math.cos(ang), sa = Math.sin(ang);
    const uv = pts.map(([x, y]) => [(x - cx) * ca + (y - cy) * sa, -(x - cx) * sa + (y - cy) * ca]);
    const umin = Math.min(...uv.map((p) => p[0])), umax = Math.max(...uv.map((p) => p[0]));
    const vmin = Math.min(...uv.map((p) => p[1])), vmax = Math.max(...uv.map((p) => p[1]));
    const half = (vmax - vmin) / 2;
    const vc = (vmax + vmin) / 2;
    const eave = b.eave ?? b.h * 0.78;
    const ridge = Math.max(eave + 1, Math.min(b.h, eave + half * 0.9));
    const top = uv.map(([u]) => {
      const uu = Math.min(Math.max(u, umin + half), umax - half);
      const ru = umin + half > umax - half ? (umin + umax) / 2 : uu;
      return [cx + ru * ca - vc * sa, cy + ru * sa + vc * ca, ridge];
    });
    const color = b.roofColor;
    const dark = shade(color, 0.86);
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n;
      const a = [pts[i][0], pts[i][1], eave];
      const bb = [pts[j][0], pts[j][1], eave];
      const side = i % 2 ? color : dark;
      tri(a, bb, top[j], side);
      tri(a, top[j], top[i], side);
    }
  }
  return {
    positions: { value: new Float32Array(pos), size: 3 },
    normals: { value: new Float32Array(nor), size: 3 },
    colors: { value: new Float32Array(col), size: 3 },
  };
}

/** Window panels just outside each wall (no textures: deck's mesh texture would replace the wall colour). */
function windowMesh(buildings: Styled[], origin: [number, number]) {
  const local = toLocal(origin);
  const pos: number[] = [];
  const nor: number[] = [];
  const col: number[] = [];
  const quad = (ax: number, ay: number, bx: number, by: number, z0: number, z1: number, nx: number, ny: number, c: RGB) => {
    const v = [[ax, ay, z0], [bx, by, z0], [bx, by, z1], [ax, ay, z0], [bx, by, z1], [ax, ay, z1]];
    for (const p of v) {
      pos.push(p[0], p[1], p[2]);
      nor.push(nx, ny, 0);
      col.push(c[0] / 255, c[1] / 255, c[2] / 255);
    }
  };
  const GLASS: RGB = [62, 78, 96];
  const RIBBON: RGB = [104, 136, 156];
  const TRIM: RGB = [236, 232, 222];
  for (const b of buildings) {
    const top = b.roof === "pitched" ? b.eave ?? b.h * 0.78 : b.h;
    const floors = Math.floor((top - 0.6) / 3.3);
    if (floors < 1) continue;
    let pts = b.ring.map(local);
    // counter-clockwise so (dy, -dx) points outward
    let area = 0;
    for (let i = 0; i < pts.length; i++) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[(i + 1) % pts.length];
      area += x1 * y2 - x2 * y1;
    }
    if (area < 0) pts = [...pts].reverse();
    const ribbon = b.h > 14 && (b.use === "commercial" || b.use === "industrial" || b.wall === P.modern[0] || b.wall === P.modern[1] || b.wall === P.modern[2] || b.wall === P.modern[3] || b.wall === P.concrete[0] || b.wall === P.concrete[1]);
    const brick = P.brick.includes(b.wall);
    for (let i = 0; i < pts.length; i++) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[(i + 1) % pts.length];
      const dx = x2 - x1, dy = y2 - y1;
      const L = Math.hypot(dx, dy);
      if (L < 3.2) continue;
      const ux = dx / L, uy = dy / L;
      const nx = uy, ny = -ux;
      const off = 0.45;
      for (let f = 0; f < floors; f++) {
        const z0 = f * 3.3 + 1.0;
        const z1 = z0 + (ribbon ? 1.7 : 1.45);
        if (ribbon) {
          const a = 0.5, bnd = L - 0.5;
          quad(x1 + ux * a + nx * off, y1 + uy * a + ny * off, x1 + ux * bnd + nx * off, y1 + uy * bnd + ny * off, z0, z1, nx, ny, RIBBON);
          continue;
        }
        const spacing = brick ? 2.7 : 3.1;
        const k = Math.max(1, Math.floor((L - 1.2) / spacing));
        const start = (L - (k - 1) * spacing) / 2;
        for (let w = 0; w < k; w++) {
          const c = start + w * spacing;
          const half = 0.55;
          if (brick) quad(x1 + ux * (c - half - 0.12) + nx * off * 0.5, y1 + uy * (c - half - 0.12) + ny * off * 0.5, x1 + ux * (c + half + 0.12) + nx * off * 0.5, y1 + uy * (c + half + 0.12) + ny * off * 0.5, z0 - 0.12, z1 + 0.12, nx, ny, TRIM);
          quad(x1 + ux * (c - half) + nx * off, y1 + uy * (c - half) + ny * off, x1 + ux * (c + half) + nx * off, y1 + uy * (c + half) + ny * off, z0, z1, nx, ny, GLASS);
        }
      }
    }
  }
  return {
    positions: { value: new Float32Array(pos), size: 3 },
    normals: { value: new Float32Array(nor), size: 3 },
    colors: { value: new Float32Array(col), size: 3 },
  };
}

/** Low-poly crown (icosahedron, flat shaded) and a hexagonal trunk, unit size. */
function icosahedron() {
  const t = (1 + Math.sqrt(5)) / 2;
  const v = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]
    .map(([x, y, z]) => { const l = Math.hypot(x, y, z); return [x / l, z / l, y / l]; });
  const f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  const pos: number[] = [], nor: number[] = [];
  for (const [a, b, c] of f) {
    const [p, q, r] = [v[a], v[b], v[c]];
    const n = [(p[0] + q[0] + r[0]) / 3, (p[1] + q[1] + r[1]) / 3, (p[2] + q[2] + r[2]) / 3];
    const l = Math.hypot(n[0], n[1], n[2]);
    for (const x of [p, q, r]) { pos.push(...x); nor.push(n[0] / l, n[1] / l, n[2] / l); }
  }
  return { positions: { value: new Float32Array(pos), size: 3 }, normals: { value: new Float32Array(nor), size: 3 } };
}

function prism(sides: number) {
  const pos: number[] = [], nor: number[] = [];
  for (let i = 0; i < sides; i++) {
    const a0 = (i / sides) * Math.PI * 2, a1 = ((i + 1) / sides) * Math.PI * 2;
    const [x0, y0, x1, y1] = [Math.cos(a0), Math.sin(a0), Math.cos(a1), Math.sin(a1)];
    const nx = Math.cos((a0 + a1) / 2), ny = Math.sin((a0 + a1) / 2);
    for (const p of [[x0, y0, 0], [x1, y1, 0], [x1, y1, 1], [x0, y0, 0], [x1, y1, 1], [x0, y0, 1]]) { pos.push(...p); nor.push(nx, ny, 0); }
  }
  return { positions: { value: new Float32Array(pos), size: 3 }, normals: { value: new Float32Array(nor), size: 3 } };
}

const SHADOWS = !(import.meta.env.DEV && new URLSearchParams(location.search).has("noshadow"));
const CROWN = icosahedron();
const TRUNK = prism(6);

const ROAD_WIDTH: Record<string, number> = {
  motorway: 15, trunk: 13, primary: 12, secondary: 10, tertiary: 9, residential: 7.5, unclassified: 7, living_street: 6,
  service: 4.5, unknown: 5, footway: 1.8, cycleway: 2.2, pedestrian: 3, path: 1.8, steps: 1.6, track: 2.5, bridleway: 1.6,
};
const FOOT = new Set(["footway", "cycleway", "pedestrian", "path", "steps", "track", "bridleway"]);

function landColor(k: string): RGB | null {
  if (k === "grass" || k === "village_green" || k === "meadow") return P.grass;
  if (k === "pitch" || k === "stadium" || k === "track") return P.field;
  if (k === "park" || k === "recreation_ground" || k === "garden" || k === "protected_landscape_seascape" || k === "dog_park") return P.park;
  if (k === "playground") return P.play;
  if (k === "pedestrian" || k === "plaza") return P.plaza;
  if (k === "university" || k === "school" || k === "college") return P.plaza;
  if (k === "residential") return P.yard;
  if (k === "flowerbed" || k === "allotments") return hex("#8FB45E");
  if (k === "cemetery") return hex("#7D9C5A");
  return null;
}

export type DioramaScene = { layers: Layer[]; labels: Layer; effects: LightingEffect[]; bbox: [number, number, number, number] };

let sceneCache: { data: Diorama; scene: DioramaScene } | null = null;

/** Static scene layers (built once per diorama). Ground layers draw in order without fighting over depth. */
export function dioramaScene(data: Diorama): DioramaScene {
  if (sceneCache && sceneCache.data === data) return sceneCache.scene;
  const [w, s, e, n] = data.bbox;
  const slab: [number, number][] = [[w, s], [e, s], [e, n], [w, n]];
  const buildings = data.buildings.map(style);
  const flat = { depthWriteEnabled: false } as const;
  const SLAB_DEPTH = 45;

  const layers: Layer[] = [
    new SolidPolygonLayer({
      id: "dio-slab",
      data: [slab],
      getPolygon: (ring: [number, number][]) => ring,
      extruded: true,
      getElevation: SLAB_DEPTH,
      getFillColor: P.slabSide,
      modelMatrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -SLAB_DEPTH - 0.05, 1],
      material: { ambient: 0.55, diffuse: 0.6, shininess: 8, specularColor: [30, 30, 30] },
    }),
    new SolidPolygonLayer({ id: "dio-ground", data: [slab], getPolygon: (ring: [number, number][]) => ring, getFillColor: P.ground, parameters: flat }),
    new SolidPolygonLayer({
      id: "dio-land",
      data: data.land.filter((item) => landColor(item.k)),
      getPolygon: (item) => item.ring,
      getFillColor: (item) => landColor(item.k) ?? P.ground,
      parameters: flat,
    }),
    new SolidPolygonLayer({
      id: "dio-water",
      data: data.water.filter((item) => item.ring),
      getPolygon: (item) => [item.ring, ...item.holes],
      getFillColor: P.water,
      parameters: flat,
    }),
    new PathLayer({
      id: "dio-sidewalks",
      data: data.roads.filter((road) => !FOOT.has(road.k)),
      getPath: (road) => road.path,
      getWidth: (road) => (ROAD_WIDTH[road.k] ?? 6) + 3.5,
      widthUnits: "meters",
      getColor: P.sidewalk,
      capRounded: true,
      jointRounded: true,
      parameters: flat,
    }),
    new PathLayer({
      id: "dio-paths",
      data: data.roads.filter((road) => FOOT.has(road.k)),
      getPath: (road) => road.path,
      getWidth: (road) => ROAD_WIDTH[road.k] ?? 2.2,
      widthUnits: "meters",
      getColor: P.path,
      capRounded: true,
      jointRounded: true,
      parameters: flat,
    }),
    new PathLayer({
      id: "dio-roads",
      data: data.roads.filter((road) => !FOOT.has(road.k)),
      getPath: (road) => road.path,
      getWidth: (road) => ROAD_WIDTH[road.k] ?? 6,
      widthUnits: "meters",
      getColor: P.asphalt,
      capRounded: true,
      jointRounded: true,
      parameters: flat,
    }),
    new SolidPolygonLayer<Styled>({
      id: "dio-walls",
      data: buildings,
      getPolygon: (b) => b.ring,
      extruded: true,
      wireframe: true,
      getElevation: (b) => (b.roof === "pitched" ? b.eave ?? b.h * 0.78 : b.h),
      getFillColor: (b) => b.wall,
      getLineColor: (b) => [...shade(b.wall, 0.55), 255] as [number, number, number, number],
      material: { ambient: 0.5, diffuse: 0.65, shininess: 12, specularColor: [40, 40, 40] },
      pickable: true,
    }),
    new SolidPolygonLayer<Styled>({
      id: "dio-flat-roofs",
      data: buildings.filter((b) => b.roof !== "pitched"),
      getPolygon: (b) => b.ring.map(([x, y]) => [x, y, b.h + 0.08] as [number, number, number]),
      getFillColor: (b) => b.roofColor,
      material: { ambient: 0.6, diffuse: 0.5, shininess: 6, specularColor: [20, 20, 20] },
    }),
    new SimpleMeshLayer({
      id: "dio-pitched-roofs",
      data: [0],
      mesh: roofMesh(buildings, data.origin),
      getPosition: () => [data.origin[0], data.origin[1], 0],
      getColor: [255, 255, 255],
      material: { ambient: 0.55, diffuse: 0.6, shininess: 10, specularColor: [30, 30, 30] },
    }),
    new SimpleMeshLayer({
      id: "dio-windows",
      data: [0],
      mesh: windowMesh(buildings, data.origin),
      getPosition: () => [data.origin[0], data.origin[1], 0],
      getColor: [255, 255, 255],
      material: { ambient: 0.7, diffuse: 0.4, shininess: 40, specularColor: [90, 100, 110] },
    }),
    new SimpleMeshLayer({
      id: "dio-trunks",
      data: data.trees,
      mesh: TRUNK,
      getPosition: (tree) => [tree[0], tree[1], 0],
      getScale: (tree) => [0.22 + tree[3] * 0.03, 0.22 + tree[3] * 0.03, Math.max(1.5, tree[2] * 0.4)],
      getColor: P.trunk,
    }),
    new SimpleMeshLayer({
      id: "dio-crowns",
      data: data.trees,
      mesh: CROWN,
      getPosition: (tree) => [tree[0], tree[1], Math.max(1.5, tree[2] * 0.4) + tree[3] * 0.55],
      getScale: (tree) => [tree[3], tree[3], Math.max(tree[3] * 0.8, (tree[2] * 0.6) / 2)],
      getColor: (tree) => P.trees[Math.floor(hash(Math.round(tree[0] * 1e6), Math.round(tree[1] * 1e6)) * P.trees.length) % P.trees.length],
      material: { ambient: 0.55, diffuse: 0.65, shininess: 4, specularColor: [10, 20, 10] },
    }),
  ];

  const labelled = buildings.filter((b) => b.label);
  const seen = new Set<string>();
  const labels = new TextLayer<Styled>({
    id: "dio-labels",
    data: labelled.filter((b) => (seen.has(b.label!) ? false : (seen.add(b.label!), true))),
    getPosition: (b) => {
      const c = b.ring.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
      return [c[0] / b.ring.length, c[1] / b.ring.length, b.h + 6];
    },
    getText: (b) => b.label!,
    getSize: 12,
    getColor: [240, 236, 228, 255],
    fontFamily: "Inter, system-ui, sans-serif",
    fontWeight: 700,
    fontSettings: { sdf: true },
    outlineWidth: 0,
    background: true,
    getBackgroundColor: [22, 24, 30, 225],
    backgroundPadding: [7, 4],
    getTextAnchor: "middle",
    getAlignmentBaseline: "bottom",
    characterSet: "auto",
    billboard: true,
    parameters: { depthCompare: "always", depthWriteEnabled: false },
  });

  const effects = [
    new LightingEffect({
      ambient: new AmbientLight({ color: [255, 250, 240], intensity: 0.95 }),
      sun: new DirectionalLight({ color: [255, 244, 225], intensity: 0.7, direction: [0.55, 1.0, -1.3], _shadow: SHADOWS }),
      fill: new DirectionalLight({ color: [200, 215, 255], intensity: 0.22, direction: [-1, -0.4, -0.6] }),
    }),
  ];
  (effects[0] as unknown as { shadowColor: number[] }).shadowColor = [0.1, 0.12, 0.2, 0.32];

  const scene = { layers, labels, effects, bbox: data.bbox };
  sceneCache = { data, scene };
  return scene;
}

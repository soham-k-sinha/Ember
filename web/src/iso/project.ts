/**
 * Isometric projection for the PixiJS stage (2:1 dimetric, the Physical Realities projection).
 * World: metres around the stage centre, a = east, b = south. Screen: px = (a − b)·S, py = (a + b)·S/2 − z·S·KZ.
 * North therefore points up-right; depth (what is nearer the viewer) grows with a + b.
 */

export const S = 1; // screen px per metre at zoom 1 (the camera scales the world container)
export const KZ = 1.22; // screen px per vertical metre (2:1 dimetric with a slightly tall z, which reads better)

export type Projector = {
  origin: [number, number];
  toAB: (lon: number, lat: number) => [number, number];
  iso: (a: number, b: number, z?: number) => [number, number];
  lonlat: (lon: number, lat: number, z?: number) => [number, number];
  depth: (lon: number, lat: number) => number;
  /** stage rectangle in (a, b) */
  bounds: { a0: number; a1: number; b0: number; b1: number };
  inside: (lon: number, lat: number, margin?: number) => boolean;
};

export function projector(bbox: [number, number, number, number]): Projector {
  const [w, s, e, n] = bbox;
  const origin: [number, number] = [(w + e) / 2, (s + n) / 2];
  const kx = 111_320 * Math.cos((origin[1] * Math.PI) / 180);
  const ky = 110_540;
  const toAB = (lon: number, lat: number): [number, number] => [(lon - origin[0]) * kx, -(lat - origin[1]) * ky];
  const iso = (a: number, b: number, z = 0): [number, number] => [(a - b) * S, (a + b) * S * 0.5 - z * S * KZ];
  const [a0, b1] = toAB(w, s);
  const [a1, b0] = toAB(e, n);
  return {
    origin,
    toAB,
    iso,
    lonlat: (lon, lat, z = 0) => {
      const [a, b] = toAB(lon, lat);
      return iso(a, b, z);
    },
    depth: (lon, lat) => {
      const [a, b] = toAB(lon, lat);
      return a + b;
    },
    bounds: { a0, a1, b0, b1 },
    inside: (lon, lat, margin = 0) => {
      const [a, b] = toAB(lon, lat);
      return a >= a0 - margin && a <= a1 + margin && b >= b0 - margin && b <= b1 + margin;
    },
  };
}

/** Where the line from the stage centre toward (a, b) leaves the stage rectangle (for off-stage edge tiles). */
export function edgePoint(p: Projector, a: number, b: number, inset = 0): [number, number] {
  const { a0, a1, b0, b1 } = p.bounds;
  const ca = (a0 + a1) / 2;
  const cb = (b0 + b1) / 2;
  const da = a - ca;
  const db = b - cb;
  const ta = da > 0 ? (a1 - inset - ca) / da : da < 0 ? (a0 + inset - ca) / da : Infinity;
  const tb = db > 0 ? (b1 - inset - cb) / db : db < 0 ? (b0 + inset - cb) / db : Infinity;
  const t = Math.min(ta, tb, 1);
  return [ca + da * t, cb + db * t];
}

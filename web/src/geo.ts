import type { LngLat } from "./types";
import type { MultiPolygon, Polygon } from "geojson";

type Ring = LngLat[];
type PolygonRings = Ring[];

function pointInRing(lon: number, lat: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const denom = yj - yi || 1e-15;
    const crosses = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / denom + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

function orient(a: LngLat, b: LngLat, c: LngLat): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function onSegment(a: LngLat, b: LngLat, c: LngLat): boolean {
  return (
    Math.min(a[0], b[0]) - 1e-12 <= c[0] &&
    c[0] <= Math.max(a[0], b[0]) + 1e-12 &&
    Math.min(a[1], b[1]) - 1e-12 <= c[1] &&
    c[1] <= Math.max(a[1], b[1]) + 1e-12
  );
}

function segmentsIntersect(a: LngLat, b: LngLat, c: LngLat, d: LngLat): boolean {
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  if (o1 === 0 && onSegment(a, b, c)) return true;
  if (o2 === 0 && onSegment(a, b, d)) return true;
  if (o3 === 0 && onSegment(c, d, a)) return true;
  if (o4 === 0 && onSegment(c, d, b)) return true;
  return o1 > 0 !== o2 > 0 && o3 > 0 !== o4 > 0;
}

function pointInPolygon(lon: number, lat: number, rings: PolygonRings): boolean {
  if (rings.length === 0 || !pointInRing(lon, lat, rings[0])) return false;
  for (let i = 1; i < rings.length; i++) {
    if (pointInRing(lon, lat, rings[i])) return false;
  }
  return true;
}

function ringSegments(ring: Ring): Array<[LngLat, LngLat]> {
  const out: Array<[LngLat, LngLat]> = [];
  if (ring.length < 2) return out;
  for (let i = 0; i < ring.length - 1; i++) out.push([ring[i], ring[i + 1]]);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) out.push([last, first]);
  return out;
}

function asRings(coordinates: number[][][]): PolygonRings {
  return coordinates.map((ring) => ring.map((pair) => [pair[0], pair[1]] as LngLat));
}

function polygonsOf(geometry: Polygon | MultiPolygon | null): PolygonRings[] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return [asRings(geometry.coordinates)];
  if (geometry.type === "MultiPolygon") return geometry.coordinates.map((poly) => asRings(poly));
  return [];
}

function lineIntersectsPolygon(line: LngLat[], rings: PolygonRings): boolean {
  if (line.length === 0 || rings.length === 0) return false;
  for (const point of line) {
    if (pointInPolygon(point[0], point[1], rings)) return true;
  }
  const boundary = rings.flatMap((ring) => ringSegments(ring));
  for (let i = 0; i < line.length - 1; i++) {
    const a = line[i];
    const b = line[i + 1];
    for (const [c, d] of boundary) {
      if (segmentsIntersect(a, b, c, d)) return true;
    }
  }
  return false;
}

export function lineIntersectsGeometry(
  line: LngLat[],
  geometry: Polygon | MultiPolygon | null,
): boolean {
  return polygonsOf(geometry).some((rings) => lineIntersectsPolygon(line, rings));
}

/**
 * Colour, hashing and noise helpers for the isometric stage, plus the material palette.
 * Muted late-afternoon tones so the resources and the flood carry the strong colour.
 */

export type RGB = [number, number, number];

const clamp = (v: number) => Math.max(0, Math.min(255, v));
export const toNum = ([r, g, b]: RGB) => (Math.round(clamp(r)) << 16) | (Math.round(clamp(g)) << 8) | Math.round(clamp(b));
export const toRgb = (c: number): RGB => [(c >> 16) & 255, (c >> 8) & 255, c & 255];
export const rgba = (c: RGB, a = 1) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${a})`;

/** Darken (f < 1) or lighten (f > 1). Darker shades drift cool, the way shadow does outdoors. */
export function shade(c: number, f: number): number {
  const [r, g, b] = toRgb(c);
  const cool = f < 1 ? (1 - f) * 0.2 : 0;
  return toNum([r * f * (1 - cool), g * f * (1 - cool * 0.45), b * f * (1 + cool * 0.45)]);
}

export function mix(a: number, b: number, t: number): number {
  const x = toRgb(a);
  const y = toRgb(b);
  return toNum([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t]);
}

/** Deterministic hash of two integers and a seed, in [0, 1). */
export function hash2(x: number, y: number, seed = 0): number {
  let h = Math.imul(x | 0, 0x27d4eb2d) ^ Math.imul(y | 0, 0x165667b1) ^ Math.imul(seed | 0, 0x9e3779b1);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export function hashN(n: number, seed = 0): number {
  return hash2(n, n * 31 + 7, seed);
}

const fade = (t: number) => t * t * (3 - 2 * t);

/** Smooth value noise; a lattice period makes it tile seamlessly. */
export function noise(x: number, y: number, seed: number, period = 0): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const fx = fade(x - xi);
  const fy = fade(y - yi);
  const w = (v: number) => (period ? ((v % period) + period) % period : v);
  const a = hash2(w(xi), w(yi), seed);
  const b = hash2(w(xi + 1), w(yi), seed);
  const c = hash2(w(xi), w(yi + 1), seed);
  const d = hash2(w(xi + 1), w(yi + 1), seed);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}

/** Ground materials (top-down texture base colours). */
export const GROUND = {
  grassDark: [70, 92, 52] as RGB,
  grassLight: [112, 128, 70] as RGB,
  field: [86, 118, 60] as RGB,
  asphalt: [72, 74, 78] as RGB,
  asphaltLight: [88, 90, 94] as RGB,
  marking: [224, 214, 170] as RGB,
  concrete: [176, 170, 158] as RGB,
  concreteSeam: [134, 128, 118] as RGB,
  kerb: [196, 190, 176] as RGB,
  plaza: [168, 158, 140] as RGB,
  plazaSeam: [118, 110, 98] as RGB,
  brickWalk: [150, 84, 66] as RGB,
  path: [182, 168, 134] as RGB,
  play: [176, 128, 96] as RGB,
  water: [34, 64, 78] as RGB,
  waterLight: [66, 108, 120] as RGB,
  shallow: [70, 116, 122] as RGB,
  coping: [150, 142, 128] as RGB,
  yard: [96, 112, 66] as RGB,
  lot: [96, 96, 98] as RGB,
};

/** Building materials (numbers for Pixi). */
export const BUILD = {
  brick: 0x8a4f3e, brickDark: 0x6f3b2f, brickLight: 0x9a5d48,
  clapboard: [0xd9d2c2, 0xc9b98e, 0x9ea6a3, 0x8f9e84, 0x7d8b9a, 0xb7a487, 0xd2c6a8, 0x8a958a],
  clapAccent: [0x7f3b33, 0x3e4e66, 0x5d6b4f],
  concrete: 0xa9a294, concreteDark: 0x8e887c,
  glass: 0x5d7480, glassDark: 0x2c3438, glassLit: 0xe0a85c,
  steel: 0xb8bcbf, steelDark: 0x52575c,
  stone: 0xb6ab96, stoneDark: 0x6c6457,
  slate: 0x474c53, shingle: 0x55504c, membrane: 0x77797a, copper: 0x5f8c7a, terracotta: 0x8e5540,
  cedar: 0xc79a62, cream: 0xd6ccb4, timber: 0x6a5240,
} as const;

export const SKY_BG = 0x0b0e14;

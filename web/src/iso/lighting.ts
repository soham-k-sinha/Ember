/**
 * Time-of-day lighting for the stage. The flood clock (t_s from 0) maps onto a late afternoon
 * in October: golden hour at the start, dusk as the river crests, night by the end, so windows,
 * street lamps and light bars come on as the water rises. Every channel eases between keys.
 * Labelled in the UI: the clock time is illustrative; the simulation runs in seconds.
 */

export type Light = {
  hour: number;
  world: [number, number, number]; // multiplier for ground, buildings, trees
  people: [number, number, number]; // milder multiplier so people stay readable
  shadow: number; // cast-shadow opacity
  lights: number; // 0 = off, 1 = full night lighting
  sky: number; // canvas background
  haze: [number, number, number];
  hazeAlpha: number;
};

export const START_HOUR = 16.4;

type Key = { h: number; world: [number, number, number]; shadow: number; lights: number; sky: [number, number, number]; haze: [number, number, number]; hazeA: number };

const KEYS: Key[] = [
  { h: 15.0, world: [1.0, 0.97, 0.9], shadow: 0.46, lights: 0, sky: [16, 20, 28], haze: [255, 222, 176], hazeA: 0.06 },
  { h: 16.6, world: [1.0, 0.91, 0.76], shadow: 0.52, lights: 0.06, sky: [18, 18, 26], haze: [255, 176, 100], hazeA: 0.16 },
  { h: 17.6, world: [0.9, 0.74, 0.66], shadow: 0.42, lights: 0.38, sky: [16, 14, 24], haze: [246, 134, 86], hazeA: 0.18 },
  { h: 18.4, world: [0.6, 0.52, 0.68], shadow: 0.22, lights: 0.78, sky: [12, 11, 22], haze: [150, 104, 186], hazeA: 0.12 },
  { h: 19.3, world: [0.4, 0.42, 0.64], shadow: 0.1, lights: 1, sky: [9, 11, 20], haze: [72, 84, 160], hazeA: 0.08 },
  { h: 24.0, world: [0.34, 0.38, 0.6], shadow: 0.06, lights: 1, sky: [7, 9, 18], haze: [44, 60, 120], hazeA: 0.05 },
];

const ease = (t: number) => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const lerp3 = (a: [number, number, number], b: [number, number, number], t: number): [number, number, number] => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

export function lightAt(tS: number): Light {
  const hour = START_HOUR + tS / 3600;
  let i = 0;
  while (i < KEYS.length - 2 && KEYS[i + 1].h <= hour) i++;
  const a = KEYS[i];
  const b = KEYS[i + 1];
  const t = ease(Math.min(1, Math.max(0, (hour - a.h) / (b.h - a.h))));
  const world = lerp3(a.world, b.world, t);
  const lights = lerp(a.lights, b.lights, t);
  const sky = lerp3(a.sky, b.sky, t);
  return {
    hour,
    world,
    people: world.map((c) => Math.min(1, c + (1 - c) * 0.65 + lights * 0.04)) as [number, number, number],
    shadow: lerp(a.shadow, b.shadow, t),
    lights,
    sky: (Math.round(sky[0]) << 16) | (Math.round(sky[1]) << 8) | Math.round(sky[2]),
    haze: lerp3(a.haze, b.haze, t),
    hazeAlpha: lerp(a.hazeA, b.hazeA, t),
  };
}

export const tint = (m: [number, number, number]) =>
  (Math.round(255 * Math.min(1, m[0])) << 16) | (Math.round(255 * Math.min(1, m[1])) << 8) | Math.round(255 * Math.min(1, m[2]));

export function clockLabel(tS: number): string {
  const h = START_HOUR + tS / 3600;
  const hh = Math.floor(h) % 24;
  const mm = Math.floor((h - Math.floor(h)) * 60);
  const suffix = hh >= 12 ? "pm" : "am";
  return `${((hh + 11) % 12) + 1}:${String(mm).padStart(2, "0")} ${suffix}`;
}

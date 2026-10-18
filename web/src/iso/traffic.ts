/**
 * Background cars on the stage (D73): the scenario's synthetic staged evacuation, simulated once by the
 * engine (queue_traffic) and shipped in the playback as sampled car paths. Each car is a pooled sprite
 * using one of 16 heading × 8 colour textures pre-rendered from the same car model the car parks use;
 * it moves along its path by the replay clock and sits still while queued, so jams form where the engine
 * jammed. Nothing here is simulated; the vans feel the same traffic through the engine's slowdown table.
 * On screen (only) the evacuation cars keep to the right-hand lane and keep a gap: the engine queues cars at
 * the end of a road on one spot and its paths run down the centre line, so a car that would overlap the one
 * ahead (or an everyday car) is drawn further back along its own path and catches up when the way clears.
 * The same sprites draw the everyday cars (ambient.ts), with brake lights at the signals and headlights after
 * dusk; from afar every car keeps a minimum on-screen size, like the people.
 */

import { Container, Sprite, Texture, type Renderer } from "pixi.js";
import type { AmbientCar, Other } from "./ambient";
import { car } from "./props";
import type { Projector } from "./project";
import type { Playback } from "../playback";

const HEADINGS = 16;
const COLORS = [0xd8d8d4, 0x2b2e33, 0x8d9299, 0x6b1f22, 0x24395c, 0x7c8a6a, 0xb7aa92, 0xa03a2a];
const LEN_M = 4.6;
const RES = 10; // texture px per metre (sharp up to the closest zoom)

type Car = { id: string; ab: Array<[number, number]>; t: number[]; cum: number[]; color: number; t0: number; t1: number; shown: number; was: number };
type Item = { c: Car; i: number; D: number; a: number; b: number; ua: number; ub: number; cell: number };
type Frame = { tex: Texture; ax: number; ay: number };
type View = { x0: number; y0: number; x1: number; y1: number };
export type CarLook = { now: number; camS: number; lights: number };

const LANE_M = 1.8; // evacuation cars drive this far right of the road's centre line
const GAP_M = 6.5; // front-to-front spacing in a queue
const CATCH_UP = 15; // m/s a held-back car regains on top of its own progress
const MIN_PX = 5.5; // a car is never shorter than this on screen…
const MAX_K = 2.4; // …but never more than this many times its size, or it would not fit its road
const LIGHTS_S = 0.55; // brake and head lights only when they read

function glowTexture(): Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(16, 16, 0, 16, 16, 16);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.55)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 32, 32);
  return Texture.from(c);
}

export class TrafficCars {
  private frames: Frame[][] = []; // [color][heading]
  private cars: Car[] = [];
  private pool: Sprite[] = [];
  private source: Playback["traffic"] | null = null;
  private n = 0;
  private glow = glowTexture();
  private lamps: Sprite[] = [];
  private nl = 0;
  private lastNow = 0;
  private grid = new Map<number, Array<Item | AmbientCar>>();
  /** The evacuation cars as drawn last frame (the everyday cars respect them). */
  shown: Other[] = [];

  constructor(
    renderer: Renderer,
    private objects: Container,
    private p: Projector,
    private depthFor: (a: number, b: number, px: number, py: number, halfW: number, height: number) => number,
  ) {
    for (let c = 0; c < COLORS.length; c++) {
      const row: Frame[] = [];
      for (let h = 0; h < HEADINGS; h++) {
        const g = car(p, 0, 0, (h / HEADINGS) * Math.PI * 2, COLORS[c]);
        g.position.set(0, 0);
        const b = g.getLocalBounds();
        const tex = renderer.generateTexture({ target: g, resolution: RES, antialias: true });
        row.push({ tex, ax: -b.minX / (b.maxX - b.minX), ay: -b.minY / (b.maxY - b.minY) });
        g.destroy();
      }
      this.frames.push(row);
    }
  }

  private load(traffic: Playback["traffic"] | null) {
    this.source = traffic;
    this.cars = [];
    if (!traffic) return;
    const { a0, a1, b0, b1 } = this.p.bounds;
    traffic.cars.forEach((c, i) => {
      const ab = c.path.map(([lon, lat]) => this.p.toAB(lon, lat));
      // only cars that pass over the stage
      if (!ab.some(([a, b]) => a > a0 - 20 && a < a1 + 20 && b > b0 - 20 && b < b1 + 20)) return;
      const cum = [0];
      for (let q = 1; q < ab.length; q++) cum.push(cum[q - 1] + Math.hypot(ab[q][0] - ab[q - 1][0], ab[q][1] - ab[q - 1][1]));
      this.cars.push({ id: c.id, ab, t: c.t, cum, color: i % COLORS.length, t0: c.t[0], t1: c.t[c.t.length - 1], shown: NaN, was: NaN });
    });
  }

  update(traffic: Playback["traffic"] | null | undefined, t: number, view: View, tint: number, ambient: AmbientCar[] = [], look: CarLook = { now: 0, camS: 1, lights: 0 }) {
    if ((traffic ?? null) !== this.source) this.load(traffic ?? null);
    const { a0, a1, b0, b1 } = this.p.bounds;
    this.n = 0;
    this.nl = 0;
    const k = Math.min(MAX_K, Math.max(1, MIN_PX / (LEN_M * look.camS)));
    const lit = look.camS >= LIGHTS_S;
    for (const c of ambient) {
      if (c.a < a0 || c.a > a1 || c.b < b0 || c.b > b1) continue;
      const [x, y] = this.p.iso(c.a, c.b);
      if (x < view.x0 - 6 * k || x > view.x1 + 6 * k || y < view.y0 - 6 * k || y > view.y1 + 6 * k) continue;
      const z = this.put(c.a, c.b, x, y, Math.atan2(c.ub, c.ua), c.color % COLORS.length, k, tint);
      if (!lit) continue;
      const braking = c.acc < -0.6 || c.v < 0.3;
      const tail = braking ? 0.95 : 0.3 * look.lights;
      if (tail > 0.05) this.lamp(c.a - c.ua * 2.15 * k, c.b - c.ub * 2.15 * k, 0.55, 0xff2a1a, (braking ? 1.4 : 1) * k, tail, z);
      if (look.lights > 0.05) this.lamp(c.a + c.ua * 3.6 * k, c.b + c.ub * 3.6 * k, 0.6, 0xffe6b0, 2.4 * k, 0.45 * look.lights, z);
    }
    const dt = Math.min(0.25, Math.max(0, look.now - this.lastNow));
    this.lastNow = look.now;
    // evacuation cars: where the replay puts them, then held back where they would overlap
    const items: Item[] = [];
    for (const c of this.cars) {
      if (t < c.t0 || t > c.t1) {
        c.shown = c.was = NaN;
        continue;
      }
      let lo = 0;
      let hi = c.t.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (c.t[mid] <= t) lo = mid;
        else hi = mid;
      }
      const span = c.t[hi] - c.t[lo];
      const f = span > 0 ? Math.min(1, Math.max(0, (t - c.t[lo]) / span)) : 0;
      const D0 = c.cum[lo] + (c.cum[hi] - c.cum[lo]) * f;
      const fresh = Number.isNaN(c.shown) || Math.abs(D0 - c.shown) > 80 || D0 < c.was;
      const D = fresh ? D0 : Math.min(D0, c.shown + (D0 - c.was) + CATCH_UP * dt);
      c.was = D0;
      const it: Item = { c, i: items.length, D, a: 0, b: 0, ua: 1, ub: 0, cell: 0 };
      this.at(it);
      if (it.a < a0 - 30 || it.a > a1 + 30 || it.b < b0 - 30 || it.b > b1 + 30) {
        c.shown = D;
        continue;
      }
      items.push(it);
    }
    this.grid.clear();
    for (const c of ambient) gridAdd(this.grid, cellOf(c.a, c.b), c);
    for (const it of items) gridAdd(this.grid, (it.cell = cellOf(it.a, it.b)), it);
    for (const it of items) {
      for (let guard = 0; guard < 12; guard++) {
        const push = this.blocked(it);
        if (push <= 0) break;
        it.D = Math.max(0, it.D - push);
        const before = it.cell;
        this.at(it);
        it.cell = cellOf(it.a, it.b);
        if (it.cell !== before) {
          const arr = this.grid.get(before);
          if (arr) arr.splice(arr.indexOf(it), 1);
          gridAdd(this.grid, it.cell, it);
        }
        if (it.D === 0) break;
      }
      it.c.shown = it.D;
    }
    this.shown = items;
    for (const it of items) {
      if (it.a < a0 || it.a > a1 || it.b < b0 || it.b > b1) continue;
      const [x, y] = this.p.iso(it.a, it.b);
      if (x < view.x0 - 6 * k || x > view.x1 + 6 * k || y < view.y0 - 6 * k || y > view.y1 + 6 * k) continue;
      this.put(it.a, it.b, x, y, Math.atan2(it.ub, it.ua), it.c.color, k, tint);
    }
    for (let i = this.n; i < this.pool.length; i++) this.pool[i].visible = false;
    for (let i = this.nl; i < this.lamps.length; i++) this.lamps[i].visible = false;
  }

  /** Position and heading of an evacuation car at distance it.D along its own path, in the right-hand lane. */
  private at(it: Item) {
    const { ab, cum } = it.c;
    let lo = 0;
    let hi = cum.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (cum[mid] <= it.D) lo = mid;
      else hi = mid;
    }
    // heading from the nearest segment that actually moves (a queued car keeps its direction)
    let j = hi;
    while (j > 1 && cum[j] - cum[j - 1] < 0.05) j--;
    const seg = cum[j] - cum[j - 1];
    const ua = seg > 0.05 ? (ab[j][0] - ab[j - 1][0]) / seg : it.ua;
    const ub = seg > 0.05 ? (ab[j][1] - ab[j - 1][1]) / seg : it.ub;
    const span = cum[hi] - cum[lo];
    const f = span > 0 ? Math.min(1, Math.max(0, (it.D - cum[lo]) / span)) : 0;
    it.a = ab[lo][0] + (ab[hi][0] - ab[lo][0]) * f - ub * LANE_M;
    it.b = ab[lo][1] + (ab[hi][1] - ab[lo][1]) * f + ua * LANE_M;
    it.ua = ua;
    it.ub = ub;
  }

  /** How far it must drop back to keep GAP_M behind the car ahead in its lane (≤ 0: it is clear). */
  private blocked(it: Item): number {
    let need = 0;
    const cx = Math.floor(it.a / 10);
    const cy = Math.floor(it.b / 10);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const o of this.grid.get((cx + dx) * 100003 + (cy + dy)) ?? []) {
        if (o === it) continue;
        const ra = o.a - it.a;
        const rb = o.b - it.b;
        const along = ra * it.ua + rb * it.ub;
        if (!("i" in o) && o.ua * it.ua + o.ub * it.ub < 0.3) {
          // an everyday car crossing (or turning) just ahead: wait for it to pass
          if (along > -0.5 && along < 5 && Math.abs(ra * it.ub - rb * it.ua) < 2.2) need = Math.max(need, 5 - along + 0.01);
          continue;
        }
        if (along < -0.01 || along >= GAP_M || Math.abs(ra * it.ub - rb * it.ua) > 1.6 || o.ua * it.ua + o.ub * it.ub < 0.3) continue;
        // two cars on one spot: the earlier one in the list is ahead
        if (along < 0.01 && "i" in o && o.i > it.i) continue;
        need = Math.max(need, GAP_M - along + 0.01);
      }
    }
    return need;
  }

  /** One car sprite at stage (a, b) / screen (x, y) heading `ang`; returns its depth. */
  private put(a: number, b: number, x: number, y: number, ang: number, color: number, k: number, tint: number): number {
    const h = ((Math.round((ang / (Math.PI * 2)) * HEADINGS) % HEADINGS) + HEADINGS) % HEADINGS;
    const fr = this.frames[color][h];
    let s = this.pool[this.n];
    if (!s) {
      s = new Sprite(fr.tex);
      s.eventMode = "none";
      this.objects.addChild(s);
      this.pool.push(s);
    }
    if (s.texture !== fr.tex) s.texture = fr.tex;
    s.anchor.set(fr.ax, fr.ay);
    s.scale.set(k); // generateTexture already reports world units (RES is its pixel density)
    s.position.set(x, y);
    s.zIndex = this.depthFor(a, b, x, y, 2.5 * k, 2 * k);
    s.tint = tint;
    s.visible = true;
    this.n++;
    return s.zIndex;
  }

  /** An additive glow (brake or head light) at stage point (a, b), z metres up, `size` metres across. */
  private lamp(a: number, b: number, z: number, color: number, size: number, alpha: number, depth: number) {
    let s = this.lamps[this.nl];
    if (!s) {
      s = new Sprite(this.glow);
      s.eventMode = "none";
      s.anchor.set(0.5);
      s.blendMode = "add";
      this.objects.addChild(s);
      this.lamps.push(s);
    }
    const [x, y] = this.p.iso(a, b, z);
    s.position.set(x, y);
    s.width = size;
    s.height = size * 0.6;
    s.tint = color;
    s.alpha = alpha;
    s.zIndex = depth + 0.01;
    s.visible = true;
    this.nl++;
  }
}

const cellOf = (a: number, b: number) => Math.floor(a / 10) * 100003 + Math.floor(b / 10);

function gridAdd<T>(m: Map<number, T[]>, k: number, v: T) {
  const arr = m.get(k);
  if (arr) arr.push(v);
  else m.set(k, [v]);
}

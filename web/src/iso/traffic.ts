/**
 * Background cars on the stage (D73): the scenario's synthetic staged evacuation, simulated once by the
 * engine (queue_traffic) and shipped in the playback as sampled car paths. Each car is a pooled sprite
 * using one of 16 heading × 8 colour textures pre-rendered from the same car model the car parks use;
 * it moves along its path by the replay clock and sits still while queued, so jams form where the engine
 * jammed. Nothing here is simulated; the vans feel the same traffic through the engine's slowdown table.
 * The same sprites draw the everyday cars (ambient.ts), with brake lights at the signals and headlights after
 * dusk; from afar every car keeps a minimum on-screen size, like the people.
 */

import { Container, Sprite, Texture, type Renderer } from "pixi.js";
import type { AmbientCar } from "./ambient";
import { car } from "./props";
import type { Projector } from "./project";
import type { Playback } from "../playback";

const HEADINGS = 16;
const COLORS = [0xd8d8d4, 0x2b2e33, 0x8d9299, 0x6b1f22, 0x24395c, 0x7c8a6a, 0xb7aa92, 0xa03a2a];
const LEN_M = 4.6;
const RES = 10; // texture px per metre (sharp up to the closest zoom)

type Car = { id: string; ab: Array<[number, number]>; t: number[]; color: number; t0: number; t1: number };
type Frame = { tex: Texture; ax: number; ay: number };
type View = { x0: number; y0: number; x1: number; y1: number };
export type CarLook = { now: number; camS: number; lights: number };

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
      this.cars.push({ id: c.id, ab, t: c.t, color: i % COLORS.length, t0: c.t[0], t1: c.t[c.t.length - 1] });
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
    for (const c of this.cars) {
      if (t < c.t0 || t > c.t1) continue;
      // position + heading on the segment that contains t
      let lo = 0;
      let hi = c.t.length - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (c.t[mid] <= t) lo = mid;
        else hi = mid;
      }
      const span = c.t[hi] - c.t[lo];
      const f = span > 0 ? Math.min(1, Math.max(0, (t - c.t[lo]) / span)) : 0;
      const [pa, pb] = c.ab[lo];
      const [qa, qb] = c.ab[hi];
      const a = pa + (qa - pa) * f;
      const b = pb + (qb - pb) * f;
      if (a < a0 || a > a1 || b < b0 || b > b1) continue;
      const [x, y] = this.p.iso(a, b);
      if (x < view.x0 - 6 || x > view.x1 + 6 || y < view.y0 - 6 || y > view.y1 + 6) continue;
      // heading from the nearest segment that actually moves (a queued car keeps its last direction)
      let da = qa - pa;
      let db = qb - pb;
      for (let k = lo; Math.abs(da) + Math.abs(db) < 0.01 && k > 0; k--) {
        da = c.ab[k][0] - c.ab[k - 1][0];
        db = c.ab[k][1] - c.ab[k - 1][1];
      }
      this.put(a, b, x, y, Math.atan2(db, da), c.color, k, tint);
    }
    for (let i = this.n; i < this.pool.length; i++) this.pool[i].visible = false;
    for (let i = this.nl; i < this.lamps.length; i++) this.lamps[i].visible = false;
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

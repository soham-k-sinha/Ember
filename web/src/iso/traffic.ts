/**
 * Background cars on the stage (D73): the scenario's synthetic staged evacuation, simulated once by the
 * engine (queue_traffic) and shipped in the playback as sampled car paths. Each car is a pooled sprite
 * using one of 16 heading × 8 colour textures pre-rendered from the same car model the car parks use;
 * it moves along its path by the replay clock and sits still while queued, so jams form where the engine
 * jammed. Nothing here is simulated; the vans feel the same traffic through the engine's slowdown table.
 */

import { Container, Sprite, type Renderer, type Texture } from "pixi.js";
import { car } from "./props";
import type { Projector } from "./project";
import type { Playback } from "../playback";

const HEADINGS = 16;
const COLORS = [0xd8d8d4, 0x2b2e33, 0x8d9299, 0x6b1f22, 0x24395c, 0x7c8a6a, 0xb7aa92, 0xa03a2a];
const RES = 10; // texture px per metre (sharp up to the closest zoom)

type Car = { id: string; ab: Array<[number, number]>; t: number[]; color: number; t0: number; t1: number };
type Frame = { tex: Texture; ax: number; ay: number };

export class TrafficCars {
  private frames: Frame[][] = []; // [color][heading]
  private cars: Car[] = [];
  private pool: Sprite[] = [];
  private source: Playback["traffic"] | null = null;

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

  update(traffic: Playback["traffic"] | null | undefined, t: number, view: { x0: number; y0: number; x1: number; y1: number }, tint: number) {
    if ((traffic ?? null) !== this.source) this.load(traffic ?? null);
    const { a0, a1, b0, b1 } = this.p.bounds;
    let n = 0;
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
      const ang = Math.atan2(db, da);
      const h = ((Math.round((ang / (Math.PI * 2)) * HEADINGS) % HEADINGS) + HEADINGS) % HEADINGS;
      const fr = this.frames[c.color][h];
      let s = this.pool[n];
      if (!s) {
        s = new Sprite(fr.tex);
        s.eventMode = "none";
        this.objects.addChild(s);
        this.pool.push(s);
      }
      if (s.texture !== fr.tex) s.texture = fr.tex;
      s.anchor.set(fr.ax, fr.ay);
      s.scale.set(1); // generateTexture already reports world units (RES is its pixel density)
      s.position.set(x, y);
      s.zIndex = this.depthFor(a, b, x, y, 2.5, 2);
      s.tint = tint;
      s.visible = true;
      n++;
    }
    for (let i = n; i < this.pool.length; i++) this.pool[i].visible = false;
  }
}

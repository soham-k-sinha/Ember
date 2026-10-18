/**
 * Traffic lights at the district's real signalised junctions (OpenStreetMap highway=traffic_signals, baked into
 * the stage data). Each junction gets signal poles on the kerb of its two main road axes; the axes alternate
 * green → amber → red on an illustrative 46 s cycle (offset per junction), with glowing lamps after dusk.
 * Decoration only: background cars follow the engine's traffic run and do not stop for these lights.
 */

import { Container, Graphics } from "pixi.js";
import type { Diorama } from "./data";
import { FOOT, ROAD_W } from "./ground";
import type { Projector } from "./project";

const CYCLE_S = 46;
const GREEN_S = 19;
const AMBER_S = 4;
const POLE_M = 4.2;

type Pole = { root: Container; lamp: Graphics; glow: Graphics; axis: 0 | 1; offset: number; x: number; y: number; state: number };

function phase(t: number, axis: 0 | 1, offset: number): 0 | 1 | 2 {
  // 0 green, 1 amber, 2 red; axis 1 runs half a cycle behind axis 0
  const c = (t + offset + (axis ? CYCLE_S / 2 : 0)) % CYCLE_S;
  return c < GREEN_S ? 0 : c < GREEN_S + AMBER_S ? 1 : 2;
}

const COLORS = [0x3be37a, 0xffb020, 0xff3b30];

export class TrafficSignals {
  private poles: Pole[] = [];

  constructor(data: Diorama, private p: Projector, objects: Container, depthFor: (a: number, b: number, px: number, py: number, halfW: number, height: number) => number, lit: Container[]) {
    const roads = data.roads.filter((r) => !FOOT.has(r.k) && r.k !== "parking_aisle").map((r) => ({ k: r.k, pts: r.path.map(([lon, lat]) => p.toAB(lon, lat)) }));
    (data.signals ?? []).forEach(([lon, lat], si) => {
      const [na, nb] = p.toAB(lon, lat);
      // the roads through this junction: direction and half-width of each segment that touches it
      const dirs: Array<{ ua: number; ub: number; half: number }> = [];
      for (const r of roads) {
        for (let i = 0; i < r.pts.length; i++) {
          const [a, b] = r.pts[i];
          if (Math.hypot(a - na, b - nb) > 6) continue;
          for (const j of [i - 1, i + 1]) {
            if (j < 0 || j >= r.pts.length) continue;
            const da = r.pts[j][0] - a;
            const db = r.pts[j][1] - b;
            const len = Math.hypot(da, db);
            if (len > 1) dirs.push({ ua: da / len, ub: db / len, half: (ROAD_W[r.k] ?? 7) / 2 });
          }
        }
      }
      if (!dirs.length) return;
      // two axes: the widest road, and the most perpendicular other one
      dirs.sort((x, y) => y.half - x.half);
      const A = dirs[0];
      const B = dirs.reduce((best, d) => (Math.abs(d.ua * A.ub - d.ub * A.ua) > Math.abs(best.ua * A.ub - best.ub * A.ua) ? d : best), dirs[0]);
      const offset = (si * 7.3) % CYCLE_S;
      const corners: Array<{ axis: 0 | 1; a: number; b: number }> = [];
      for (const [axis, d, other] of [[0, A, B], [1, B, A]] as const) {
        // two poles per axis, on opposite kerbs just before the junction
        for (const side of [1, -1]) {
          const back = (other.half + 2.2) * side;
          const kerb = (d.half + 1.2) * side;
          corners.push({ axis, a: na - d.ua * back - d.ub * kerb, b: nb - d.ub * back + d.ua * kerb });
        }
      }
      for (const c of corners) {
        const [x, y] = p.iso(c.a, c.b);
        const root = new Container();
        const pole = new Graphics();
        const [, topY] = p.iso(0, 0, POLE_M);
        pole.rect(-0.09, topY, 0.18, -topY).fill(0x2b2f33);
        pole.rect(-0.09, topY, 0.06, -topY).fill(0x4a5056);
        pole.roundRect(-0.28, topY - 0.95, 0.56, 1.05, 0.1).fill(0x1b1d20).stroke({ width: 0.06, color: 0x050505 });
        const lamp = new Graphics();
        const glow = new Graphics();
        glow.blendMode = "add";
        root.addChild(pole, lamp, glow);
        root.position.set(x, y);
        root.zIndex = depthFor(c.a, c.b, x, y, 0.4, POLE_M * 1.22);
        objects.addChild(root);
        lit.push(pole);
        this.poles.push({ root, lamp, glow, axis: c.axis, offset, x, y, state: -1 });
      }
    });
  }

  /** Lamps for wall-clock time `now` (s); `lights` 0..1 brightens the glow after dusk. */
  update(now: number, lights: number, view: { x0: number; y0: number; x1: number; y1: number }, camS: number) {
    const [, topY] = this.p.iso(0, 0, POLE_M);
    for (const pole of this.poles) {
      const on = camS >= 0.7 && pole.x > view.x0 - 4 && pole.x < view.x1 + 4 && pole.y > view.y0 - 6 && pole.y < view.y1 + 8;
      pole.root.visible = on;
      if (!on) continue;
      const st = phase(now, pole.axis, pole.offset);
      const key = st * 10 + Math.round(lights * 4);
      if (key === pole.state) continue;
      pole.state = key;
      pole.lamp.clear();
      pole.glow.clear();
      for (let k = 0; k < 3; k++) {
        const ly = topY - 0.78 + k * 0.32; // red top, amber middle, green bottom
        const idx = 2 - k;
        const lit = idx === st;
        pole.lamp.circle(0, ly, 0.12).fill(lit ? COLORS[idx] : 0x30302c);
        if (lit) pole.glow.circle(0, ly, 0.55 + 0.6 * lights).fill({ color: COLORS[idx], alpha: 0.25 + 0.4 * lights });
      }
    }
  }
}

/**
 * Traffic lights at the district's real signalised junctions (OpenStreetMap highway=traffic_signals, baked into
 * the stage data). Each junction gets signal poles on the kerb of its two main road axes; the axes alternate
 * green → amber → red on an illustrative 46 s cycle (offset per junction), with glowing lamps after dusk. Like the
 * people, a signal never draws smaller than ~18 px tall so its lamps stay readable; zoomed out, one signal per
 * junction stands in for its four.
 * The everyday cars (ambient.ts) stop for these lights; the engine's evacuation cars follow their own run and do not.
 */

import { Container, Graphics } from "pixi.js";
import type { Diorama } from "./data";
import { FOOT, ROAD_W } from "./ground";
import type { Projector } from "./project";

const CYCLE_S = 46;
const GREEN_S = 19;
const AMBER_S = 4;
const POLE_M = 4.2;

type Pole = { root: Container; lamp: Graphics; glow: Graphics; arm: Graphics; tip: [number, number]; axis: 0 | 1; offset: number; x: number; y: number; state: number; primary: boolean };

const HEAD_W = 0.7;
const HEAD_H = 1.5;
const ARM_K = 1.6; // the mast arm only while signals draw near true size

const MIN_PX = 14; // minimum on-screen pole height
const ALL_POLES_S = 0.7; // closer than this, every pole of a junction; further, one per junction

function phase(t: number, axis: 0 | 1, offset: number): 0 | 1 | 2 {
  // 0 green, 1 amber, 2 red; axis 1 runs half a cycle behind axis 0
  const c = (t + offset + (axis ? CYCLE_S / 2 : 0)) % CYCLE_S;
  return c < GREEN_S ? 0 : c < GREEN_S + AMBER_S ? 1 : 2;
}

const COLORS = [0x3be37a, 0xffb020, 0xff3b30];

export type Junction = { a: number; b: number; axes: [{ ua: number; ub: number }, { ua: number; ub: number }]; offset: number };

export class TrafficSignals {
  private poles: Pole[] = [];
  readonly junctions: Junction[] = [];

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
      this.junctions.push({ a: na, b: nb, axes: [A, B], offset });
      const corners: Array<{ axis: 0 | 1; a: number; b: number; ia: number; ib: number; arm: number }> = [];
      for (const [axis, d, other] of [[0, A, B], [1, B, A]] as const) {
        // two poles per axis, on opposite kerbs just before the junction
        for (const side of [1, -1]) {
          const back = (other.half + 2.2) * side;
          const kerb = (d.half + 1.2) * side;
          // the mast arm reaches in over the approaching lane
          corners.push({ axis, a: na - d.ua * back - d.ub * kerb, b: nb - d.ub * back + d.ua * kerb, ia: d.ub * side, ib: -d.ua * side, arm: Math.min(6, d.half * 0.75 + 1.2) });
        }
      }
      corners.forEach((c, ci) => {
        const [x, y] = p.iso(c.a, c.b);
        const root = new Container();
        const pole = new Graphics();
        const [, topY] = p.iso(0, 0, POLE_M);
        pole.rect(-0.09, topY, 0.18, -topY).fill(0x2b2f33);
        pole.rect(-0.09, topY, 0.06, -topY).fill(0x4a5056);
        pole.roundRect(-HEAD_W / 2, topY - HEAD_H + 0.1, HEAD_W, HEAD_H, 0.12).fill(0x1b1d20).stroke({ width: 0.07, color: 0x050505 });
        const [ex, ey] = p.iso(c.a + c.ia * c.arm, c.b + c.ib * c.arm, POLE_M - 0.3);
        const tip: [number, number] = [ex - x, ey - y];
        const arm = new Graphics();
        arm.moveTo(0, topY + 0.35).lineTo(tip[0], tip[1]).stroke({ width: 0.16, color: 0x2b2f33, cap: "round" });
        arm.roundRect(tip[0] - HEAD_W / 2, tip[1], HEAD_W, HEAD_H, 0.12).fill(0x1b1d20).stroke({ width: 0.07, color: 0x050505 });
        const lamp = new Graphics();
        const glow = new Graphics();
        glow.blendMode = "add";
        root.addChild(pole, arm, lamp, glow);
        root.position.set(x, y);
        root.zIndex = depthFor(c.a, c.b, x, y, 0.4, POLE_M * 1.22);
        objects.addChild(root);
        lit.push(pole, arm);
        this.poles.push({ root, lamp, glow, arm, tip, axis: c.axis, offset, x, y, state: -1, primary: ci === 0 });
      });
    });
  }

  /** 0 green, 1 amber, 2 red for a car heading (ua, ub) into junction j: it obeys the axis it is most aligned with. */
  stateFor(j: number, ua: number, ub: number, now: number): 0 | 1 | 2 {
    const { axes, offset } = this.junctions[j];
    const axis = Math.abs(ua * axes[0].ua + ub * axes[0].ub) >= Math.abs(ua * axes[1].ua + ub * axes[1].ub) ? 0 : 1;
    return phase(now, axis, offset);
  }

  /** Lamps for wall-clock time `now` (s); `lights` 0..1 brightens the glow after dusk. */
  update(now: number, lights: number, view: { x0: number; y0: number; x1: number; y1: number }, camS: number) {
    const [, topY] = this.p.iso(0, 0, POLE_M);
    const k = Math.max(1, MIN_PX / (POLE_M * 1.22 * camS));
    const all = camS >= ALL_POLES_S;
    for (const pole of this.poles) {
      if (pole.root.scale.x !== k) pole.root.scale.set(k);
      const on = (all || pole.primary) && pole.x > view.x0 - 4 * k && pole.x < view.x1 + 4 && pole.y > view.y0 - 6 && pole.y < view.y1 + 8;
      pole.root.visible = on;
      if (!on) continue;
      const st = phase(now, pole.axis, pole.offset);
      const near = k < ARM_K;
      pole.arm.visible = near;
      const key = st * 10 + Math.round(lights * 4) + (near ? 100 : 0);
      if (key === pole.state) continue;
      pole.state = key;
      pole.lamp.clear();
      pole.glow.clear();
      const heads: Array<[number, number]> = [[0, topY - HEAD_H + 0.1]];
      if (near) heads.push(pole.tip);
      for (const [hx, hy] of heads) {
        for (let q = 0; q < 3; q++) {
          const ly = hy + 0.3 + q * 0.45; // red top, amber middle, green bottom
          const idx = 2 - q;
          const on = idx === st;
          pole.lamp.circle(hx, ly, 0.17).fill(on ? COLORS[idx] : 0x30302c);
          if (on) pole.glow.circle(hx, ly, 0.7 + 0.6 * lights).fill({ color: COLORS[idx], alpha: 0.3 + 0.4 * lights });
        }
      }
    }
  }
}

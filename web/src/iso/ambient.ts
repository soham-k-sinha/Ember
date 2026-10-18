/**
 * Everyday street traffic (D98): illustrative cars that keep the district's real roads busy before, during and
 * after the evacuation. They drive the stage's OpenStreetMap road graph on the right-hand lane, follow the car
 * ahead (intelligent-driver model), slow for corners, stop at the red and amber of the real signalised
 * junctions (signals.ts), take turns through every junction box (a car enters only when its path through the
 * box clears every car already in it, and conflicting cars go first come, first served), queue behind the
 * engine's evacuation cars and never cross one in a box, keep to one-way streets (two lanes on the wide
 * one-way carriageways such as Soldiers Field Road), turn back at floodwater, and thin out as the evacuation empties the district. They run
 * on the wall clock like the passers-by. Not simulated by the engine and in no metric: the evacuation traffic
 * that the planner feels is the engine's staged-evacuation run (traffic.ts).
 */

import type { Diorama } from "./data";
import { FOOT, ROAD_W } from "./ground";
import type { Projector } from "./project";
import type { TrafficSignals } from "./signals";

const SPEED: Record<string, number> = { motorway: 16, trunk: 14, primary: 12, secondary: 11, tertiary: 10, residential: 8, unclassified: 8, unknown: 7, living_street: 5, service: 5 };
const WEIGHT: Record<string, number> = { motorway: 3, trunk: 3, primary: 2.5, secondary: 2, tertiary: 1.6, residential: 1, unclassified: 1, unknown: 0.6, living_street: 0.5, service: 0.25 };
export const AMBIENT_CARS = 460;
const LEN = 4.6; // car length (m)
const ACC = 1.6; // m/s²
const DEC = 2.6;
const GAP0 = 2.2; // standstill gap (m)
const HEADWAY = 1.1; // s
const EDGE_M = 30; // dead ends this close to the stage edge lead off stage

type Pt = [number, number];
type Link = { pts: Pt[]; cum: number[]; len: number; n: [number, number]; k: string; v0: number; off: number; ow: number; lanes: number; trim: [number, number] };
type Node = { a: number; b: number; links: number[]; signal: number; edge: boolean };
type Turn = { L: number; d: 1 | -1; ln: number; p0: Pt; c: Pt; p2: Pt; len: number; slow: number; pts: Pt[] };
/** Another car to respect (the engine's evacuation cars): position and heading. */
export type Other = { a: number; b: number; ua: number; ub: number };
const CLEAR_M = 2.5; // two paths through a box closer than this conflict
const QUEUE_M = 8; // within this of the stop line a car has arrived (first come, first served)
export type AmbientCar = {
  id: number;
  L: number;
  d: 1 | -1;
  ln: number; // lane (0 or 1) on a two-lane one-way road
  s: number; // along the lane in the travel direction, from the link's start
  v: number;
  acc: number;
  next: Turn | null;
  passed: number; // the last signal junction crossed (not stopped for twice)
  arrive: number; // when it reached the stop line (wall clock), Infinity before
  granted: boolean; // cleared to cross the box ahead (never revoked)
  stuck: number;
  // render state
  a: number;
  b: number;
  ua: number;
  ub: number;
  color: number;
};

const bez = (p0: Pt, c: Pt, p2: Pt, u: number): Pt => {
  const w = 1 - u;
  return [w * w * p0[0] + 2 * w * u * c[0] + u * u * p2[0], w * w * p0[1] + 2 * w * u * c[1] + u * u * p2[1]];
};

export class AmbientTraffic {
  readonly cars: AmbientCar[] = [];
  private links: Link[] = [];
  private nodes: Node[] = [];
  private pick: number[] = []; // cumulative spawn weight per link
  private lanes = new Map<number, AmbientCar[]>();
  private seq = 0;
  private rnd: () => number;
  private p: Projector;
  private signals: TrafficSignals;
  private wetAt: (a: number, b: number) => boolean;

  constructor(data: Diorama, p: Projector, signals: TrafficSignals, wetAt: (a: number, b: number) => boolean) {
    this.p = p;
    this.signals = signals;
    this.wetAt = wetAt;
    let seed = 11;
    this.rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    this.build(data);
  }

  // ---------- road graph ----------

  private build(data: Diorama) {
    const ids = new Map<string, number>();
    const pos: Pt[] = [];
    const nbr: Array<Set<number>> = [];
    const vid = (a: number, b: number) => {
      const key = `${Math.round(a * 2)},${Math.round(b * 2)}`;
      let i = ids.get(key);
      if (i === undefined) {
        i = pos.length;
        ids.set(key, i);
        pos.push([a, b]);
        nbr.push(new Set());
      }
      return i;
    };
    const ways: Array<{ v: number[]; k: string; ow: number }> = [];
    for (const r of data.roads) {
      if (FOOT.has(r.k) || r.k === "parking_aisle" || !(r.k in SPEED)) continue;
      const v: number[] = [];
      for (const [lon, lat] of r.path) {
        const [a, b] = this.p.toAB(lon, lat);
        const i = vid(a, b);
        if (v[v.length - 1] !== i) v.push(i);
      }
      for (let j = 1; j < v.length; j++) {
        nbr[v[j]].add(v[j - 1]);
        nbr[v[j - 1]].add(v[j]);
      }
      if (v.length > 1) ways.push({ v, k: r.k, ow: r.ow ?? 0 });
    }
    // signal nodes are OSM vertices: the vertex nearest each junction within 12 m stands for it
    const signalAt = new Map<number, number>();
    this.signals.junctions.forEach((j, ji) => {
      let best = -1;
      let bd = 12;
      for (let i = 0; i < pos.length; i++) {
        const dd = Math.hypot(pos[i][0] - j.a, pos[i][1] - j.b);
        if (dd < bd && nbr[i].size) (bd = dd), (best = i);
      }
      if (best >= 0) signalAt.set(best, ji);
    });
    // links run between junctions (degree ≠ 2) and signals; split each way there
    const isKey = (i: number) => nbr[i].size !== 2 || signalAt.has(i);
    const nodeOf = new Map<number, number>();
    const { a0, a1, b0, b1 } = this.p.bounds;
    const node = (i: number) => {
      let n = nodeOf.get(i);
      if (n === undefined) {
        n = this.nodes.length;
        nodeOf.set(i, n);
        const [a, b] = pos[i];
        this.nodes.push({ a, b, links: [], signal: signalAt.get(i) ?? -1, edge: a < a0 + EDGE_M || a > a1 - EDGE_M || b < b0 + EDGE_M || b > b1 - EDGE_M });
      }
      return n;
    };
    const seen = new Set<string>();
    for (const w of ways) {
      let start = 0;
      for (let j = 1; j < w.v.length; j++) {
        if (j < w.v.length - 1 && !isKey(w.v[j])) continue;
        const vs = w.v.slice(start, j + 1);
        start = j;
        const key = vs[0] < vs[vs.length - 1] ? vs.join(",") : [...vs].reverse().join(",");
        if (seen.has(key)) continue;
        seen.add(key);
        const pts = vs.map((i) => pos[i]);
        const cum = [0];
        for (let q = 1; q < pts.length; q++) cum.push(cum[q - 1] + Math.hypot(pts[q][0] - pts[q - 1][0], pts[q][1] - pts[q - 1][1]));
        const len = cum[cum.length - 1];
        if (len < 0.5) continue;
        const L = this.links.length;
        const n0 = node(vs[0]);
        const n1 = node(vs[vs.length - 1]);
        const width = ROAD_W[w.k] ?? 5;
        this.links.push({ pts, cum, len, n: [n0, n1], k: w.k, v0: SPEED[w.k], off: Math.max(1.4, width / 4), ow: w.ow, lanes: w.ow && width >= 9 ? 2 : 1, trim: [0, 0] });
        this.nodes[n0].links.push(L);
        if (n1 !== n0) this.nodes[n1].links.push(L);
      }
    }
    // lanes stop short of a junction by its half-width, so turns sweep through the box
    for (const l of this.links) {
      const r = l.n.map((n) => {
        const nd = this.nodes[n];
        if (nd.links.length < 2) return 0;
        if (nd.links.length === 2) return nd.signal >= 0 ? 2.5 : 0.5;
        return Math.min(9, 1 + Math.max(...nd.links.map((x) => (ROAD_W[this.links[x].k] ?? 5) / 2)));
      });
      const room = Math.max(0, l.len - 1);
      const k = r[0] + r[1] > room ? room / (r[0] + r[1]) : 1;
      l.trim = [r[0] * k, r[1] * k];
    }
    let acc = 0;
    this.pick = this.links.map((l) => (acc += l.len * WEIGHT[l.k]));
  }

  /** Lane centre at distance s along link L travelled in direction d, and the travel direction there. */
  private lane(L: number, d: 1 | -1, s: number, ln = 0): [number, number, number, number] {
    const l = this.links[L];
    const along = Math.max(0, Math.min(l.len, d > 0 ? s : l.len - s));
    let i = 1;
    while (i < l.cum.length - 1 && l.cum[i] < along) i++;
    const [pa, pb] = l.pts[i - 1];
    const [qa, qb] = l.pts[i];
    const seg = l.cum[i] - l.cum[i - 1] || 1;
    const f = (along - l.cum[i - 1]) / seg;
    const ua = ((qa - pa) / seg) * d;
    const ub = ((qb - pb) / seg) * d;
    // drive on the right: right of (ua, ub) is (-ub, ua) with b pointing south; one-way roads use their width
    const off = !l.ow ? l.off : l.lanes === 2 ? (ln ? 1 : -1) * ((ROAD_W[l.k] ?? 5) / 5) : 0;
    return [pa + (qa - pa) * f - ub * off, pb + (qb - pb) * f + ua * off, ua, ub];
  }

  private start(L: number, d: 1 | -1) {
    return this.links[L].trim[d > 0 ? 0 : 1];
  }

  private end(L: number, d: 1 | -1) {
    const l = this.links[L];
    return l.len - l.trim[d > 0 ? 1 : 0];
  }

  private endNode(L: number, d: 1 | -1) {
    return this.links[L].n[d > 0 ? 1 : 0];
  }

  /** Choose where to go from the end of (L, d): prefer straight on and bigger roads, never into the flood. */
  private choose(L: number, d: 1 | -1, ln = 0): Turn | null {
    const n = this.endNode(L, d);
    const nd = this.nodes[n];
    const e = this.end(L, d);
    const [a0, b0, ua, ub] = this.lane(L, d, e, ln);
    const opts: Array<{ L: number; d: 1 | -1; w: number }> = [];
    for (const M of nd.links) {
      const ml = this.links[M];
      for (const md of [1, -1] as const) {
        if (ml.n[md > 0 ? 0 : 1] !== n || (M === L && md === -d) || (ml.ow && ml.ow !== md)) continue;
        const [sa, sb, va, vb] = this.lane(M, md, this.start(M, md) + 6);
        if (this.wetAt(sa, sb)) continue;
        const straight = ua * va + ub * vb;
        opts.push({ L: M, d: md, w: (0.25 + Math.max(0, straight) * 1.75) * WEIGHT[ml.k] });
      }
    }
    let to: { L: number; d: 1 | -1 };
    if (opts.length) {
      let r = this.rnd() * opts.reduce((x, o) => x + o.w, 0);
      to = opts[opts.length - 1];
      for (const o of opts) if ((r -= o.w) <= 0) { to = o; break; }
    } else {
      if ((nd.edge && nd.links.length === 1) || this.links[L].ow) return null; // off the stage (or no turning on a one-way)
      to = { L, d: d > 0 ? -1 : 1 }; // a dead end or water: turn around
    }
    const lanes = this.links[to.L].lanes;
    const nl = lanes === 1 ? 0 : this.links[L].lanes === 2 ? ln : this.rnd() < 0.5 ? 0 : 1;
    const s2 = this.start(to.L, to.d);
    const [c2a, c2b, va, vb] = this.lane(to.L, to.d, s2, nl);
    const p0: Pt = [a0, b0];
    const p2: Pt = [c2a, c2b];
    // control point: where the two lane lines meet (a straight run: halfway)
    const cross = ua * vb - ub * va;
    let c: Pt = [(a0 + c2a) / 2, (b0 + c2b) / 2];
    if (to.L === L) c = [c[0] + ua * this.links[L].off * 1.5, c[1] + ub * this.links[L].off * 1.5];
    else if (Math.abs(cross) > 0.2) {
      const t = ((c2a - a0) * vb - (c2b - b0) * va) / cross;
      if (t > 0 && t < 25) c = [a0 + ua * t, b0 + ub * t];
    }
    let len = 0;
    let q = p0;
    for (let i = 1; i <= 6; i++) {
      const r = bez(p0, c, p2, i / 6);
      len += Math.hypot(r[0] - q[0], r[1] - q[1]);
      q = r;
    }
    const sharp = 1 - Math.max(0, ua * va + ub * vb); // 0 straight, 1 a right angle, 2 a U-turn
    const pts: Pt[] = [];
    for (let i = 0; i <= 8; i++) pts.push(bez(p0, c, p2, i / 8));
    return { L: to.L, d: to.d, ln: nl, p0, c, p2, len: Math.max(0.5, len), slow: sharp < 0.3 ? Infinity : Math.max(3, 9 - sharp * 4), pts };
  }

  // ---------- population ----------

  private spawn(view: { x0: number; y0: number; x1: number; y1: number } | null): boolean {
    const total = this.pick[this.pick.length - 1];
    for (let tries = 0; tries < 24; tries++) {
      const u = this.rnd() * total;
      let lo = 0;
      let hi = this.pick.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (this.pick[mid] < u) lo = mid + 1;
        else hi = mid;
      }
      const L = lo;
      const ow = this.links[L].ow;
      const d: 1 | -1 = ow ? (ow > 0 ? 1 : -1) : this.rnd() < 0.5 ? 1 : -1;
      const ln = this.links[L].lanes === 2 && this.rnd() < 0.5 ? 1 : 0;
      const s0 = this.start(L, d);
      const s1 = this.end(L, d);
      if (s1 - s0 < LEN) continue;
      const s = s0 + this.rnd() * (s1 - s0);
      const [a, b, ua, ub] = this.lane(L, d, s, ln);
      if (this.wetAt(a, b)) continue;
      if (view) {
        const [x, y] = this.p.iso(a, b);
        if (x > view.x0 - 20 && x < view.x1 + 20 && y > view.y0 - 20 && y < view.y1 + 20) continue; // never pop in on screen
      }
      const lane = this.cars.filter((c) => c.L === L && c.d === d && c.ln === ln);
      if (lane.some((c) => Math.abs(c.s - s) < LEN * 3)) continue;
      const id = this.seq++;
      const car: AmbientCar = { id, L, d, ln, s, v: SPEED[this.links[L].k] * (0.4 + 0.5 * this.rnd()), acc: 0, next: null, passed: -1, arrive: Infinity, granted: false, stuck: 0, a, b, ua, ub, color: id };
      car.next = this.choose(L, d, ln);
      this.cars.push(car);
      return true;
    }
    return false;
  }

  /** Cars wanted at replay time t: everyday traffic that empties out as the evacuation runs and the water rises. */
  static target(t: number) {
    const f = Math.max(0, Math.min(1, (t - 1800) / 6000));
    return Math.round(AMBIENT_CARS * (1 - 0.8 * f));
  }

  // ---------- motion ----------

  /** Advance by dt seconds of wall clock; `now` drives the lights, `t` (replay) the population. */
  step(dt: number, now: number, t: number, view: { x0: number; y0: number; x1: number; y1: number }, others: Other[] = []) {
    if (!this.links.length) return;
    this.indexOthers(others);
    dt = Math.min(0.1, Math.max(0, dt));
    const want = AmbientTraffic.target(t);
    if (!this.cars.length) while (this.cars.length < want && this.spawn(null));
    else if (this.cars.length < want) this.spawn(view);
    else if (this.cars.length > want) {
      // leave quietly: the first car off screen goes
      const i = this.cars.findIndex((c) => !this.inView(c, view));
      this.cars.splice(i >= 0 ? i : 0, 1);
    }
    // lanes, front to back
    this.lanes.clear();
    for (const c of this.cars) {
      const key = laneKey(c.L, c.d, c.ln);
      let arr = this.lanes.get(key);
      if (!arr) this.lanes.set(key, (arr = []));
      arr.push(c);
    }
    for (const arr of this.lanes.values()) arr.sort((x, y) => y.s - x.s);
    // junction boxes: who is in (or cleared into) each, and who is waiting at its line
    this.box.clear();
    this.waiting.clear();
    for (const c of this.cars) {
      if (!c.next) continue;
      const n = this.endNode(c.L, c.d);
      const e = this.end(c.L, c.d);
      if (c.s > e || c.granted) push(this.box, n, c);
      else if (e - c.s < QUEUE_M && c.v < 3) {
        if (c.arrive === Infinity) c.arrive = now;
        if (!this.redFor(c, now)) push(this.waiting, n, c);
      }
    }
    const gone: AmbientCar[] = [];
    for (const arr of this.lanes.values()) {
      for (let i = 0; i < arr.length; i++) {
        const c = arr[i];
        const l = this.links[c.L];
        const e = this.end(c.L, c.d);
        const exit = e + (c.next?.len ?? 0);
        let gap = Infinity;
        let lv = 0;
        if (i > 0) {
          gap = arr[i - 1].s - c.s - LEN;
          lv = arr[i - 1].v;
        } else if (c.next) {
          const ahead = this.lanes.get(laneKey(c.next.L, c.next.d, c.next.ln));
          const last = ahead?.[ahead.length - 1];
          if (last) {
            gap = exit - c.s + (last.s - this.start(c.next.L, c.next.d)) - LEN;
            lv = last.v;
          }
        }
        {
          const og = this.otherAhead(c);
          if (og < gap) (gap = og), (lv = 0);
        }
        let v0 = l.v0;
        if (c.s <= e) {
          // the stop line: red, or amber with room to stop
          const nd = this.nodes[this.endNode(c.L, c.d)];
          if (nd.signal >= 0 && nd.signal !== c.passed) {
            const [, , ua, ub] = this.lane(c.L, c.d, e);
            const st = this.signals.stateFor(nd.signal, ua, ub, now);
            const toLine = e - c.s - 0.5;
            if (st === 2 || (st === 1 && toLine > (c.v * c.v) / (2 * DEC) + 1)) {
              if (toLine < gap) (gap = toLine), (lv = 0);
            }
          }
          // the box: wait at the line until this car's path through it is clear
          if (c.next && !c.granted && gap > e - c.s - 0.5) {
            const toLine = e - c.s - 0.5;
            const n = this.endNode(c.L, c.d);
            if (this.clear(c, n)) {
              if (toLine <= (c.v * c.v) / (2 * DEC) + 2) {
                c.granted = true;
                push(this.box, n, c);
              }
            } else if (toLine < gap) (gap = Math.max(0, toLine)), (lv = 0);
          }
          if (!c.next) {
            // off the stage at the end of this lane
          } else if (c.next.slow < v0) v0 = Math.min(v0, c.next.slow + (e - c.s) * 0.35);
        } else if (c.next) v0 = Math.min(v0, c.next.slow);
        // intelligent-driver model
        const sStar = GAP0 + c.v * HEADWAY + (c.v * (c.v - lv)) / (2 * Math.sqrt(ACC * DEC));
        let acc = ACC * (1 - (c.v / v0) ** 4) - (gap < Infinity ? ACC * (sStar / Math.max(0.1, gap)) ** 2 : 0);
        acc = Math.max(-9, acc);
        c.acc = acc;
        c.v = Math.max(0, c.v + acc * dt);
        if (gap < 0.05) c.v = 0;
        c.s += c.v * dt;
        c.stuck = c.v < 0.1 ? c.stuck + dt : 0;
        // the water ahead: turn around
        if (c.s < e - 8) {
          const [fa, fb] = this.lane(c.L, c.d, c.s + 8, c.ln);
          if (this.wetAt(fa, fb) && l.ow) {
            gone.push(c); // no turning on a one-way: it leaves
            continue;
          } else if (this.wetAt(fa, fb)) {
            c.ln = 0;
            c.d = c.d > 0 ? -1 : 1;
            c.s = Math.max(this.start(c.L, c.d), l.len - c.s);
            c.v *= 0.3;
            c.next = this.choose(c.L, c.d, c.ln);
            c.arrive = Infinity;
            c.granted = false;
          }
        }
        if (c.s >= exit) {
          if (!c.next) {
            gone.push(c);
            continue;
          }
          const nd = this.nodes[this.endNode(c.L, c.d)];
          if (nd.signal >= 0) c.passed = nd.signal;
          const over = c.s - exit;
          c.L = c.next.L;
          c.d = c.next.d;
          c.ln = c.next.ln;
          c.s = this.start(c.L, c.d) + over;
          c.next = this.choose(c.L, c.d, c.ln);
          c.arrive = Infinity;
          c.granted = false;
        }
        if (c.stuck > 45) gone.push(c); // a knot that will not clear: tow it
        else if (this.wetAt(c.a, c.b)) gone.push(c); // the water rose under it (or the replay jumped): gone
        // render position
        if (c.s > e && c.next) {
          const u = Math.min(1, (c.s - e) / c.next.len);
          const [a, b] = bez(c.next.p0, c.next.c, c.next.p2, u);
          const [na, nb] = bez(c.next.p0, c.next.c, c.next.p2, Math.min(1, u + 0.05));
          const dl = Math.hypot(na - a, nb - b);
          c.a = a;
          c.b = b;
          if (dl > 1e-4) (c.ua = (na - a) / dl), (c.ub = (nb - b) / dl);
        } else {
          const [a, b, ua, ub] = this.lane(c.L, c.d, c.s, c.ln);
          c.a = a;
          c.b = b;
          c.ua = ua;
          c.ub = ub;
        }
      }
    }
    if (gone.length) {
      const g = new Set(gone);
      for (let i = this.cars.length - 1; i >= 0; i--) if (g.has(this.cars[i])) this.cars.splice(i, 1);
    }
  }

  private box = new Map<number, AmbientCar[]>();
  private waiting = new Map<number, AmbientCar[]>();
  private grid = new Map<number, Other[]>();

  private redFor(c: AmbientCar, now: number) {
    const nd = this.nodes[this.endNode(c.L, c.d)];
    if (nd.signal < 0 || nd.signal === c.passed) return false;
    const [, , ua, ub] = this.lane(c.L, c.d, this.end(c.L, c.d));
    return this.signals.stateFor(nd.signal, ua, ub, now) !== 0;
  }

  /** May c enter the box at node n now? Not across a car in it, a car waiting longer, or an evacuation car. */
  private clear(c: AmbientCar, n: number) {
    const mine = c.next!;
    const same = (o: AmbientCar) => o === c || (o.L === c.L && o.d === c.d);
    for (const o of this.box.get(n) ?? []) if (!same(o) && o.next && crosses(o.next.pts, mine.pts)) return false;
    for (const w of this.waiting.get(n) ?? []) {
      if (same(w) || !w.next) continue;
      if ((w.arrive < c.arrive || (w.arrive === c.arrive && w.id < c.id)) && crosses(w.next.pts, mine.pts)) return false;
    }
    for (const q of mine.pts) for (const o of this.near(q[0], q[1])) if (Math.hypot(o.a - q[0], o.b - q[1]) < CLEAR_M + 1) return false;
    return true;
  }

  private indexOthers(others: Other[]) {
    this.grid.clear();
    for (const o of others) push(this.grid, cell(o.a, o.b), o);
  }

  private near(a: number, b: number): Other[] {
    if (!this.grid.size) return [];
    const out: Other[] = [];
    const cx = Math.floor(a / 10);
    const cy = Math.floor(b / 10);
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      const g = this.grid.get((cx + dx) * 100003 + (cy + dy));
      if (g) out.push(...g);
    }
    return out;
  }

  /** Gap to the nearest evacuation car ahead in this car's lane (Infinity if none within 20 m). */
  private otherAhead(c: AmbientCar): number {
    if (!this.grid.size) return Infinity;
    let gap = Infinity;
    for (const o of this.near(c.a + c.ua * 10, c.b + c.ub * 10)) {
      const ra = o.a - c.a;
      const rb = o.b - c.b;
      const along = ra * c.ua + rb * c.ub;
      if (along <= 0 || along > 20 || Math.abs(ra * c.ub - rb * c.ua) > 1.7 || o.ua * c.ua + o.ub * c.ub < 0.3) continue;
      gap = Math.min(gap, along - LEN);
    }
    return gap;
  }

  private inView(c: AmbientCar, view: { x0: number; y0: number; x1: number; y1: number }) {
    const [x, y] = this.p.iso(c.a, c.b);
    return x > view.x0 - 20 && x < view.x1 + 20 && y > view.y0 - 20 && y < view.y1 + 20;
  }
}

function push<K, V>(m: Map<K, V[]>, k: K, v: V) {
  const arr = m.get(k);
  if (arr) arr.push(v);
  else m.set(k, [v]);
}

const cell = (a: number, b: number) => Math.floor(a / 10) * 100003 + Math.floor(b / 10);

/** Do two paths through a box come within CLEAR_M of each other? */
function crosses(p: Pt[], q: Pt[]) {
  for (const [a, b] of p) for (const [c, d] of q) if (Math.abs(a - c) < CLEAR_M && Math.abs(b - d) < CLEAR_M && Math.hypot(a - c, b - d) < CLEAR_M) return true;
  return false;
}

const laneKey = (L: number, d: 1 | -1, ln: number) => (L * 2 + (d > 0 ? 1 : 0)) * 2 + ln;

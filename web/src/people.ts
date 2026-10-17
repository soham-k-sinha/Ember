/**
 * The street-level crowd. Everything here is ILLUSTRATIVE and labelled so in the UI (CLAUDE.md rule 10):
 * the engine simulates the 40 assisted households and the fleet; this module draws the people
 * around them so the scene reads like a neighbourhood during a flood.
 *
 * - Assisted households: one figure per person at their door until picked up (status from the sim).
 * - Self-evacuating neighbours ("walkers"): a deterministic share of background households leave on
 *   foot before the water reaches their street, routed with a time-dependent shortest path that
 *   refuses edges flooded by the time they would get there. A quarter don't plan ahead: they take the
 *   direct route and turn back when they reach water.
 * - The shelter crowd: people dropped off by vans (sim) plus walkers who reached the shelter.
 *
 * Positions are pure functions of (household id, clock), so scrubbing is consistent and nothing is stored.
 */

import { lineIntersectsGeometry } from "./geo";
import { floorIndex, poseAt } from "./playback";
import type { FloodGeometry, LngLat, ScenarioKeyframe, TownEdge, TownNode } from "./types";

export type BgHousehold = { id: number; lon: number; lat: number; node: number; size: number; vehicles?: number; flags?: Record<string, boolean> };

export type Walker = {
  id: string;
  household: number;
  group: number; // index within the household group
  size: number;
  path: LngLat[];
  times: number[];
  start: number;
  end: number;
  dest: "shelter" | "exit" | "home";
  turnedBack: boolean;
  offset: LngLat;
};

// ---------- deterministic randomness ----------
export function hash(n: number, salt = 0): number {
  let x = (n ^ (salt * 0x9e3779b1)) >>> 0;
  x = Math.imul(x ^ (x >>> 16), 0x7feb352d) >>> 0;
  x = Math.imul(x ^ (x >>> 15), 0x846ca68b) >>> 0;
  x = (x ^ (x >>> 16)) >>> 0;
  return x / 4294967296;
}

const FIRST = ["Maya", "Luis", "Grace", "Omar", "Priya", "Daniel", "Rosa", "Kwame", "Hannah", "Tomás", "Mei", "Samuel", "Aisha", "Patrick", "Lena", "Diego", "Ruth", "Arjun", "Nora", "Elijah", "Fatima", "Walter", "Sofia", "Jin", "Beatriz", "Marcus", "Ines", "Theo", "Amara", "Frank"];
const LAST = ["Okafor", "Silva", "Nguyen", "Brennan", "Patel", "Haddad", "Kowalski", "Mendes", "Chen", "Duarte", "O'Neill", "Ramos", "Kim", "Shapiro", "Ferreira", "Mensah", "Park", "Costa", "Murphy", "Abebe"];

export function surname(id: number): string {
  return LAST[Math.floor(hash(id, 11) * LAST.length)];
}

export function householdName(id: number): string {
  return `The ${surname(id)} household`;
}

export type Member = { name: string; role: string; mobility: boolean };

/** Synthetic members for an assisted household: count and mobility from the sim's needs. */
export function members(id: number, people: number, mobility: boolean, medical: boolean): Member[] {
  const last = surname(id);
  const out: Member[] = [];
  for (let i = 0; i < Math.max(1, people); i++) {
    const first = FIRST[Math.floor(hash(id * 7 + i, 13) * FIRST.length)];
    const elder = (mobility && i === 0) || hash(id * 7 + i, 17) < 0.18;
    const child = !elder && i > 1 && hash(id * 7 + i, 19) < 0.5;
    out.push({
      name: `${first} ${last}`,
      role: elder ? (mobility && i === 0 ? "uses a wheelchair" : "older adult") : child ? "child" : medical && i === 0 ? "needs medication" : "adult",
      mobility: mobility && i === 0,
    });
  }
  return out;
}

// ---------- metres ↔ degrees near Allston ----------
const LAT0 = 42.36;
const M_LON = 111_320 * Math.cos((LAT0 * Math.PI) / 180);
const M_LAT = 110_540;

export function offsetMetres(p: LngLat, dx: number, dy: number): LngLat {
  return [p[0] + dx / M_LON, p[1] + dy / M_LAT];
}

function metres(a: LngLat, b: LngLat): number {
  return Math.hypot((b[0] - a[0]) * M_LON, (b[1] - a[1]) * M_LAT);
}

/** Small ring around a point for a group of n people (metres). */
export function cluster(center: LngLat, n: number, seed: number, radius = 2.2): LngLat[] {
  const out: LngLat[] = [];
  for (let i = 0; i < n; i++) {
    const a = hash(seed, i + 1) * Math.PI * 2;
    const r = i === 0 ? 0.6 : radius * (0.6 + 0.5 * hash(seed, i + 31));
    out.push(offsetMetres(center, Math.cos(a) * r, Math.sin(a) * r));
  }
  return out;
}

// ---------- road graph for walkers ----------
type Graph = {
  nodeIndex: Map<number, number>;
  pos: LngLat[];
  adj: Array<Array<{ to: number; edge: number; len: number; forward: boolean }>>;
  edges: TownEdge[];
  floodAt: Float64Array; // first time each edge is under water (Infinity = never)
};

export function buildGraph(nodes: TownNode[], edges: TownEdge[], keyframes: ScenarioKeyframe[], closures?: Array<[number, number, number | null]>): Graph {
  const nodeIndex = new Map<number, number>(nodes.map((node, i) => [node.id, i]));
  const pos: LngLat[] = nodes.map((node) => [node.lon, node.lat]);
  const adj: Graph["adj"] = nodes.map(() => []);
  const floodAt = new Float64Array(edges.length).fill(Infinity);
  if (closures && closures.length > 0) {
    for (const [edgeId, from] of closures) if (edgeId < floodAt.length) floodAt[edgeId] = Math.min(floodAt[edgeId], from);
  } else {
    for (const frame of keyframes) {
      for (const edge of edges) {
        if (floodAt[edge.id] === Infinity && lineIntersectsGeometry(edge.geom, frame.geometry as FloodGeometry)) floodAt[edge.id] = frame.t_s;
      }
    }
  }
  const seen = new Set<string>();
  for (const edge of edges) {
    const u = nodeIndex.get(edge.u);
    const v = nodeIndex.get(edge.v);
    if (u == null || v == null) continue;
    const key = u < v ? `${u}-${v}` : `${v}-${u}`;
    // footpaths: a two-way street is two directed edges; walkers use each pair once, both ways
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    adj[u].push({ to: v, edge: edge.id, len: edge.length_m, forward: true });
    adj[v].push({ to: u, edge: edge.id, len: edge.length_m, forward: false });
  }
  // a flooded twin closes the footpath too
  for (const edge of edges) {
    const u = nodeIndex.get(edge.u);
    const v = nodeIndex.get(edge.v);
    if (u == null || v == null) continue;
    for (const step of adj[u]) if (step.to === v && step.edge !== edge.id) floodAt[step.edge] = Math.min(floodAt[step.edge], floodAt[edge.id]);
    for (const step of adj[v]) if (step.to === u && step.edge !== edge.id) floodAt[step.edge] = Math.min(floodAt[step.edge], floodAt[edge.id]);
  }
  return { nodeIndex, pos, adj, edges, floodAt };
}

/** Earliest-arrival Dijkstra on foot from `src` at `t0`; an edge is usable if it is still dry when entered (+margin). */
function earliest(graph: Graph, src: number, t0: number, speed: number, aware: boolean): { at: Float64Array; prev: Int32Array; via: Int32Array } {
  const n = graph.pos.length;
  const at = new Float64Array(n).fill(Infinity);
  const prev = new Int32Array(n).fill(-1);
  const via = new Int32Array(n).fill(-1);
  at[src] = t0;
  const heap: Array<[number, number]> = [[t0, src]];
  const push = (item: [number, number]) => {
    heap.push(item);
    let i = heap.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (heap[p][0] <= heap[i][0]) break;
      [heap[p], heap[i]] = [heap[i], heap[p]];
      i = p;
    }
  };
  const pop = (): [number, number] | undefined => {
    const top = heap[0];
    const last = heap.pop();
    if (heap.length > 0 && last) {
      heap[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < heap.length && heap[l][0] < heap[m][0]) m = l;
        if (r < heap.length && heap[r][0] < heap[m][0]) m = r;
        if (m === i) break;
        [heap[m], heap[i]] = [heap[i], heap[m]];
        i = m;
      }
    }
    return top;
  };
  for (let item = pop(); item; item = pop()) {
    const [t, u] = item;
    if (t > at[u]) continue;
    for (const step of graph.adj[u]) {
      if (aware && graph.floodAt[step.edge] <= t + 120) continue;
      const arrive = t + step.len / speed;
      if (arrive < at[step.to]) {
        at[step.to] = arrive;
        prev[step.to] = u;
        via[step.to] = step.edge;
        push([arrive, step.to]);
      }
    }
  }
  return { at, prev, via };
}

function edgePoints(graph: Graph, edgeId: number, fromNode: number): LngLat[] {
  const edge = graph.edges[edgeId];
  const forward = graph.nodeIndex.get(edge.u) === fromNode;
  return forward ? edge.geom : [...edge.geom].reverse();
}

function polyline(graph: Graph, nodesPath: number[], edgesPath: number[]): LngLat[] {
  const pts: LngLat[] = [graph.pos[nodesPath[0]]];
  for (let i = 0; i < edgesPath.length; i++) {
    const geom = edgePoints(graph, edgesPath[i], nodesPath[i]);
    for (let j = 1; j < geom.length; j++) pts.push(geom[j]);
  }
  return pts;
}

function timed(points: LngLat[], start: number, speed: number): number[] {
  const times = [start];
  for (let i = 1; i < points.length; i++) times.push(times[i - 1] + metres(points[i - 1], points[i]) / speed);
  return times;
}

function unwind(prev: Int32Array, via: Int32Array, dst: number): { nodes: number[]; edges: number[] } {
  const nodes = [dst];
  const edges: number[] = [];
  for (let u = dst; prev[u] >= 0; u = prev[u]) {
    edges.push(via[u]);
    nodes.push(prev[u]);
  }
  return { nodes: nodes.reverse(), edges: edges.reverse() };
}

export type WalkerPlan = {
  walkers: Walker[];
  departed: Map<number, number>; // household → when its group left (for porch gathering)
};

/** Who walks out, when, and where. Deterministic in the household ids. */
export function planWalkers(args: {
  households: BgHousehold[];
  assisted: Set<number>;
  graph: Graph;
  shelterNode: number | null;
  exitNodes: number[];
  share?: number;
}): WalkerPlan {
  const { households, assisted, graph, shelterNode } = args;
  const share = args.share ?? 0.07;
  const shelter = shelterNode != null ? graph.nodeIndex.get(shelterNode) ?? null : null;
  const exits = args.exitNodes.map((id) => graph.nodeIndex.get(id)).filter((i): i is number => i != null);
  // when does the water reach each node?
  const nodeFlood = new Float64Array(graph.pos.length).fill(Infinity);
  graph.adj.forEach((steps, u) => {
    for (const step of steps) nodeFlood[u] = Math.min(nodeFlood[u], graph.floodAt[step.edge]);
  });
  const walkers: Walker[] = [];
  const departed = new Map<number, number>();
  for (const household of households) {
    if (assisted.has(household.id)) continue;
    const src = graph.nodeIndex.get(household.node);
    if (src == null) continue;
    const threatened = nodeFlood[src] < Infinity;
    const p = hash(household.id, 3);
    if (p > (threatened ? share * 3.2 : share * 0.35)) continue;
    const lead = 15 * 60 + hash(household.id, 5) * 55 * 60;
    const start = Math.max(4 * 60, threatened ? nodeFlood[src] - lead : 25 * 60 + hash(household.id, 7) * 120 * 60);
    const speed = 1.05 + hash(household.id, 9) * 0.45;
    const aware = hash(household.id, 21) > 0.25;
    const size = Math.max(1, Math.min(4, household.size));

    const reach = earliest(graph, src, start, speed, true);
    let dst = -1;
    let dest: Walker["dest"] = "home";
    if (shelter != null && reach.at[shelter] < Infinity && reach.at[shelter] - start < 40 * 60) {
      dst = shelter;
      dest = "shelter";
    } else {
      let best = Infinity;
      for (const exit of exits) {
        if (reach.at[exit] < best) {
          best = reach.at[exit];
          dst = exit;
        }
      }
      if (dst >= 0) dest = "exit";
    }
    if (dst < 0 || dst === src) continue; // cut off: they shelter in place

    let points: LngLat[];
    let times: number[];
    let turnedBack = false;
    if (aware) {
      const route = unwind(reach.prev, reach.via, dst);
      points = polyline(graph, route.nodes, route.edges);
      times = timed(points, start, speed);
    } else {
      // the direct route, ignoring what the water will do; turn back at the first flooded edge
      const blind = earliest(graph, src, start, speed, false);
      const route = unwind(blind.prev, blind.via, dst);
      let t = start;
      let cut = route.edges.length;
      for (let i = 0; i < route.edges.length; i++) {
        if (graph.floodAt[route.edges[i]] <= t) {
          cut = i;
          break;
        }
        t += graph.edges[route.edges[i]].length_m / speed;
      }
      if (cut === route.edges.length) {
        points = polyline(graph, route.nodes, route.edges);
        times = timed(points, start, speed);
      } else {
        const out = polyline(graph, route.nodes.slice(0, cut + 1), route.edges.slice(0, cut));
        const edge = route.edges[cut];
        const into = edgePoints(graph, edge, route.nodes[cut]);
        const peek = into.slice(0, Math.max(2, Math.ceil(into.length / 3)));
        const there = [...out, ...peek.slice(1)];
        const back = [...there].reverse().slice(1);
        points = [...there, ...back];
        times = timed(points, start, speed * 0.9);
        // a short pause at the water's edge
        const turn = there.length - 1;
        for (let i = turn; i < times.length; i++) times[i] += 25;
        turnedBack = true;
        dest = "home";
      }
    }
    if (points.length < 2) continue;
    departed.set(household.id, start);
    for (let g = 0; g < size; g++) {
      const a = hash(household.id, 40 + g) * Math.PI * 2;
      const r = g === 0 ? 0 : 1.1 + hash(household.id, 50 + g);
      walkers.push({
        id: `${household.id}:${g}`,
        household: household.id,
        group: g,
        size,
        path: points,
        times: times.map((x) => x + g * 1.5),
        start: start + g * 1.5,
        end: times[times.length - 1] + g * 1.5,
        dest,
        turnedBack,
        offset: [(Math.cos(a) * r) / M_LON, (Math.sin(a) * r) / M_LAT],
      });
    }
  }
  return { walkers, departed };
}

export type WalkerPose = { walker: Walker; position: LngLat; heading: number; frame: "walk1" | "walk2" | "stand" };

export function walkersAt(plan: WalkerPlan, t: number, bounds: [number, number, number, number] | null): WalkerPose[] {
  const out: WalkerPose[] = [];
  for (const walker of plan.walkers) {
    if (t < walker.start || t > walker.end) continue;
    const pose = poseAt(walker.path, walker.times, t);
    const position: LngLat = [pose.position[0] + walker.offset[0], pose.position[1] + walker.offset[1]];
    if (bounds && (position[0] < bounds[0] || position[0] > bounds[2] || position[1] < bounds[1] || position[1] > bounds[3])) continue;
    const step = Math.floor(t / 0.6 + walker.group) % 2;
    out.push({ walker, position, heading: pose.heading, frame: pose.moving ? (step ? "walk1" : "walk2") : "stand" });
  }
  return out;
}

/** Walkers that have reached the shelter by t. */
export function arrivedAtShelter(plan: WalkerPlan, t: number): number {
  let n = 0;
  for (const walker of plan.walkers) if (walker.dest === "shelter" && walker.end <= t) n++;
  return n;
}

/** Groups gathering at their door in the 6 minutes before they set off. */
export function gathering(plan: WalkerPlan, households: Map<number, BgHousehold>, t: number): Array<{ household: BgHousehold; size: number }> {
  const out: Array<{ household: BgHousehold; size: number }> = [];
  for (const [id, start] of plan.departed) {
    if (t >= start - 6 * 60 && t < start) {
      const household = households.get(id);
      if (household) out.push({ household, size: Math.max(1, Math.min(4, household.size)) });
    }
  }
  return out;
}

/** Spiral of positions around a point for a crowd of n (metres apart). */
export function crowd(center: LngLat, n: number, spacing = 1.7): LngLat[] {
  const out: LngLat[] = [];
  for (let i = 0; i < n; i++) {
    const r = spacing * Math.sqrt(i + 1) * 0.62;
    const a = i * 2.399963 + hash(i, 61) * 0.4;
    out.push(offsetMetres(center, Math.cos(a) * r, Math.sin(a) * r));
  }
  return out;
}

export function countWalking(plan: WalkerPlan, t: number): { walking: number; turnedBack: number; sheltered: number; left: number } {
  let walking = 0;
  let turnedBack = 0;
  let sheltered = 0;
  let left = 0;
  for (const walker of plan.walkers) {
    if (t >= walker.start && t <= walker.end) {
      walking++;
      if (walker.turnedBack) {
        const i = floorIndex(walker.times, t);
        if (i >= walker.path.length / 2) turnedBack++;
      }
    } else if (t > walker.end) {
      if (walker.dest === "shelter") sheltered++;
      else if (walker.dest === "exit") left++;
    }
  }
  return { walking, turnedBack, sheltered, left };
}

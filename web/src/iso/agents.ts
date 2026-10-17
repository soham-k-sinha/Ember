/**
 * Who stands where on the stage, frame by frame, from data the engine already produced (D52):
 *  - households waiting outside their building (on the pavement toward their street), facing the
 *    street, then the van once it has arrived for them;
 *  - boarding: in the minute before the engine's pickup, members walk one by one from where they
 *    waited to the parked van's door and get in;
 *  - getting out: after the engine's drop-off, they walk from the van into the nearest facility;
 *  - the shelter crowd (the engine's people_on_site plus neighbours who walked there), milling — illustrative;
 *  - neighbours on foot (the walker plan) — illustrative;
 *  - passers-by on the pavements and paths, walking at real pace from the start and thinning out
 *    as the flood rises; never on water — illustrative, so the city is alive before anyone leaves.
 * All times come from the playback (pickup / drop-off events, vehicle tracks); this only acts them out.
 */

import type { Shape } from "./atlas";
import type { Agent } from "./crowd";
import type { Projector } from "./project";
import { curb, householdColor, peopleCount, type LegendMode } from "../layers";
import { arrivedAtShelter, cluster, crowd, walkersAt, type WalkerPlan } from "../people";
import { poseAt, type Playback, type Track } from "../playback";
import type { Diorama } from "./data";
import { FOOT, ROAD_W } from "./ground";
import type { ScenarioKeyframe, StateHousehold, StateSnapshot } from "../types";
import { inCrowdView, MAX_STROLLERS, type CrowdView } from "./density";

type Leg = { rid: string; arrive: number; pickup: number; dropoff: number | null };

export type AgentWorld = {
  p: Projector;
  insideBuilding: (a: number, b: number) => boolean;
  onRoad: (a: number, b: number) => boolean;
  legs: Map<number, Leg>;
  tracks: Map<string, Track>;
  spots: Map<number, [number, number]>; // household → where its people wait (a, b)
  outside: Map<string, [number, number]>; // facility → a standing spot outside it (a, b)
  strolls: Stroll[]; // pavement and path routes for passers-by
  strollCum: number[];
  strollers: Stroller[]; // stable route/phase choices, computed once instead of every frame
  flood: Array<{ t: number; rings: Array<Array<[number, number]>> }>; // flood keyframes in (a, b)
};

type Stroll = { pts: Array<[number, number]>; cum: number[]; len: number; w: number };
type Stroller = { id: number; route: Stroll; speed: number; pause: number; phase: number; priority: number };
const CLOTH = [0x8a94a6, 0x6f7f96, 0xb39b7d, 0x9a6b5a, 0x5d7a6a, 0xc9c2b4, 0x7b6f8f, 0x4f5d75, 0xa88a5c, 0x6a8caf];

/** Pavement lines (both sides of each street, kerb + 1.8 m) and footpaths, in ground metres. */
export function strollRoutes(data: Diorama, p: Projector, insideBuilding: (a: number, b: number) => boolean): Stroll[] {
  const out: Stroll[] = [];
  const push = (pts: Array<[number, number]>) => {
    const keep = pts.filter(([a, b]) => !insideBuilding(a, b));
    if (keep.length < 2) return;
    const cum = [0];
    for (let i = 1; i < keep.length; i++) cum.push(cum[i - 1] + Math.hypot(keep[i][0] - keep[i - 1][0], keep[i][1] - keep[i - 1][1]));
    if (cum[cum.length - 1] > 25) out.push({ pts: keep, cum, len: cum[cum.length - 1], w: 1 });
  };
  for (const road of data.roads) {
    const ab = road.path.map(([lon, lat]) => p.toAB(lon, lat));
    if (FOOT.has(road.k)) {
      if (road.k !== "steps") push(ab);
      continue;
    }
    if (road.k === "motorway" || road.k === "trunk" || road.k === "parking_aisle") continue;
    const off = (ROAD_W[road.k] ?? 5) / 2 + 1.8;
    for (const side of [1, -1]) {
      const line: Array<[number, number]> = ab.map(([a, b], i) => {
        const [pa, pb] = ab[Math.max(0, i - 1)];
        const [qa, qb] = ab[Math.min(ab.length - 1, i + 1)];
        const len = Math.hypot(qa - pa, qb - pb) || 1;
        return [a - ((qb - pb) / len) * off * side, b + ((qa - pa) / len) * off * side];
      });
      push(line);
    }
  }
  return out;
}

function inRing(ring: Array<[number, number]>, a: number, b: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ai, bi] = ring[i];
    const [aj, bj] = ring[j];
    if (bi > b !== bj > b && a < ((aj - ai) * (b - bi)) / (bj - bi) + ai) inside = !inside;
  }
  return inside;
}

function underWater(w: AgentWorld, t: number, a: number, b: number): boolean {
  for (const f of w.flood) if (f.t <= t && f.rings.some((ring) => inRing(ring, a, b))) return true;
  return false;
}

/** Pick a route with probability ∝ its weight (cumulative table built in setScene). */
function pickRoute(w: AgentWorld, u: number): Stroll {
  const total = w.strollCum[w.strollCum.length - 1];
  let lo = 0;
  let hi = w.strollCum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (w.strollCum[mid] < u * total) lo = mid + 1;
    else hi = mid;
  }
  return w.strolls[lo];
}

export function setScene(w: AgentWorld, data: Diorama, keyframes: ScenarioKeyframe[], venue: [number, number]) {
  w.strolls = strollRoutes(data, w.p, w.insideBuilding);
  // busier near the venue (campus, plazas) and on footpaths; quieter far out
  const [va, vb] = w.p.toAB(venue[0], venue[1]);
  let acc = 0;
  w.strollCum = w.strolls.map((r) => {
    const [ma, mb] = r.pts[Math.floor(r.pts.length / 2)];
    r.w = Math.max(0.12, Math.exp(-Math.hypot(ma - va, mb - vb) / 380)) * Math.min(2, r.len / 60);
    acc += r.w;
    return acc;
  });
  w.strollers = w.strolls.length ? Array.from({ length: MAX_STROLLERS }, (_, i) => {
    const h1 = ((i * 2654435761) >>> 0) / 4294967296;
    const h2 = ((i * 40503 + 977) % 10007) / 10007;
    const h3 = ((i * 69069 + 12345) % 9973) / 9973;
    return { id: i, route: pickRoute(w, h2), speed: 1.05 + h3 * 0.5, pause: 4 + h1 * 10, phase: h3 * 997, priority: h1 };
  }).sort((a, b) => a.priority - b.priority) : [];
  w.flood = keyframes.map((k) => {
    const list = k.geometry.type === "Polygon" ? [k.geometry.coordinates as [number, number][][]] : (k.geometry.coordinates as [number, number][][][]);
    return { t: k.t_s, rings: list.map((poly) => poly[0].map(([lon, lat]) => w.p.toAB(lon, lat))) };
  });
}

export function agentWorld(p: Projector, insideBuilding: (a: number, b: number) => boolean, onRoad: (a: number, b: number) => boolean, pb: Playback | null): AgentWorld {
  const legs = new Map<number, Leg>();
  const tracks = new Map<string, Track>();
  if (pb) {
    for (const track of pb.tracks) tracks.set(track.id, track);
    const arriveBy = new Map<string, { t: number; rid: string }>();
    for (const e of pb.events) if (e.kind === "arrive" && e.assignment_id && e.resource_id) arriveBy.set(e.assignment_id, { t: e.t_s, rid: e.resource_id });
    // events are stamped at the end of their tick; the household's own status timeline says when the
    // van actually left with them (picked_up) and when they were set down (safe)
    const statusAt = new Map<number, Array<[number, string]>>();
    for (const h of pb.households) statusAt.set(h.household_id, h.status as Array<[number, string]>);
    for (const e of pb.events) {
      if (e.household_id == null || !e.assignment_id || e.kind !== "pickup") continue;
      const arrive = arriveBy.get(e.assignment_id);
      if (!arrive) continue;
      const changes = statusAt.get(e.household_id) ?? [];
      const picked = changes.find(([, st]) => st === "picked_up")?.[0] ?? e.t_s;
      const safe = changes.find(([, st]) => st === "safe")?.[0] ?? null;
      legs.set(e.household_id, { rid: arrive.rid, arrive: arrive.t, pickup: picked, dropoff: safe });
    }
  }
  return { p, insideBuilding, onRoad, legs, tracks, spots: new Map(), outside: new Map(), strolls: [], strollCum: [], strollers: [], flood: [] };
}

/** Nearest ground point outside any building: first along `toward`, then in widening rings. */
function outsidePoint(w: AgentWorld, a: number, b: number, toward?: [number, number]): [number, number] {
  if (!w.insideBuilding(a, b)) return [a, b];
  if (toward && !w.insideBuilding(toward[0], toward[1])) {
    // from the street back toward home: stop on the pavement just before the first façade
    // (walking outward from home instead would stop in the first courtyard or light well)
    const d = Math.hypot(toward[0] - a, toward[1] - b);
    for (let s = 0.5; s < d; s += 0.5) {
      const pa = toward[0] + ((a - toward[0]) * s) / d;
      const pb = toward[1] + ((b - toward[1]) * s) / d;
      if (w.insideBuilding(pa, pb)) {
        const s2 = Math.max(0, s - 1.5);
        return [toward[0] + ((a - toward[0]) * s2) / d, toward[1] + ((b - toward[1]) * s2) / d];
      }
    }
  }
  for (let r = 2; r <= 60; r += 2) {
    for (let i = 0; i < 16; i++) {
      const ang = (i / 16) * Math.PI * 2;
      const pa = a + Math.cos(ang) * r;
      const pb = b + Math.sin(ang) * r;
      if (!w.insideBuilding(pa, pb)) return [pa, pb];
    }
  }
  return toward ?? [a, b];
}

/** Where a household's people wait: on the pavement in front of their building, on the side of their street. */
export function waitSpot(w: AgentWorld, h: { household_id: number; lon: number; lat: number; node: number }): [number, number] {
  let spot = w.spots.get(h.household_id);
  if (spot) return spot;
  const [a, b] = w.p.toAB(h.lon, h.lat);
  const c = w.p.toAB(...curb(h.lon, h.lat, h.node));
  const d = Math.hypot(c[0] - a, c[1] - b);
  spot = outsidePoint(w, a, b, c);
  // neighbours from the same building share a doorstep: spread them along the pavement
  const ua = d > 0 ? (c[0] - a) / d : 1;
  const ub = d > 0 ? (c[1] - b) / d : 0;
  const taken = [...w.spots.values()];
  for (let i = 1; i < 12 && taken.some((o) => Math.hypot(o[0] - spot![0], o[1] - spot![1]) < 3.2); i++) {
    const step = Math.ceil(i / 2) * 3.4 * (i % 2 ? 1 : -1);
    const cand = outsidePoint(w, spot[0] - ub * step, spot[1] + ua * step);
    if (!taken.some((o) => Math.hypot(o[0] - cand[0], o[1] - cand[1]) < 3.2)) {
      spot = cand;
      break;
    }
  }
  w.spots.set(h.household_id, spot);
  return spot;
}

/** The same spot as lon/lat (for pins drawn over the stage). */
export function waitLonLat(w: AgentWorld, h: { household_id: number; lon: number; lat: number; node: number }): [number, number] {
  return w.p.fromAB(...waitSpot(w, h));
}

/** Open ground near a facility for people to stand on: off the carriageway, outside buildings, with room around it. */
function facilitySpot(w: AgentWorld, id: string, lon: number, lat: number): [number, number] {
  let spot = w.outside.get(id);
  if (spot) return spot;
  const [a, b] = w.p.toAB(lon, lat);
  const free = (pa: number, pb: number) => !w.insideBuilding(pa, pb) && !w.onRoad(pa, pb);
  const roomy = (pa: number, pb: number) => {
    let n = 0;
    for (let i = 0; i < 12; i++) {
      const ang = (i / 12) * Math.PI * 2;
      if (free(pa + Math.cos(ang) * 7, pb + Math.sin(ang) * 7)) n++;
    }
    return n >= 9;
  };
  spot = free(a, b) && roomy(a, b) ? [a, b] : undefined;
  for (let r = 3; !spot && r <= 90; r += 3) {
    for (let i = 0; i < 24 && !spot; i++) {
      const ang = (i / 24) * Math.PI * 2;
      const pa = a + Math.cos(ang) * r;
      const pb = b + Math.sin(ang) * r;
      if (free(pa, pb) && roomy(pa, pb)) spot = [pa, pb];
    }
  }
  spot = spot ?? outsidePoint(w, a, b);
  w.outside.set(id, spot);
  return spot;
}

const SHAPE: Record<StateHousehold["status"], Shape> = {
  needs: "diamond",
  unknown: "hollow",
  assigned: "ring",
  confirmed: "ring",
  picked_up: "circle",
  safe: "square",
  unreached: "triangle",
};

const toHex = (c: [number, number, number]) => (c[0] << 16) | (c[1] << 8) | c[2];
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const ease = (x: number) => x * x * (3 - 2 * x);

function vanAt(w: AgentWorld, rid: string, t: number): [number, number] | null {
  const track = w.tracks.get(rid);
  if (!track) return null;
  return w.p.toAB(...poseAt(track.path, track.t, t).position);
}

/** Toward `from`, `side` metres off the vehicle's centre (its kerb-side door). */
function doorOf(van: [number, number], from: [number, number], side = 1.6): [number, number] {
  const d = Math.hypot(from[0] - van[0], from[1] - van[1]) || 1;
  return [van[0] + ((from[0] - van[0]) * side) / d, van[1] + ((from[1] - van[1]) * side) / d];
}

const BOARD_S = 70; // sim seconds before pickup when the household starts walking to the van
const WALK_MPS = 1.3;

export function buildAgents(args: {
  w: AgentWorld;
  state: StateSnapshot;
  t: number;
  legend: LegendMode;
  walkers: WalkerPlan | null;
  showWalkers: boolean;
  now: number; // wall seconds (decorative idle motion only)
  /** Stage-wide decorative population budget before flood and viewport filtering. */
  strollCount?: number;
  view?: CrowdView;
  figureHeight?: number;
  figureHalfWidth?: number;
}): Agent[] {
  const { w, state, t, legend, now } = args;
  const { p } = w;
  const out: Agent[] = [];
  let alightingAtShelter = 0;
  const shelter = state.facilities.find((f) => f.type === "shelter");
  const destinations = state.facilities.filter((f) => f.type === "shelter" || f.type === "hospital" || f.type === "clinic");

  for (const h of state.households) {
    if (!p.inside(h.lon, h.lat, 30)) continue;
    const n = Math.max(1, Math.min(6, peopleCount(h)));
    const color = toHex(householdColor(h, legend, t));
    const leg = w.legs.get(h.household_id);
    const spot = waitSpot(w, h);
    const slots = cluster(p.fromAB(...spot), n, h.household_id, 1.3).map(([lon, lat]) => p.toAB(lon, lat));

    // still at home (waiting, or never reached)
    const waiting = h.status !== "picked_up" && h.status !== "safe";
    if (waiting) {
      const boarding = leg && t >= leg.pickup - BOARD_S && t < leg.pickup;
      const van = leg && t >= leg.arrive ? vanAt(w, leg.rid, Math.min(t, leg.pickup)) : null;
      const street = p.toAB(...curb(h.lon, h.lat, h.node));
      const urgent = h.status === "needs" || h.status === "unknown";
      slots.forEach((slot, i) => {
        const id = `h:${h.household_id}:${i}`;
        if (boarding && van) {
          // the van is parked at its pickup spot: walk to the door, one after another, and get in
          const door = doorOf(van, spot);
          const dist = Math.hypot(door[0] - slot[0], door[1] - slot[1]);
          const dur = Math.min(BOARD_S * 0.7, Math.max(8, dist / WALK_MPS));
          const stagger = Math.min(6, (BOARD_S - dur) / Math.max(1, n));
          const start = leg.pickup - BOARD_S + i * stagger;
          const f = clamp01((t - start) / dur);
          if (f >= 1) return; // inside the van
          out.push({
            id, a: slot[0] + (door[0] - slot[0]) * f, b: slot[1] + (door[1] - slot[1]) * f,
            color, shape: "circle", moving: f > 0 && f < 1, faceTo: van, household: h.household_id, xray: true,
          });
          return;
        }
        const wave = urgent && i === 0 && !van && Math.floor(now * 1.4 + h.household_id) % 3 === 0;
        out.push({
          id, a: slot[0], b: slot[1], color, shape: SHAPE[h.status], moving: false,
          pose: wave ? "wave" : "stand", faceTo: van ?? street, household: h.household_id, xray: true,
        });
      });
      continue;
    }

    // dropped off: get out of the van and walk into the facility it stopped at
    if (leg?.dropoff != null && t >= leg.dropoff && t < leg.dropoff + 150) {
      const van = vanAt(w, leg.rid, leg.dropoff);
      if (!van) continue;
      let best: { spot: [number, number]; id: string } | null = null;
      let bestD = 160;
      for (const f of destinations) {
        const at = facilitySpot(w, f.id, f.lon, f.lat);
        const d = Math.hypot(at[0] - van[0], at[1] - van[1]);
        if (d < bestD) {
          bestD = d;
          best = { spot: at, id: f.id };
        }
      }
      const goal = best?.spot ?? [van[0] + 8, van[1] - 4];
      const door = doorOf(van, goal);
      const dur = Math.min(110, Math.max(10, Math.hypot(goal[0] - door[0], goal[1] - door[1]) / WALK_MPS));
      for (let i = 0; i < n; i++) {
        const start = leg.dropoff + i * 4;
        const f = clamp01((t - start) / dur);
        if (t < start || f >= 1) continue;
        if (best && shelter && best.id === shelter.id) alightingAtShelter++;
        const jitter = ((i % 3) - 1) * 0.6;
        out.push({
          id: `h:${h.household_id}:${i}`,
          a: door[0] + (goal[0] - door[0]) * f + jitter, b: door[1] + (goal[1] - door[1]) * f - jitter,
          color: 0x3fbf7f, shape: "circle", moving: true, household: h.household_id,
          alpha: f > 0.85 ? (1 - f) / 0.15 : 1,
        });
      }
    }
  }

  // the shelter crowd, milling (illustrative): each person drifts between nearby spots, pauses, some sit
  if (shelter && p.inside(shelter.lon, shelter.lat)) {
    const walkedIn = args.walkers && args.showWalkers ? arrivedAtShelter(args.walkers, t) : 0;
    const n = Math.max(0, Math.min(140, (shelter.people_on_site ?? 0) + walkedIn - alightingAtShelter));
    const centre = facilitySpot(w, shelter.id, shelter.lon, shelter.lat);
    const slots = crowd(p.fromAB(...centre), n * 2, 1.9)
      .map(([lon, lat]) => p.toAB(lon, lat))
      .filter(([a, b]) => !w.insideBuilding(a, b) && !w.onRoad(a, b))
      .slice(0, n);
    slots.forEach((slot, i) => {
      const period = 9 + (i % 7) * 1.7;
      const clock = now / period + (i * 0.6180339) % 1;
      const k = Math.floor(clock);
      const f = clock - k;
      const spotOf = (j: number): [number, number] => {
        const ang = ((j * 2654435761 + i * 40503) % 6283) / 1000;
        const r = 0.6 + ((j * 7 + i) % 5) * 0.35;
        return [slot[0] + Math.cos(ang) * r, slot[1] + Math.sin(ang) * r];
      };
      const from = spotOf(k);
      const to = spotOf(k + 1);
      const walkF = clamp01(f / 0.3);
      const e = ease(walkF);
      const sits = i % 5 === 0;
      out.push({
        id: `s:${i}`,
        a: sits ? slot[0] : from[0] + (to[0] - from[0]) * e,
        b: sits ? slot[1] : from[1] + (to[1] - from[1]) * e,
        color: 0x3fbf7f, shape: "square", moving: !sits && walkF > 0 && walkF < 1,
        pose: sits ? "sit" : "stand", faceTo: centre,
      });
    });
  }

  // passers-by (illustrative): real walking pace on wall time, fewer as the flood rises, never on water
  if (args.showWalkers && w.strolls.length) {
    const count = Math.min(w.strollers.length, Math.round((args.strollCount ?? 700) * (1 - 0.75 * clamp01((t - 2400) / 7200))));
    for (let i = 0; i < count; i++) {
      const stroller = w.strollers[i];
      const { route, speed, pause } = stroller;
      const cycle = (route.len * 2) / speed + pause * 2;
      const tt = (now + stroller.phase) % cycle;
      // there, pause, back, pause
      let d: number;
      let moving = true;
      const leg = route.len / speed;
      if (tt < leg) d = tt * speed;
      else if (tt < leg + pause) { d = route.len; moving = false; }
      else if (tt < 2 * leg + pause) d = route.len - (tt - leg - pause) * speed;
      else { d = 0; moving = false; }
      let k = 1;
      while (k < route.cum.length - 1 && route.cum[k] < d) k++;
      const s0 = route.cum[k - 1];
      const f = (d - s0) / (route.cum[k] - s0 || 1);
      const a = route.pts[k - 1][0] + (route.pts[k][0] - route.pts[k - 1][0]) * f;
      const b = route.pts[k - 1][1] + (route.pts[k][1] - route.pts[k - 1][1]) * f;
      if (args.view) {
        const [x, y] = p.iso(a, b);
        if (!inCrowdView(x, y, args.view, args.figureHeight ?? 15, args.figureHalfWidth ?? 3)) continue;
      }
      if (!p.inside(...p.fromAB(a, b)) || underWater(w, t, a, b)) continue;
      out.push({ id: `p:${stroller.id}`, a, b, color: CLOTH[stroller.id % CLOTH.length], shape: "circle", moving, alpha: 0.95 });
    }
  }

  // neighbours on foot (illustrative)
  if (args.walkers && args.showWalkers) {
    let count = 0;
    for (const pose of walkersAt(args.walkers, t, null)) {
      if (count > 700) break;
      if (!p.inside(pose.position[0], pose.position[1])) continue;
      const [a, b] = p.toAB(pose.position[0], pose.position[1]);
      out.push({
        id: `w:${pose.walker.id}`, a, b,
        color: pose.walker.turnedBack ? 0xe08a4f : 0xb8c2d0, shape: pose.walker.turnedBack ? "triangle" : "circle",
        moving: pose.frame !== "stand",
      });
      count++;
    }
  }
  return out;
}

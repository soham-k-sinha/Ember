/**
 * PixiJS isometric stage (D52 prototype): the flood district as a clay model, with the resources as
 * the subject. World layers (ground, flood, trails, buildings, vehicles, people) live in a camera
 * container; markers and labels are drawn in screen space so they stay crisp and readable at any zoom.
 */

import { useEffect, useRef } from "react";
import { Application, Container, Graphics, Text, type FederatedPointerEvent } from "pixi.js";
import { loadDiorama, type Diorama } from "../diorama";
import { scenario, town } from "../fixtures";
import { curb, householdColor, peopleCount, type LegendMode } from "../layers";
import { cluster, crowd, walkersAt, type WalkerPlan } from "../people";
import { pathAhead, type Playback } from "../playback";
import type { Closure, FloodGeometry, Selection, StateFacility, StateResource, StateSnapshot } from "../types";
import { edgePoint, projector, type Projector } from "./project";
import { buildStatic, CLAY } from "./scene";

export type IsoProps = {
  state: StateSnapshot;
  t: number;
  closures: Closure[];
  playback: Playback | null;
  walkers: WalkerPlan | null;
  showWalkers: boolean;
  legend: LegendMode;
  selection: Selection | null;
  follow: Selection | null;
  onSelect: (selection: Selection | null) => void;
  onFollow: (selection: Selection | null) => void;
};

const KIND: Record<string, { color: number; label: string }> = {
  van: { color: 0x2f6fe0, label: "Van" },
  accessible_van: { color: 0x8a4fe0, label: "Accessible van" },
  truck: { color: 0xe0782f, label: "Truck" },
  crew: { color: 0x22a06b, label: "Crew" },
  generator: { color: 0xe8b51e, label: "Generator" },
};

const FACILITY: Record<string, { color: number; glyph: string }> = {
  hospital: { color: 0xe5484d, glyph: "H" },
  clinic: { color: 0xe5484d, glyph: "+" },
  shelter: { color: 0x22a06b, glyph: "S" },
  pumping_station: { color: 0x7c5cff, glyph: "P" },
  substation: { color: 0xe8b51e, glyph: "kV" },
  outfall: { color: 0x6b7a8f, glyph: "O" },
  response_base: { color: 0x2f6fe0, glyph: "EMS" },
};

const STATE_RING: Record<string, number> = { ok: 0x22a06b, backup: 0xf5a524, down: 0xe5484d };

const toHex = (c: [number, number, number]) => (c[0] << 16) | (c[1] << 8) | c[2];

type Pill = { root: Container; bg: Graphics; text: Text; key: string; used: boolean };

type Ctx = {
  app: Application;
  data: Diorama;
  p: Projector;
  world: Container;
  dyn: Container;
  flood: Graphics;
  closed: Graphics;
  trails: Graphics;
  actors: Graphics;
  people: Graphics;
  overlay: Graphics;
  hits: Container;
  pills: Map<string, Pill>;
  pillLayer: Container;
  floodKey: unknown;
  closedKey: string;
  cam: { x: number; y: number; s: number };
  drag: { on: boolean; moved: boolean; x: number; y: number } ;
};

export function IsoView(props: IsoProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const ctxRef = useRef<Ctx | null>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let dead = false;
    let ready = false;
    const app = new Application();
    void (async () => {
      await app.init({ resizeTo: el, antialias: true, background: CLAY.bg, resolution: Math.min(2, window.devicePixelRatio || 1), autoDensity: true });
      ready = true;
      if (dead) {
        app.destroy(true, { children: true });
        return;
      }
      el.appendChild(app.canvas);
      const data = await loadDiorama("stage");
      if (dead || !data) return;
      const p = projector(data.bbox);
      const accents = propsRef.current.state.facilities
        .filter((facility) => p.inside(facility.lon, facility.lat))
        .map((facility) => ({ lon: facility.lon, lat: facility.lat, color: FACILITY[facility.type]?.color ?? 0x888888 }));
      const scene = buildStatic(app.renderer, data, p, accents);
      const world = new Container();
      const dyn = new Container();
      const flood = new Graphics();
      const closed = new Graphics();
      const trails = new Graphics();
      dyn.addChild(flood, closed, trails);
      dyn.mask = scene.slabMask;
      const actors = new Graphics();
      const people = new Graphics();
      world.addChild(scene.ground, scene.slabMask, dyn, scene.sorted, people, actors);
      const overlay = new Graphics();
      const hits = new Container();
      const pillLayer = new Container();
      app.stage.addChild(world, overlay, pillLayer, hits);

      // camera: fit the stage
      const b = world.getLocalBounds();
      const s = Math.min(app.screen.width / (b.width * 1.08), app.screen.height / (b.height * 1.12));
      const cam = { s, x: app.screen.width / 2 - (b.x + b.width / 2) * s, y: app.screen.height / 2 - (b.y + b.height / 2) * s };
      const ctx: Ctx = {
        app, data, p, world, dyn, flood, closed, trails, actors, people, overlay, hits, pills: new Map(), pillLayer,
        floodKey: null, closedKey: "", cam, drag: { on: false, moved: false, x: 0, y: 0 },
      };
      ctxRef.current = ctx;

      // pan / zoom
      app.stage.eventMode = "static";
      app.stage.hitArea = app.screen;
      app.stage.on("pointerdown", (e: FederatedPointerEvent) => {
        ctx.drag = { on: true, moved: false, x: e.global.x, y: e.global.y };
      });
      app.stage.on("pointermove", (e: FederatedPointerEvent) => {
        if (!ctx.drag.on) return;
        const dx = e.global.x - ctx.drag.x;
        const dy = e.global.y - ctx.drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) {
          ctx.drag.moved = true;
          if (propsRef.current.follow) propsRef.current.onFollow(null);
        }
        ctx.cam.x += dx;
        ctx.cam.y += dy;
        ctx.drag.x = e.global.x;
        ctx.drag.y = e.global.y;
      });
      const end = () => {
        setTimeout(() => (ctx.drag.moved = false), 0);
        ctx.drag.on = false;
      };
      app.stage.on("pointerup", end);
      app.stage.on("pointerupoutside", end);
      app.stage.on("pointertap", () => {
        if (!ctx.drag.moved) propsRef.current.onSelect(null);
      });
      app.canvas.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          const rect = app.canvas.getBoundingClientRect();
          const mx = event.clientX - rect.left;
          const my = event.clientY - rect.top;
          const k = Math.exp(-event.deltaY * 0.0016);
          const ns = Math.min(9, Math.max(0.35, ctx.cam.s * k));
          const f = ns / ctx.cam.s;
          ctx.cam.x = mx - (mx - ctx.cam.x) * f;
          ctx.cam.y = my - (my - ctx.cam.y) * f;
          ctx.cam.s = ns;
        },
        { passive: false },
      );

      app.ticker.add(() => frame(ctx, propsRef.current));
    })();
    return () => {
      dead = true;
      ctxRef.current = null;
      if (ready) {
        try {
          app.destroy(true, { children: true });
        } catch {
          // already torn down
        }
      }
    };
  }, []);

  return <div className="iso-host" ref={host} />;
}

// ---------------------------------------------------------------------------------------------

function frame(ctx: Ctx, props: IsoProps) {
  const { p, cam } = ctx;
  const t = props.t;
  const now = performance.now() / 1000;
  const pulse = 0.5 + 0.5 * Math.sin(now * 3.2);

  // follow the selected vehicle / household
  const followAt = props.follow ? positionOf(props.state, props.follow) : null;
  if (followAt) {
    const [x, y] = p.lonlat(followAt[0], followAt[1]);
    const tx = ctx.app.screen.width * 0.42 - x * cam.s;
    const ty = ctx.app.screen.height * 0.5 - y * cam.s;
    cam.x += (tx - cam.x) * 0.12;
    cam.y += (ty - cam.y) * 0.12;
  }
  ctx.world.position.set(cam.x, cam.y);
  ctx.world.scale.set(cam.s);

  drawFlood(ctx, props, pulse);
  drawClosures(ctx, props);
  drawTrails(ctx, props, t);
  drawPeople(ctx, props, t, now);
  drawVehicles(ctx, props, now);
  drawOverlay(ctx, props, now, pulse);
}

const toScreen = (ctx: Ctx, x: number, y: number): [number, number] => [ctx.cam.x + x * ctx.cam.s, ctx.cam.y + y * ctx.cam.s];

function positionOf(state: StateSnapshot, selection: Selection): [number, number] | null {
  if (selection.kind === "resource") {
    const r = state.resources.find((item) => item.id === selection.id);
    return r ? [r.lon, r.lat] : null;
  }
  if (selection.kind === "household") {
    const h = state.households.find((item) => item.household_id === selection.id);
    return h ? [h.lon, h.lat] : null;
  }
  if (selection.kind === "facility") {
    const f = state.facilities.find((item) => item.id === selection.id);
    return f ? [f.lon, f.lat] : null;
  }
  return null;
}

function polys(geometry: FloodGeometry | null): [number, number][][][] {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return [geometry.coordinates as [number, number][][]];
  return geometry.coordinates as [number, number][][][];
}

function drawFlood(ctx: Ctx, props: IsoProps, pulse: number) {
  const geometry = props.state.hazard.geometry ?? activeFlood(props.t);
  if (ctx.floodKey !== geometry) {
    ctx.floodKey = geometry;
    const g = ctx.flood;
    g.clear();
    for (const poly of polys(geometry)) {
      const [outer, ...holes] = poly;
      g.poly(outer.flatMap(([lon, lat]) => ctx.p.lonlat(lon, lat))).fill({ color: 0x2f86ff, alpha: 0.5 });
      for (const hole of holes) g.poly(hole.flatMap(([lon, lat]) => ctx.p.lonlat(lon, lat))).cut();
      g.poly(outer.flatMap(([lon, lat]) => ctx.p.lonlat(lon, lat))).stroke({ width: 1.6, color: 0x9fd0ff, alpha: 0.95 });
    }
  }
  ctx.flood.alpha = 0.82 + 0.18 * pulse;
}

// scenario keyframes, for when the snapshot carries no geometry (the replay path)
function activeFlood(t: number): FloodGeometry | null {
  let g: FloodGeometry | null = null;
  for (const frame of scenario.hazard.keyframes) if (frame.t_s <= t) g = frame.geometry;
  return g;
}

const EDGE_BY_ID = new Map(town.edges.map((edge) => [edge.id, edge]));

function drawClosures(ctx: Ctx, props: IsoProps) {
  const key = props.closures.map((c) => c.edge_id).sort((a, b) => a - b).join(",");
  if (key === ctx.closedKey) return;
  ctx.closedKey = key;
  const g = ctx.closed;
  g.clear();
  for (const closure of props.closures) {
    const edge = EDGE_BY_ID.get(closure.edge_id);
    if (!edge) continue;
    const pts = edge.geom.map(([lon, lat]) => ctx.p.lonlat(lon, lat));
    g.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
  }
  g.stroke({ width: 4, color: 0xe5484d, alpha: 0.9, cap: "round", join: "round" });
}

function drawTrails(ctx: Ctx, props: IsoProps, t: number) {
  const g = ctx.trails;
  g.clear();
  const pb = props.playback;
  if (!pb) return;
  for (const track of pb.tracks) {
    const color = KIND[track.kind]?.color ?? 0x888888;
    // trail: the last 2.5 minutes
    const pts: [number, number][] = [];
    for (let i = 0; i < track.t.length; i++) {
      if (track.t[i] < t - 150) continue;
      if (track.t[i] > t) break;
      pts.push(ctx.p.lonlat(track.path[i][0], track.path[i][1]));
    }
    if (pts.length > 1) {
      g.moveTo(pts[0][0], pts[0][1]);
      for (const [x, y] of pts.slice(1)) g.lineTo(x, y);
      g.stroke({ width: 3, color, alpha: 0.55, cap: "round", join: "round" });
    }
    // where it is heading: dashed
    const ahead = pathAhead(track, t).map(([lon, lat]) => ctx.p.lonlat(lon, lat));
    let carry = 0;
    for (let i = 1; i < ahead.length; i++) {
      const [x1, y1] = ahead[i - 1];
      const [x2, y2] = ahead[i];
      const len = Math.hypot(x2 - x1, y2 - y1);
      for (let d = -carry; d < len; d += 9) {
        const s0 = Math.max(0, d);
        const s1 = Math.min(len, d + 5);
        if (s1 <= s0) continue;
        g.moveTo(x1 + ((x2 - x1) * s0) / len, y1 + ((y2 - y1) * s0) / len).lineTo(x1 + ((x2 - x1) * s1) / len, y1 + ((y2 - y1) * s1) / len);
      }
      carry = (carry + len) % 9;
    }
    if (ahead.length > 1) g.stroke({ width: 2.2, color, alpha: 0.9, cap: "round" });
  }
}

/** A tiny standing person: shadow, legs/body, head. Height ~ h px in world units. */
function figure(g: Graphics, x: number, y: number, color: number, h: number, bob = 0) {
  g.ellipse(x, y, h * 0.32, h * 0.13).fill({ color: 0x000000, alpha: 0.18 });
  g.roundRect(x - h * 0.18, y - h * 0.78 - bob, h * 0.36, h * 0.62, h * 0.16).fill(color);
  g.circle(x, y - h * 0.92 - bob, h * 0.17).fill(0xf1d6b8);
}

function drawPeople(ctx: Ctx, props: IsoProps, t: number, now: number) {
  const g = ctx.people;
  g.clear();
  const { p } = ctx;
  const h = 5.2;
  // households waiting for help, at the curb
  for (const household of props.state.households) {
    if (household.status === "picked_up" || household.status === "safe") continue;
    if (!p.inside(household.lon, household.lat)) continue;
    const c = toHex(householdColor(household, props.legend, t));
    const n = Math.min(6, peopleCount(household));
    cluster(curb(household.lon, household.lat, household.node), n, household.household_id, 2.2).forEach(([lon, lat], i) => {
      const [x, y] = p.lonlat(lon, lat);
      const wave = i === 0 && (household.status === "needs" || household.status === "unknown") ? Math.abs(Math.sin(now * 4 + i)) * 0.6 : 0;
      figure(g, x, y, c, h, wave);
    });
  }
  // the shelter crowd
  const shelter = props.state.facilities.find((facility) => facility.type === "shelter");
  if (shelter && p.inside(shelter.lon, shelter.lat)) {
    const n = Math.min(70, shelter.people_on_site ?? 0);
    crowd([shelter.lon, shelter.lat], n, 3.4).forEach(([lon, lat], i) => {
      const [x, y] = p.lonlat(lon, lat);
      figure(g, x, y, 0x22a06b, h * 0.95, Math.abs(Math.sin(now * 2 + i)) * 0.25);
    });
  }
  // neighbours on foot (illustrative), only those on stage
  if (props.walkers && props.showWalkers) {
    let drawn = 0;
    for (const pose of walkersAt(props.walkers, t, null)) {
      if (drawn > 500) break;
      if (!p.inside(pose.position[0], pose.position[1])) continue;
      const [x, y] = p.lonlat(pose.position[0], pose.position[1]);
      figure(g, x, y, pose.walker.turnedBack ? 0xe08a4f : 0x9aa6b8, h * 0.85, pose.frame === "walk1" ? 0.5 : 0);
      drawn++;
    }
  }
}

/** Oriented vehicle box seen in iso: footprint L×W (m), height H, plus a light bar when en route. */
function vehicle(g: Graphics, p: Projector, r: StateResource, now: number, selected: boolean) {
  const [a, b] = p.toAB(r.lon, r.lat);
  const hd = ((r.heading_deg ?? 0) * Math.PI) / 180;
  const fa = Math.sin(hd);
  const fb = -Math.cos(hd); // forward in (a = east, b = south)
  const sa = -fb;
  const sb = fa; // right side
  const big = r.kind === "truck" || r.kind === "generator" ? 1.25 : 1;
  const L = 9 * big;
  const W = 4.4 * big;
  const H = 3.6 * big;
  const corner = (u: number, v: number): [number, number] => [a + fa * u + sa * v, b + fb * u + sb * v];
  const base = [corner(L / 2, -W / 2), corner(L / 2, W / 2), corner(-L / 2, W / 2), corner(-L / 2, -W / 2)];
  const color = KIND[r.kind]?.color ?? 0x888888;
  const dark = shadeHex(color, 0.72);
  const mid = shadeHex(color, 0.86);
  // ground shadow
  g.poly(base.flatMap(([x, y]) => p.iso(x + 1.2, y + 1.2))).fill({ color: 0x000000, alpha: 0.22 });
  // visible sides
  for (let i = 0; i < 4; i++) {
    const [a1, b1] = base[i];
    const [a2, b2] = base[(i + 1) % 4];
    const na = b2 - b1;
    const nb = -(a2 - a1);
    if (na + nb <= 0) continue;
    g.poly([...p.iso(a1, b1), ...p.iso(a2, b2), ...p.iso(a2, b2, H), ...p.iso(a1, b1, H)]).fill(na > nb ? mid : dark).stroke({ width: 0.4, color: 0x1a1a1a, alpha: 0.5 });
  }
  g.poly(base.flatMap(([x, y]) => p.iso(x, y, H))).fill(shadeHex(color, 1.08)).stroke({ width: selected ? 1.4 : 0.4, color: selected ? 0xffffff : 0x1a1a1a, alpha: selected ? 1 : 0.5 });
  // windscreen at the front
  const [wa1, wb1] = corner(L / 2 - 0.4, -W / 2 + 0.6);
  const [wa2, wb2] = corner(L / 2 - 0.4, W / 2 - 0.6);
  const [wa3, wb3] = corner(L / 2 - 2.2, W / 2 - 0.6);
  const [wa4, wb4] = corner(L / 2 - 2.2, -W / 2 + 0.6);
  g.poly([...p.iso(wa1, wb1, H + 0.02), ...p.iso(wa2, wb2, H + 0.02), ...p.iso(wa3, wb3, H + 0.02), ...p.iso(wa4, wb4, H + 0.02)]).fill(0x1d2a36);
  if (r.status === "en_route" || r.status === "returning") {
    const on = Math.floor(now * 5) % 2 === 0;
    const [la, lb] = corner(0.3, -W / 4);
    const [ra, rb] = corner(0.3, W / 4);
    g.circle(...p.iso(la, lb, H + 0.6), 1.1).fill(on ? 0xff3b3b : 0x5a1010);
    g.circle(...p.iso(ra, rb, H + 0.6), 1.1).fill(on ? 0x2a1a60 : 0x4d8dff);
  }
  if (r.status === "working") {
    const [x, y] = p.iso(a, b, H + 2.2);
    g.circle(x, y, 1.6 + 0.6 * Math.sin(now * 6)).fill({ color: 0xffb020, alpha: 0.9 });
  }
}

function shadeHex(c: number, k: number): number {
  const r = Math.min(255, Math.round(((c >> 16) & 255) * k));
  const g = Math.min(255, Math.round(((c >> 8) & 255) * k));
  const b = Math.min(255, Math.round((c & 255) * k));
  return (r << 16) | (g << 8) | b;
}

function drawVehicles(ctx: Ctx, props: IsoProps, now: number) {
  const g = ctx.actors;
  g.clear();
  const sel = props.selection?.kind === "resource" ? props.selection.id : props.follow?.kind === "resource" ? props.follow.id : null;
  const list = props.state.resources
    .filter((r) => ctx.p.inside(r.lon, r.lat))
    .sort((x, y) => ctx.p.depth(x.lon, x.lat) - ctx.p.depth(y.lon, y.lat));
  for (const r of list) vehicle(g, ctx.p, r, now, r.id === sel);
}

// ---------- screen-space markers, labels, hit targets ----------

function pill(ctx: Ctx, key: string, text: string, x: number, y: number, style: { bg: number; fg?: number; size?: number; border?: number }) {
  let item = ctx.pills.get(key);
  if (!item) {
    const root = new Container();
    const bg = new Graphics();
    const label = new Text({ text, style: { fontFamily: "Inter, system-ui, sans-serif", fontSize: style.size ?? 11, fontWeight: "700", fill: style.fg ?? 0xffffff, letterSpacing: 0.4 }, resolution: 2 });
    root.addChild(bg, label);
    ctx.pillLayer.addChild(root);
    item = { root, bg, text: label, key: "", used: true };
    ctx.pills.set(key, item);
  }
  const sig = `${text}|${style.bg}|${style.border ?? 0}`;
  if (item.key !== sig) {
    item.key = sig;
    item.text.text = text;
    const w = item.text.width + 12;
    const h = item.text.height + 5;
    item.bg.clear().roundRect(-w / 2, -h, w, h, 5).fill({ color: style.bg, alpha: 0.94 });
    if (style.border) item.bg.roundRect(-w / 2, -h, w, h, 5).stroke({ width: 1.2, color: style.border });
    item.text.position.set(-item.text.width / 2, -h + 2.5);
  }
  item.root.position.set(Math.round(x), Math.round(y));
  item.root.visible = true;
  item.used = true;
}

function hit(ctx: Ctx, key: string, x: number, y: number, r: number, select: Selection) {
  const props = { ...select };
  let target = ctx.hits.getChildByLabel(key) as Graphics | null;
  if (!target) {
    target = new Graphics().circle(0, 0, 1).fill({ color: 0xffffff, alpha: 0.001 });
    target.label = key;
    target.eventMode = "static";
    target.cursor = "pointer";
    ctx.hits.addChild(target);
  }
  target.removeAllListeners("pointertap");
  target.on("pointertap", (e: FederatedPointerEvent) => {
    e.stopPropagation();
    if (!ctx.drag.moved) currentSelect?.(props);
  });
  target.position.set(x, y);
  target.scale.set(r);
  target.visible = true;
}

let currentSelect: ((selection: Selection | null) => void) | null = null;

function drawOverlay(ctx: Ctx, props: IsoProps, _now: number, pulse: number) {
  currentSelect = props.onSelect;
  const g = ctx.overlay;
  g.clear();
  for (const item of ctx.pills.values()) item.used = false;
  for (const child of ctx.hits.children) child.visible = false;
  const { p } = ctx;
  const zoomed = ctx.cam.s > 1.6;

  // facilities: on stage → a base marker; off stage → an edge tile pointing to where it is
  const offStageCount = new Map<string, number>();
  const offStage: Array<{ facility: StateFacility; at: [number, number] }> = [];
  for (const facility of props.state.facilities) {
    if (p.inside(facility.lon, facility.lat)) continue;
    const [a, b] = p.toAB(facility.lon, facility.lat);
    offStage.push({ facility, at: edgePoint(p, a, b, 14) });
  }
  for (const r of props.state.resources) {
    if (p.inside(r.lon, r.lat) || offStage.length === 0) continue;
    const [a, b] = p.toAB(r.lon, r.lat);
    let best = offStage[0];
    let d = Infinity;
    for (const item of offStage) {
      const [fa, fb] = p.toAB(item.facility.lon, item.facility.lat);
      const dd = Math.hypot(a - fa, b - fb);
      if (dd < d) {
        d = dd;
        best = item;
      }
    }
    offStageCount.set(best.facility.id, (offStageCount.get(best.facility.id) ?? 0) + 1);
  }

  for (const facility of props.state.facilities) {
    const meta = FACILITY[facility.type] ?? { color: 0x888888, glyph: "?" };
    const ring = STATE_RING[facility.state] ?? 0x888888;
    const onStage = p.inside(facility.lon, facility.lat);
    let x: number;
    let y: number;
    let sub = "";
    if (onStage) {
      [x, y] = toScreen(ctx, ...p.lonlat(facility.lon, facility.lat, 22));
    } else {
      const item = offStage.find((o) => o.facility.id === facility.id)!;
      [x, y] = toScreen(ctx, ...p.iso(item.at[0], item.at[1], 0));
      const [ca, cb] = [(p.bounds.a0 + p.bounds.a1) / 2, (p.bounds.b0 + p.bounds.b1) / 2];
      const [fa, fb] = p.toAB(facility.lon, facility.lat);
      sub = ` · ${(Math.hypot(fa - ca, fb - cb) / 1000).toFixed(1)} km`;
      // arrow from the tile toward the facility
      const [dx, dy] = p.iso(fa - item.at[0], fb - item.at[1]);
      const len = Math.hypot(dx, dy) || 1;
      g.moveTo(x, y).lineTo(x + (dx / len) * 26, y + (dy / len) * 26).stroke({ width: 2, color: meta.color, alpha: 0.9 });
    }
    const alarm = facility.state !== "ok";
    if (alarm) g.circle(x, y, 17 + 6 * pulse).fill({ color: ring, alpha: 0.18 + 0.18 * pulse });
    g.roundRect(x - 13, y - 13, 26, 26, 7).fill(meta.color).stroke({ width: 2.4, color: ring });
    pill(ctx, `glyph:${facility.id}`, meta.glyph, x, y + 7, { bg: meta.color, size: meta.glyph.length > 1 ? 9 : 12 });
    if (onStage) g.moveTo(x, y + 13).lineTo(x, y + 13 + 22 * ctx.cam.s * 0.5).stroke({ width: 1.5, color: meta.color, alpha: 0.8 });
    const waiting = offStageCount.get(facility.id);
    const state = facility.state === "ok" ? "" : facility.state === "backup" ? ` · on backup${facility.endurance_left_s != null ? ` ${Math.round(facility.endurance_left_s / 60)} min` : ""}` : " · DOWN";
    pill(ctx, `fac:${facility.id}`, `${facility.name.toUpperCase()}${sub}${state}${waiting ? ` · ${waiting} vehicle${waiting > 1 ? "s" : ""}` : ""}`, x, y - 17, {
      bg: 0x161a22,
      border: alarm ? ring : undefined,
    });
    hit(ctx, `hit:fac:${facility.id}`, x, y, 16, { kind: "facility", id: facility.id });
  }

  // incidents: households still waiting
  for (const household of props.state.households) {
    if (!p.inside(household.lon, household.lat)) continue;
    const waiting = household.status === "needs" || household.status === "unknown" || household.status === "assigned" || household.status === "confirmed";
    const lost = household.status === "unreached";
    if (!waiting && !lost && !(props.selection?.kind === "household" && props.selection.id === household.household_id)) continue;
    const color = toHex(householdColor(household, props.legend, props.t));
    const [gx, gy] = toScreen(ctx, ...p.lonlat(household.lon, household.lat));
    const urgent = household.status === "needs" || household.status === "unknown";
    if (urgent) g.ellipse(gx, gy, (14 + 10 * pulse) * Math.max(0.6, ctx.cam.s * 0.5), (7 + 5 * pulse) * Math.max(0.6, ctx.cam.s * 0.5)).stroke({ width: 2, color, alpha: 0.85 - 0.5 * pulse });
    const py = gy - 30;
    g.moveTo(gx, gy - 4).lineTo(gx, py + 9).stroke({ width: 1.5, color, alpha: 0.9 });
    g.circle(gx, py, 10).fill(household.judge ? 0xffc542 : color).stroke({ width: 2, color: 0xffffff });
    // deadline ring: the share of the time left before the water reaches them
    if (household.deadline_s && waiting) {
      const left = Math.max(0, Math.min(1, (household.deadline_s - props.t) / household.deadline_s));
      g.moveTo(gx, py - 13).arc(gx, py, 13, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * left).stroke({ width: 2.5, color: left < 0.25 ? 0xe5484d : 0xffffff, alpha: 0.95 });
    }
    pill(ctx, `n:${household.household_id}`, String(peopleCount(household, 1)), gx, py + 7, { bg: household.judge ? 0xffc542 : color, fg: household.judge ? 0x1a1406 : 0xffffff, size: 11 });
    if (household.judge || zoomed || (props.selection?.kind === "household" && props.selection.id === household.household_id)) {
      const needs = household.needs;
      const extra = needs !== "unknown" && (needs.mobility || needs.accessible_vehicle) ? " · wheelchair" : needs !== "unknown" && needs.medical ? " · medical" : needs === "unknown" ? " · needs unknown" : "";
      pill(ctx, `hh:${household.household_id}`, `${household.judge ? "JUDGE · " : ""}${household.label ?? `#${household.household_id}`}${extra}`, gx, py - 13, { bg: 0x161a22, border: household.judge ? 0xffc542 : undefined, size: 10 });
    }
    hit(ctx, `hit:hh:${household.household_id}`, gx, py, 14, { kind: "household", id: household.household_id });
  }

  // vehicles: labels + hit targets
  for (const r of props.state.resources) {
    if (!p.inside(r.lon, r.lat)) continue;
    const [x, y] = toScreen(ctx, ...p.lonlat(r.lon, r.lat, 8));
    const picked = (props.selection?.kind === "resource" && props.selection.id === r.id) || (props.follow?.kind === "resource" && props.follow.id === r.id);
    if (zoomed || picked || r.status !== "available") {
      const color = KIND[r.kind]?.color ?? 0x888888;
      const aboard = r.people_on_board ? ` · ${r.people_on_board} aboard` : "";
      const eta = r.eta_s != null && r.eta_s > props.t ? ` · ${Math.round((r.eta_s - props.t) / 60)} min` : "";
      pill(ctx, `veh:${r.id}`, `${r.name}${aboard}${eta}`, x, y - 4, { bg: picked ? 0xffffff : color, fg: picked ? 0x111111 : 0xffffff, size: 10 });
    }
    hit(ctx, `hit:veh:${r.id}`, x, y + 8, 14, { kind: "resource", id: r.id });
  }

  for (const item of ctx.pills.values()) if (!item.used) item.root.visible = false;
}


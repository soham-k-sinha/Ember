/**
 * PixiJS isometric stage (D71 prototype): the flood district as a clay model, with the resources as
 * the subject. World layers (ground, flood, trails, buildings, vehicles, people) live in a camera
 * container; markers and labels are drawn in screen space so they stay crisp and readable at any zoom.
 */

import { useEffect, useRef, useState } from "react";
import { Application, Container, Graphics, Sprite, Text, type FederatedPointerEvent } from "pixi.js";
import { loadDiorama, type Diorama } from "./data";
import { agentWorld, buildAgents, setScene, waitLonLat, type AgentWorld } from "./agents";
import { Crowd } from "./crowd";
import { FloodWater } from "./water";
import { TrafficCars } from "./traffic";
import { AmbientTraffic } from "./ambient";
import { Fleet } from "./fleet";
import { TrafficSignals } from "./signals";
import { StaticSnapshot } from "./snapshot";
import { lightAt, tint } from "./lighting";
import { SKY_BG } from "./palette";
import { fixturePlaybacks, scenario, town } from "../fixtures";
import { householdColor, peopleCount } from "../model";
import type { WalkerPlan } from "../people";
import { pathAhead, type Playback } from "../playback";
import type { Closure, Selection, StateFacility, StateSnapshot } from "../types";
import { edgePoint, KZ, projector, type Projector } from "./project";
import { buildStatic, type StaticScene } from "./scene";
import { CrowdBudget, figureScale, populationAtZoom } from "./density";

/** A drill player's household: always pinned, ringing while EMBER has them on a call. */
export type PlayerPin = { label: string; onCall: boolean };

export type IsoProps = {
  state: StateSnapshot;
  t: number;
  closures: Closure[];
  playback: Playback | null;
  walkers: WalkerPlan | null;
  players: Map<number, PlayerPin>;
  selection: Selection | null;
  follow: Selection | null;
  onSelect: (selection: Selection | null) => void;
  onFollow: (selection: Selection | null) => void;
  /** camera presets (Treehouse, Judge's corner…): ease the stage camera to a place */
  focus?: { lon: number; lat: number; zoom: number; key: number } | null;
  onFallback: () => void;
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

type Pill = { root: Container; bg: Graphics; text: Text; key: string; used: boolean; w: number; h: number };

/** Label priorities: higher wins a collision; ALWAYS never yields (markers' own glyphs, the selection). */
const PRIO = { ALWAYS: 1000, SELECTED: 900, VENUE: 850, JUDGE: 800, COUNT: 700, ALARM: 600, VEHICLE: 400, FACILITY: 300, LANDMARK: 100 } as const;
const queued: Array<{ item: Pill; x: number; y: number; prio: number }> = [];

type Ctx = {
  app: Application;
  data: Diorama;
  p: Projector;
  scene: StaticScene;
  world: Container;
  dyn: Container;
  flood: FloodWater;
  floodTint: number;
  closed: Graphics;
  trails: Graphics;
  decals: Graphics; // selection rings on the ground
  marks: Container; // per-person ground marks (atlas sprites)
  top: Graphics; // markers over heads
  crowd: Crowd;
  crowdBudget: CrowdBudget;
  traffic: TrafficCars;
  ambient: AmbientTraffic;
  fleet: Fleet;
  signals: TrafficSignals;
  camWas: { x: number; y: number; s: number };
  userMoved: boolean;
  snapshot: StaticSnapshot;
  statics: Container[];
  staticSet: Set<Container>;
  camStill: number;
  aw: AgentWorld;
  awFor: Playback | null;
  lastT: number;
  lastNow: number;
  vehicles: Map<string, Graphics>;
  lightKey: string;
  fitS: number;
  focusKey: number;
  target: { x: number; y: number; s: number } | null;
  overlay: Graphics;
  haze: Sprite;
  hits: Container;
  pills: Map<string, Pill>;
  pillLayer: Container;
  closedKey: string;
  cam: { x: number; y: number; s: number };
  drag: { on: boolean; moved: boolean; x: number; y: number } ;
};

export function IsoView(props: IsoProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const ctxRef = useRef<Ctx | null>(null);
  const propsRef = useRef(props);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  propsRef.current = props;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    setStatus("loading");
    let dead = false;
    let ready = false;
    const cleanups: Array<() => void> = [];
    const app = new Application();
    void (async () => {
      await app.init({ resizeTo: el, antialias: true, background: SKY_BG, resolution: Math.min(2, window.devicePixelRatio || 1), autoDensity: true });
      ready = true;
      if (dead) {
        app.destroy(true, { children: true });
        return;
      }
      el.appendChild(app.canvas);
      const data = await loadDiorama("stage");
      if (dead) return;
      if (!data) throw new Error("The district data could not be loaded.");
      const p = projector(data.bbox);
      const scene = buildStatic(data, p);
      const world = new Container();
      const dyn = new Container();
      const flood = new FloodWater(p, scenario.hazard.keyframes, data);
      const closed = new Graphics();
      const trails = new Graphics();
      const decals = new Graphics();
      const marks = new Container();
      dyn.addChild(flood.root, closed, trails, marks, decals);
      dyn.mask = scene.slabMask;
      const top = new Graphics();
      world.addChild(scene.slab, scene.ground, scene.tiles.ground, scene.shadow, scene.tiles.shadow, scene.pools, scene.slabMask, dyn, scene.objects, top);
      const crowd = new Crowd(scene.objects, marks, scene.atlas, p, scene.depthFor);
      const traffic = new TrafficCars(app.renderer, scene.objects, p, scene.depthFor);
      const fleet = new Fleet(app.renderer, scene.objects, p);
      const signals = new TrafficSignals(data, p, scene.objects, scene.depthFor, scene.lit);
      const ambient = new AmbientTraffic(data, p, signals, (a, b) => flood.wetAt(a, b));
      const snapshot = new StaticSnapshot(app.renderer);
      const statics = [...scene.buildings.map((r) => r.holder), ...scene.cullables.map((c) => c.node)];
      world.addChildAt(snapshot.sprite, world.getChildIndex(scene.objects));
      const aw = agentWorld(p, scene.insideBuilding, scene.onRoad, propsRef.current.playback);
      setScene(aw, data, scenario.hazard.keyframes, [town.venue.lon, town.venue.lat]);
      const overlay = new Graphics();
      const hits = new Container();
      const pillLayer = new Container();
      const haze = hazeSprite();
      app.stage.addChild(world, haze, overlay, pillLayer, hits);

      // camera: fit the stage
      const cam = fitStage(app, scene.slab, el);
      const s = cam.s;
      const ctx: Ctx = {
        app, data, p, scene, world, dyn, flood, floodTint: 0xffffff, closed, trails, decals, marks, top, crowd, crowdBudget: new CrowdBudget(), traffic, ambient, fleet, signals, camWas: { ...cam }, camStill: 0, userMoved: false, snapshot, statics, staticSet: new Set(statics), aw, awFor: propsRef.current.playback, lastT: propsRef.current.t, lastNow: performance.now() / 1000, vehicles: new Map(), lightKey: "", fitS: s, focusKey: 0, target: null, overlay, haze, hits, pills: new Map(), pillLayer,
        closedKey: "", cam, drag: { on: false, moved: false, x: 0, y: 0 },
      };
      ctxRef.current = ctx;
      if (import.meta.env.DEV) (window as unknown as { __iso?: { app: Application; ctx: Ctx; frame: () => void; props: () => IsoProps; prof: () => Record<string, number> } }).__iso = { app, ctx, frame: () => frame(ctx, propsRef.current), props: () => propsRef.current, prof: readProfile };

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
          ctx.target = null;
          ctx.userMoved = true;
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
      app.stage.on("pointertap", (e: FederatedPointerEvent) => {
        if (ctx.drag.moved) return;
        const household = ctx.crowd.pick(e.global.x, e.global.y, ctx.cam);
        propsRef.current.onSelect(household != null ? { kind: "household", id: household } : null);
      });
      app.canvas.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          ctx.target = null;
          ctx.userMoved = true;
          const rect = app.canvas.getBoundingClientRect();
          const mx = event.clientX - rect.left;
          const my = event.clientY - rect.top;
          const k = Math.exp(-event.deltaY * 0.0016);
          const ns = Math.min(9, Math.max(Math.min(0.35, ctx.fitS * 0.8), ctx.cam.s * k));
          const f = ns / ctx.cam.s;
          ctx.cam.x = mx - (mx - ctx.cam.x) * f;
          ctx.cam.y = my - (my - ctx.cam.y) * f;
          ctx.cam.s = ns;
        },
        { passive: false },
      );

      app.ticker.add(() => frame(ctx, propsRef.current));
      // refit when the map area changes size (window, panels), unless the user has taken the camera
      const refit = new ResizeObserver(() => {
        if (ctx.userMoved) return;
        requestAnimationFrame(() => {
          const fit = fitStage(app, scene.slab, el);
          Object.assign(ctx.cam, fit);
          ctx.fitS = fit.s;
        });
      });
      refit.observe(el);
      cleanups.push(() => refit.disconnect());
      if (new URLSearchParams(location.search).has("perf")) cleanups.push(perfHud(app, ctx, el));
      setStatus("ready");
    })().catch((error: unknown) => {
      if (dead) return;
      console.error("EMBER stage failed to load", error);
      setStatus("error");
    });
    return () => {
      dead = true;
      ctxRef.current = null;
      for (const c of cleanups) c();
      if (ready) {
        try {
          app.destroy(true, { children: true });
        } catch {
          // already torn down
        }
      }
    };
  }, [attempt]);

  return <div className="iso-host" ref={host}>
    {status !== "ready" && <div className="stage-status" role={status === "error" ? "alert" : "status"}>
      <strong>{status === "error" ? "The district view couldn't load" : "Building the district…"}</strong>
      <p>{status === "error" ? "Try again, or continue on the flat map." : "Loading real streets, buildings and trees."}</p>
      {status === "error" && <div>
        <button className="chip" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
        <button className="chip" onClick={props.onFallback}>Use flat map</button>
      </div>}
    </div>}
  </div>;
}

/** Screen-space atmospheric haze falling in from the upper left (additive; tinted and faded by the light). */
function hazeSprite(): Sprite {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g2 = c.getContext("2d")!;
  const grad = g2.createRadialGradient(0, 0, 0, 0, 0, 128);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.55, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g2.fillStyle = grad;
  g2.fillRect(0, 0, 128, 128);
  const sprite = Sprite.from(c);
  sprite.blendMode = "add";
  sprite.eventMode = "none";
  return sprite;
}

/** `?perf` in the URL: a small readout of real frame rate and frame times on this display (for checking 60 fps). */
function perfHud(app: Application, ctx: Ctx, host: HTMLElement) {
  const box = document.createElement("div");
  box.style.cssText = "position:absolute;right:10px;top:54px;z-index:9;font:600 11px/1.4 ui-monospace,monospace;color:#e9f3ff;background:rgba(10,14,20,.78);padding:6px 9px;border-radius:8px;pointer-events:none;white-space:pre";
  host.appendChild(box);
  const dts: number[] = [];
  let last = performance.now();
  app.ticker.add(() => {
    dts.push(app.ticker.deltaMS);
    const now = performance.now();
    if (now - last < 500) return;
    last = now;
    const sorted = [...dts].sort((a, b) => a - b);
    const fps = (1000 * dts.length) / dts.reduce((a, b) => a + b, 0);
    const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? 0;
    const people = ctx.crowd.visibleCount();
    box.textContent = `${fps.toFixed(0)} fps  p95 ${p95.toFixed(1)} ms\n${app.screen.width}×${app.screen.height} @${app.renderer.resolution}x  zoom ${ctx.cam.s.toFixed(2)}\npeople ${people}  budget ${ctx.crowdBudget.limit}  snapshot ${ctx.snapshot.active ? "on" : "off"}`;
    dts.length = 0;
  });
  return () => box.remove();
}

/** Bake the snapshot in neutral light without the night glows; the live tint is applied to the image instead. */
function snapshotBake(ctx: Ctx) {
  const lit = ctx.scene.lit;
  const glows = [...ctx.scene.glows, ...ctx.scene.lampGlows];
  let tints: number[] = [];
  let shown: boolean[] = [];
  return {
    tint: ctx.scene.light.tint,
    before: () => {
      tints = lit.map((n) => n.tint as number);
      for (const n of lit) n.tint = 0xffffff;
      shown = glows.map((g) => g.visible);
      for (const g of glows) g.visible = false;
    },
    after: () => {
      lit.forEach((n, i) => (n.tint = tints[i]));
      glows.forEach((g, i) => (g.visible = shown[i]));
    },
  };
}

/** Camera that fits the whole stage into the part of the canvas the score card does not cover. */
function fitStage(app: Application, slab: Graphics, host: HTMLElement | null): { s: number; x: number; y: number } {
  // fit the whole stage inside the part of the map the overlays leave free: right of the score card, below the
  // latest-change strip, left of the join card where it overlaps
  const b = slab.getLocalBounds();
  const W = app.screen.width;
  const H = app.screen.height;
  let left = 0;
  let right = 0;
  let top = 0;
  let bottom = 0;
  if (host) {
    const h = host.getBoundingClientRect();
    const rect = (sel: string) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const overlaps = r.width > 0 && r.right > h.left && r.left < h.right && r.bottom > h.top && r.top < h.bottom;
      return overlaps ? r : null;
    };
    const card = rect(".scorecard");
    if (card) left = Math.max(0, card.right - h.left + 16);
    const join = rect(".join");
    if (join) {
      right = Math.max(0, h.right - join.left + 12);
      bottom = Math.max(0, h.bottom - join.top + 12);
    }
    const strip = rect(".latest");
    if (strip) top = Math.max(0, strip.bottom - h.top + 8);
  }
  // the join card sits in a corner: lose either a column to its left or a band above it, whichever costs less
  const fit = (x0: number, y0: number, x1: number, y1: number) => {
    const fw = Math.max(200, x1 - x0);
    const fh = Math.max(200, y1 - y0);
    const sc = Math.min(fw / (b.width * 1.03), fh / (b.height * 1.06));
    return { s: sc, x: x0 + fw / 2 - (b.x + b.width / 2) * sc, y: y0 + fh / 2 - (b.y + b.height / 2) * sc };
  };
  const beside = fit(left, top, W - right, H);
  const above = fit(left, top, W, H - bottom);
  return beside.s >= above.s ? beside : above;
}

/** Dev profiling: per-section frame cost, read with window.__iso.prof() (averages since the last read). */
const PROF: Record<string, number> = {};
let PROF_N = 0;
let PROF_T = 0;
function mark(name: string) {
  if (!import.meta.env.DEV) return;
  const now = performance.now();
  PROF[name] = (PROF[name] ?? 0) + (now - PROF_T);
  PROF_T = now;
}
export function readProfile(): Record<string, number> {
  const out: Record<string, number> = { frames: PROF_N };
  for (const [k, v] of Object.entries(PROF)) out[k] = +(v / Math.max(1, PROF_N)).toFixed(2);
  for (const k of Object.keys(PROF)) delete PROF[k];
  PROF_N = 0;
  return out;
}

// ---------------------------------------------------------------------------------------------

function frame(ctx: Ctx, props: IsoProps) {
  if (import.meta.env.DEV) {
    PROF_N++;
    PROF_T = performance.now();
  }
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
  // presets: ease to the requested place (zoom 14.3 ≈ the whole stage, each level doubles)
  if (props.focus && props.focus.key !== ctx.focusKey) {
    ctx.focusKey = props.focus.key;
    if (props.focus.zoom <= 14.4) {
      // the district preset: the whole stage, fitted beside the overlays; the camera is the app's again
      ctx.target = fitStage(ctx.app, ctx.scene.slab, ctx.app.canvas.parentElement);
      ctx.userMoved = false;
    } else {
      ctx.userMoved = true;
      const s = Math.min(9, ctx.fitS * 2 ** (props.focus.zoom - 14.3));
      const [x, y] = p.lonlat(props.focus.lon, props.focus.lat);
      ctx.target = { s, x: ctx.app.screen.width * 0.5 - x * s, y: ctx.app.screen.height * 0.5 - y * s };
    }
  }
  if (ctx.target && !followAt) {
    const k = 0.1;
    cam.s += (ctx.target.s - cam.s) * k;
    cam.x += (ctx.target.x - cam.x) * k;
    cam.y += (ctx.target.y - cam.y) * k;
    if (Math.abs(ctx.target.s - cam.s) < 0.002 && Math.abs(ctx.target.x - cam.x) < 0.5) ctx.target = null;
  }
  ctx.world.position.set(cam.x, cam.y);
  ctx.world.scale.set(cam.s);
  ctx.haze.width = ctx.app.screen.width * 1.25;
  ctx.haze.height = ctx.app.screen.height * 1.1;
  cull(ctx);
  mark("cull");
  applyLight(ctx, t);
  mark("applyLight");
  {
    // district zoom: the static city as one baked image, moving things live on top (D96)
    const dynamics = ctx.scene.objects.children.filter((c) => !ctx.staticSet.has(c as Container)) as Container[];
    ctx.snapshot.update(cam.s, performance.now() - ctx.camStill > 220, ctx.scene.objects, ctx.statics, dynamics, ctx.app.renderer.resolution, snapshotBake(ctx));
  }
  mark("snapshot");
  {
    const view = { x0: -cam.x / cam.s, y0: -cam.y / cam.s, x1: (ctx.app.screen.width - cam.x) / cam.s, y1: (ctx.app.screen.height - cam.y) / cam.s };
    // sharp ground tiles bake only once the camera has settled, so panning and zooming never stall on a bake
    const moved = Math.abs(cam.s - ctx.camWas.s) > 1e-4 || Math.abs(cam.x - ctx.camWas.x) > 0.5 || Math.abs(cam.y - ctx.camWas.y) > 0.5;
    if (moved) ctx.camStill = performance.now();
    ctx.camWas = { ...cam };
    const sharp = ctx.scene.tiles.update(view, cam.s, ctx.scene.light.tint, performance.now() - ctx.camStill > 180);
    mark("tiles");
    ctx.scene.shadow.visible = !sharp;
    ctx.scene.tiles.shadow.alpha = ctx.scene.shadow.alpha;
  }

  drawFlood(ctx, props, now);
  mark("drawFlood");
  drawClosures(ctx, props);
  mark("drawClosures");
  drawTrails(ctx, props, t);
  mark("drawTrails");
  drawPeople(ctx, props, t, now);
  mark("drawPeople");
  {
    const view = { x0: -cam.x / cam.s, y0: -cam.y / cam.s, x1: (ctx.app.screen.width - cam.x) / cam.s, y1: (ctx.app.screen.height - cam.y) / cam.s };
    // everyday cars (illustrative, wall clock) and the evacuation traffic: the same for every plan, so the
    // fixture ships it once, with EMBER's replay
    ctx.ambient.step(now - ctx.lastNow, now, t, view, ctx.traffic.shown);
    mark("ambient");
    ctx.traffic.update(props.playback?.traffic ?? fixturePlaybacks.ember.traffic, t, view, ctx.scene.light.tint, ctx.ambient.cars, { now, camS: cam.s, lights: ctx.scene.light.lights });
    mark("traffic");
    ctx.signals.update(now, ctx.scene.light.lights, view, cam.s);
    mark("signals");
  }
  ctx.lastT = t;
  ctx.lastNow = now;
  drawVehicles(ctx, props, now);
  mark("vehicles");
  drawOverlay(ctx, props, now, pulse);
  mark("overlay");
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

function drawFlood(ctx: Ctx, props: IsoProps, now: number) {
  ctx.flood.update(props.t, now, props.state.hazard.geometry ?? null, ctx.floodTint);
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

const DETAIL_S = 2.1; // zoom at which buildings switch to full detail (windows, doors, rooftop units)

/** Draw only what is on screen; zoomed in, swap visible buildings to their detailed version. */
function cull(ctx: Ctx) {
  const { cam, app } = ctx;
  const m = 40 / cam.s;
  const x0 = -cam.x / cam.s - m;
  const y0 = -cam.y / cam.s - m;
  const x1 = (app.screen.width - cam.x) / cam.s + m;
  const y1 = (app.screen.height - cam.y) / cam.s + m;
  const hit = (b: { x0: number; y0: number; x1: number; y1: number }) => b.x1 >= x0 && b.x0 <= x1 && b.y1 >= y0 && b.y0 <= y1;
  const detail = cam.s >= DETAIL_S;
  for (const rec of ctx.scene.buildings) {
    const on = hit(rec.bounds);
    rec.holder.visible = on;
    if (!on) continue;
    if (detail) {
      const full = ctx.scene.ensureFull(rec);
      full.visible = true;
      rec.lite.visible = false;
    } else {
      rec.lite.visible = true;
      if (rec.full) rec.full.visible = false;
    }
  }
  for (const item of ctx.scene.cullables) item.node.visible = cam.s >= (item.minScale ?? 0) && hit(item.bounds);
}

/** Evening light: tint the city, fade shadows, bring up windows, lamps and pools, in 48 steps over the run. */
function applyLight(ctx: Ctx, t: number) {
  const step = Math.round(t / (scenario.t_end_s / 48));
  const key = String(step);
  if (key === ctx.lightKey) return;
  ctx.lightKey = key;
  const L = lightAt(step * (scenario.t_end_s / 48));
  const world = tint(L.world);
  ctx.scene.light.tint = world;
  ctx.scene.light.lights = L.lights;
  for (const node of ctx.scene.lit) node.tint = world;
  ctx.scene.shadow.alpha = L.shadow;
  ctx.scene.pools.alpha = L.lights * 0.95;
  ctx.scene.pools.visible = L.lights > 0.01;
  for (const g of ctx.scene.glows) {
    g.alpha = L.lights;
    g.visible = L.lights > 0.01;
  }
  for (const g of ctx.scene.lampGlows) g.alpha = ((g as Sprite & { base?: number }).base ?? 1) * L.lights;
  ctx.app.renderer.background.color = L.sky;
  ctx.haze.tint = (Math.round(L.haze[0]) << 16) | (Math.round(L.haze[1]) << 8) | Math.round(L.haze[2]);
  ctx.haze.alpha = L.hazeAlpha;
  ctx.floodTint = tint([Math.min(1, L.world[0] * 0.5 + 0.5), Math.min(1, L.world[1] * 0.5 + 0.5), Math.min(1, L.world[2] * 0.4 + 0.6)]);
}

function drawPeople(ctx: Ctx, props: IsoProps, t: number, now: number) {
  if (ctx.awFor !== props.playback) {
    ctx.awFor = props.playback;
    const { strolls, strollCum, strollers, flood } = ctx.aw;
    ctx.aw = agentWorld(ctx.p, ctx.scene.insideBuilding, ctx.scene.onRoad, props.playback);
    Object.assign(ctx.aw, { strolls, strollCum, strollers, flood });
  }
  // a seek (scrub, replay switch): no strides or springs carried across the jump
  if (t < ctx.lastT || t - ctx.lastT > 600) ctx.crowd.reset();
  const dtS = Math.min(0.1, Math.max(0, now - ctx.lastNow));
  const { cam, app } = ctx;
  const view = { x0: -cam.x / cam.s, y0: -cam.y / cam.s, x1: (app.screen.width - cam.x) / cam.s, y1: (app.screen.height - cam.y) / cam.s };
  const requested = populationAtZoom(cam.s);
  const strollCount = ctx.crowdBudget.sample((now - ctx.lastNow) * 1000, requested);
  const figureK = figureScale(ctx.scene.atlas.figureM * KZ, cam.s);
  const agents = buildAgents({ w: ctx.aw, state: props.state, t, walkers: props.walkers, now, strollCount, view, figureHeight: ctx.scene.atlas.figureM * KZ * figureK * 1.1, figureHalfWidth: 0.5 * figureK });
  ctx.crowd.update(agents, dtS, cam.s, view, tint(lightAt(t).people));
  ctx.decals.clear();
  ctx.top.clear();
  const sel = props.selection?.kind === "household" ? props.selection.id : props.follow?.kind === "household" ? props.follow.id : null;
  ctx.crowd.drawSelection(ctx.decals, ctx.top, sel, cam.s, now);
}

function drawVehicles(ctx: Ctx, props: IsoProps, now: number) {
  const selected = props.selection?.kind === "resource" ? props.selection.id : props.follow?.kind === "resource" ? props.follow.id : null;
  ctx.fleet.update(props.state.resources, { now, selected, lights: lightAt(props.t).lights, tint: ctx.scene.light.tint, depthFor: ctx.scene.depthFor });
}

// ---------- screen-space markers, labels, hit targets ----------

/** Map label scale: 13 px text at 1440 wide (projector-readable), growing with the window up to 1.4×. */
function uiScale(): number {
  return (13 / 11) * Math.max(1, Math.min(1.4, window.innerWidth / 1440));
}

function pill(ctx: Ctx, key: string, text: string, x: number, y: number, style: { bg: number; fg?: number; size?: number; border?: number }, prio: number = PRIO.ALWAYS) {
  const k = uiScale();
  const size = Math.round((style.size ?? 11) * k);
  const maxTextWidth = Math.max(80, ctx.app.screen.width - 24 * k);
  let item = ctx.pills.get(key);
  if (!item) {
    const root = new Container();
    const bg = new Graphics();
    const label = new Text({ text, style: { fontFamily: "Inter, system-ui, sans-serif", fontSize: style.size ?? 11, fontWeight: "700", fill: style.fg ?? 0xffffff, letterSpacing: 0.4 }, resolution: 2 });
    root.addChild(bg, label);
    ctx.pillLayer.addChild(root);
    item = { root, bg, text: label, key: "", used: true, w: 0, h: 0 };
    ctx.pills.set(key, item);
  }
  const sig = `${text}|${style.bg}|${style.border ?? 0}|${size}|${maxTextWidth}`;
  if (item.key !== sig) {
    item.key = sig;
    item.text.style.fontSize = size;
    item.text.style.wordWrap = true;
    item.text.style.wordWrapWidth = maxTextWidth;
    item.text.style.breakWords = true;
    item.text.text = text;
    const w = item.text.width + 12 * k;
    const h = item.text.height + 5 * k;
    item.bg.clear().roundRect(-w / 2, -h, w, h, 5 * k).fill({ color: style.bg, alpha: 0.94 });
    if (style.border) item.bg.roundRect(-w / 2, -h, w, h, 5 * k).stroke({ width: 1.4, color: style.border });
    item.text.position.set(-item.text.width / 2, -h + 2.5 * k);
    item.w = w;
    item.h = h;
  }
  item.used = true;
  queued.push({ item, x: Math.round(x), y: Math.round(y), prio });
}

/** Place the queued labels by priority; a label that would overlap one already placed is hidden. */
function placeLabels(ctx: Ctx) {
  queued.sort((a, b) => b.prio - a.prio);
  const placed: Array<[number, number, number, number]> = [];
  const W = ctx.app.screen.width;
  const H = ctx.app.screen.height;
  const box = (x: number, y: number, item: { w: number; h: number }): [number, number, number, number] => [x - item.w / 2 - 2, y - item.h - 2, x + item.w / 2 + 2, y + 2];
  const over = (r: [number, number, number, number]) => placed.find((q) => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1]);
  for (const { item, x: x0, y: y0, prio } of queued) {
    // Keep important names readable on narrow displays; their markers still show the actual location.
    const x = prio >= PRIO.JUDGE && prio < PRIO.ALWAYS
      ? Math.max(item.w / 2 + 6, Math.min(W - item.w / 2 - 6, x0)) : x0;
    let y = y0;
    let r = box(x, y, item);
    // the judge, players and the selection never yield: a clash lifts them above what is already there
    if (prio >= PRIO.JUDGE) {
      for (let k = 0, q = over(r); q && k < 6; k++, q = over(r)) {
        y = q[1] - 4;
        r = box(x, y, item);
      }
    }
    const off = r[2] < 0 || r[0] > W || r[3] < 0 || r[1] > H;
    // everything else gives way to what is already placed
    const clash = prio < PRIO.JUDGE && !!over(r);
    item.root.visible = !off && !clash;
    if (!item.root.visible) continue;
    item.root.position.set(x, y);
    placed.push(r);
  }
  queued.length = 0;
}

function hit(ctx: Ctx, key: string, x: number, y: number, r: number, select: Selection) {
  let target = ctx.hits.getChildByLabel(key) as Graphics | null;
  if (!target) {
    const hitTarget = new Graphics().circle(0, 0, 1).fill({ color: 0xffffff, alpha: 0.001 });
    hitTarget.label = key;
    hitTarget.eventMode = "static";
    hitTarget.cursor = "pointer";
    hitTarget.on("pointertap", (e: FederatedPointerEvent) => {
      e.stopPropagation();
      if (!ctx.drag.moved) currentSelect?.({ ...select });
    });
    ctx.hits.addChild(hitTarget);
    target = hitTarget;
  }
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

  // landmarks (real buildings): reference, so only zoomed in, and they yield to everything else
  if (zoomed) {
    for (const lm of ctx.scene.labels) {
      const [x, y] = toScreen(ctx, ...p.iso(lm.at[0], lm.at[1], lm.at[2] + 4));
      pill(ctx, `lm:${lm.text}`, lm.text, x, y, { bg: 0x1b1f27, fg: 0xe9e3d6, size: 10 }, PRIO.LANDMARK);
    }
  }

  // facilities: on stage → a base marker; off stage → an edge tile pointing to where it is
  const offStage: Array<{ facility: StateFacility; at: [number, number] }> = [];
  for (const facility of props.state.facilities) {
    if (p.inside(facility.lon, facility.lat)) continue;
    const [a, b] = p.toAB(facility.lon, facility.lat);
    offStage.push({ facility, at: edgePoint(p, a, b, 14) });
  }

  for (const facility of props.state.facilities) {
    const meta = FACILITY[facility.type] ?? { color: 0x888888, glyph: "?" };
    const ring = STATE_RING[facility.state] ?? 0x888888;
    const onStage = p.inside(facility.lon, facility.lat);
    let x: number;
    let y: number;
    if (onStage) {
      [x, y] = toScreen(ctx, ...p.lonlat(facility.lon, facility.lat, 22));
    } else {
      const item = offStage.find((o) => o.facility.id === facility.id)!;
      [x, y] = toScreen(ctx, ...p.iso(item.at[0], item.at[1], 0));
      const [fa, fb] = p.toAB(facility.lon, facility.lat);
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
    // the name only when it matters: something is wrong there, it is selected, or the camera is close.
    // The shelter is the venue: its name goes on the YOU ARE HERE pill.
    const picked = props.selection?.kind === "facility" && props.selection.id === facility.id;
    if (facility.type !== "shelter" && (alarm || picked || zoomed)) {
      const state = facility.state === "backup" ? ` · on backup${facility.endurance_left_s != null ? ` ${Math.round(facility.endurance_left_s / 60)} min` : ""}` : facility.state === "down" ? " · DOWN" : "";
      pill(ctx, `fac:${facility.id}`, `${facility.name}${state}`, x, y - 17, { bg: 0x161a22, border: alarm ? ring : undefined }, picked ? PRIO.SELECTED : alarm ? PRIO.ALARM : PRIO.FACILITY);
    }
    hit(ctx, `hit:fac:${facility.id}`, x, y, 16, { kind: "facility", id: facility.id });
  }

  // you are here: the venue the judges are standing in, above its shelter marker
  {
    const [x, y] = toScreen(ctx, ...p.lonlat(town.venue.lon, town.venue.lat, 22));
    pill(ctx, "venue", `YOU ARE HERE · ${town.venue.name}`, x, y - 17, { bg: 0xffc542, fg: 0x1a1406, size: 10 }, PRIO.VENUE);
  }

  // incidents: households still waiting, and every drill player's home; zoomed out, an ordinary household is a dot
  const close = ctx.cam.s > ctx.fitS * 2;
  for (const household of props.state.households) {
    if (!p.inside(household.lon, household.lat)) continue;
    const waiting = household.status === "needs" || household.status === "unknown" || household.status === "assigned" || household.status === "confirmed";
    const lost = household.status === "unreached";
    const player = props.players.get(household.household_id);
    const selected = props.selection?.kind === "household" && props.selection.id === household.household_id;
    if (!waiting && !lost && !player && !selected) continue;
    const gold = household.judge || player != null;
    const color = toHex(householdColor(household));
    const [gx, gy] = toScreen(ctx, ...p.lonlat(...waitLonLat(ctx.aw, household)));
    if (!close && !gold && !selected) {
      g.circle(gx, gy - 6, 5).fill(color).stroke({ width: 1.5, color: 0xffffff });
      hit(ctx, `hit:hh:${household.household_id}`, gx, gy - 6, 10, { kind: "household", id: household.household_id });
      continue;
    }
    const urgent = household.status === "needs" || household.status === "unknown";
    if (urgent) g.ellipse(gx, gy, (14 + 10 * pulse) * Math.min(1.6, Math.max(0.6, ctx.cam.s * 0.5)), (7 + 5 * pulse) * Math.min(1.6, Math.max(0.6, ctx.cam.s * 0.5))).stroke({ width: 2, color, alpha: 0.85 - 0.5 * pulse });
    const py = gy - 30;
    g.moveTo(gx, gy - 4).lineTo(gx, py + 9).stroke({ width: 1.5, color, alpha: 0.9 });
    if (player?.onCall) g.circle(gx, py, 16 + 10 * pulse).stroke({ width: 3, color: 0xffc542, alpha: 1 - 0.7 * pulse });
    g.circle(gx, py, 10).fill(gold ? 0xffc542 : color).stroke({ width: 2, color: 0xffffff });
    // deadline ring: the share of the time left before the water reaches them
    if (household.deadline_s && waiting) {
      const left = Math.max(0, Math.min(1, (household.deadline_s - props.t) / household.deadline_s));
      g.moveTo(gx, py - 13).arc(gx, py, 13, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * left).stroke({ width: 2.5, color: left < 0.25 ? 0xe5484d : 0xffffff, alpha: 0.95 });
    }
    pill(ctx, `n:${household.household_id}`, String(peopleCount(household, 1)), gx, py + 7, { bg: gold ? 0xffc542 : color, fg: gold ? 0x1a1406 : 0xffffff, size: 11 }, PRIO.ALWAYS);
    if (gold || selected) {
      const needs = household.needs;
      const extra = needs !== "unknown" && (needs.mobility || needs.accessible_vehicle) ? " · wheelchair" : needs !== "unknown" && needs.medical ? " · medical" : needs === "unknown" ? " · needs unknown" : "";
      const name = player ? `${player.label}${player.onCall ? " · ON CALL" : ""}` : `${household.judge ? "JUDGE · " : ""}${household.label ?? `#${household.household_id}`}`;
      pill(ctx, `hh:${household.household_id}`, `${name}${extra}`, gx, py - 16, { bg: 0x161a22, border: gold ? 0xffc542 : undefined, size: 10 }, selected ? PRIO.SELECTED : PRIO.JUDGE);
    }
    hit(ctx, `hit:hh:${household.household_id}`, gx, py, 14, { kind: "household", id: household.household_id });
  }

  // vehicles: labels + hit targets
  for (const r of props.state.resources) {
    if (!p.inside(r.lon, r.lat)) continue;
    const [x, y] = toScreen(ctx, ...p.lonlat(r.lon, r.lat, 8));
    const picked = (props.selection?.kind === "resource" && props.selection.id === r.id) || (props.follow?.kind === "resource" && props.follow.id === r.id);
    // a vehicle's tag: always when selected; zoomed in, for vehicles on a job
    if (picked || (zoomed && r.status !== "available")) {
      const color = KIND[r.kind]?.color ?? 0x888888;
      const aboard = r.people_on_board ? ` · ${r.people_on_board} aboard` : "";
      const eta = r.eta_s != null && r.eta_s > props.t ? ` · ${Math.round((r.eta_s - props.t) / 60)} min` : "";
      pill(ctx, `veh:${r.id}`, `${r.name}${aboard}${eta}`, x, y - 4, { bg: picked ? 0xffffff : color, fg: picked ? 0x111111 : 0xffffff, size: 10 }, picked ? PRIO.SELECTED : PRIO.VEHICLE);
    }
    hit(ctx, `hit:veh:${r.id}`, x, y + 8, 14, { kind: "resource", id: r.id });
  }

  placeLabels(ctx);
  for (const item of ctx.pills.values()) if (!item.used) item.root.visible = false;
}


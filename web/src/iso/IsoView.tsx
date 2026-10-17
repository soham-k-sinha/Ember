/**
 * PixiJS isometric stage (D52 prototype): the flood district as a clay model, with the resources as
 * the subject. World layers (ground, flood, trails, buildings, vehicles, people) live in a camera
 * container; markers and labels are drawn in screen space so they stay crisp and readable at any zoom.
 */

import { useEffect, useRef } from "react";
import { Application, Container, Graphics, Sprite, Text, type FederatedPointerEvent } from "pixi.js";
import { loadDiorama, type Diorama } from "./data";
import { agentWorld, buildAgents, setScene, waitLonLat, type AgentWorld } from "./agents";
import { Crowd } from "./crowd";
import { FloodWater } from "./water";
import { clockLabel, lightAt, tint } from "./lighting";
import { SKY_BG } from "./palette";
import { scenario, town } from "../fixtures";
import { householdColor, peopleCount, type LegendMode } from "../layers";
import type { WalkerPlan } from "../people";
import { pathAhead, type Playback } from "../playback";
import type { Closure, Selection, StateFacility, StateResource, StateSnapshot } from "../types";
import { edgePoint, projector, type Projector } from "./project";
import { buildStatic, type StaticScene } from "./scene";

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
  /** camera presets (Treehouse, Judge's corner…): ease the stage camera to a place */
  focus?: { lon: number; lat: number; zoom: number; key: number } | null;
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
  propsRef.current = props;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let dead = false;
    let ready = false;
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
      if (dead || !data) return;
      const p = projector(data.bbox);
      const scene = buildStatic(data, p);
      const world = new Container();
      const dyn = new Container();
      const flood = new FloodWater(p, scenario.hazard.keyframes);
      const closed = new Graphics();
      const trails = new Graphics();
      const decals = new Graphics();
      const marks = new Container();
      dyn.addChild(flood.root, closed, trails, marks, decals);
      dyn.mask = scene.slabMask;
      const top = new Graphics();
      world.addChild(scene.slab, scene.ground, scene.tiles.ground, scene.shadow, scene.tiles.shadow, scene.pools, scene.slabMask, dyn, scene.objects, top);
      const crowd = new Crowd(scene.objects, marks, scene.atlas, p, scene.depthFor);
      const aw = agentWorld(p, scene.insideBuilding, scene.onRoad, propsRef.current.playback);
      setScene(aw, data, scenario.hazard.keyframes, [town.venue.lon, town.venue.lat]);
      const overlay = new Graphics();
      const hits = new Container();
      const pillLayer = new Container();
      const haze = hazeSprite();
      app.stage.addChild(world, haze, overlay, pillLayer, hits);

      // camera: fit the stage
      const b = scene.slab.getLocalBounds();
      const s = Math.min(app.screen.width / (b.width * 1.08), app.screen.height / (b.height * 1.12));
      const cam = { s, x: app.screen.width / 2 - (b.x + b.width / 2) * s, y: app.screen.height / 2 - (b.y + b.height / 2) * s };
      const ctx: Ctx = {
        app, data, p, scene, world, dyn, flood, floodTint: 0xffffff, closed, trails, decals, marks, top, crowd, aw, awFor: propsRef.current.playback, lastT: propsRef.current.t, lastNow: performance.now() / 1000, vehicles: new Map(), lightKey: "", fitS: s, focusKey: 0, target: null, overlay, haze, hits, pills: new Map(), pillLayer,
        closedKey: "", cam, drag: { on: false, moved: false, x: 0, y: 0 },
      };
      ctxRef.current = ctx;
      if (import.meta.env.DEV) (window as unknown as { __iso?: { app: Application; ctx: Ctx; frame: () => void; props: () => IsoProps } }).__iso = { app, ctx, frame: () => frame(ctx, propsRef.current), props: () => propsRef.current };

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
  // presets: ease to the requested place (zoom 14.3 ≈ the whole stage, each level doubles)
  if (props.focus && props.focus.key !== ctx.focusKey) {
    ctx.focusKey = props.focus.key;
    if (props.focus.zoom <= 14.4) {
      // the district preset: the whole stage, fitted and centred
      const bb = ctx.scene.slab.getLocalBounds();
      const s = Math.min(ctx.app.screen.width / (bb.width * 1.06), ctx.app.screen.height / (bb.height * 1.1));
      ctx.target = { s, x: ctx.app.screen.width / 2 - (bb.x + bb.width / 2) * s, y: ctx.app.screen.height / 2 - (bb.y + bb.height / 2) * s };
    } else {
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
  applyLight(ctx, t);
  {
    const view = { x0: -cam.x / cam.s, y0: -cam.y / cam.s, x1: (ctx.app.screen.width - cam.x) / cam.s, y1: (ctx.app.screen.height - cam.y) / cam.s };
    const sharp = ctx.scene.tiles.update(view, cam.s, ctx.scene.light.tint);
    ctx.scene.shadow.visible = !sharp;
    ctx.scene.tiles.shadow.alpha = ctx.scene.shadow.alpha;
  }

  drawFlood(ctx, props, now);
  drawClosures(ctx, props);
  drawTrails(ctx, props, t);
  drawPeople(ctx, props, t, now);
  ctx.lastT = t;
  ctx.lastNow = now;
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
  for (const item of ctx.scene.cullables) item.node.visible = hit(item.bounds);
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
    const { strolls, strollCum, flood } = ctx.aw;
    ctx.aw = agentWorld(ctx.p, ctx.scene.insideBuilding, ctx.scene.onRoad, props.playback);
    Object.assign(ctx.aw, { strolls, strollCum, flood });
  }
  // a seek (scrub, replay switch): no strides or springs carried across the jump
  if (t < ctx.lastT || t - ctx.lastT > 600) ctx.crowd.reset();
  const dtS = Math.min(0.1, Math.max(0, now - ctx.lastNow));
  const agents = buildAgents({ w: ctx.aw, state: props.state, t, legend: props.legend, walkers: props.walkers, showWalkers: props.showWalkers, now });
  const { cam, app } = ctx;
  const view = { x0: -cam.x / cam.s, y0: -cam.y / cam.s, x1: (app.screen.width - cam.x) / cam.s, y1: (app.screen.height - cam.y) / cam.s };
  ctx.crowd.update(agents, dtS, cam.s, view, tint(lightAt(t).people));
  ctx.decals.clear();
  ctx.top.clear();
  const sel = props.selection?.kind === "household" ? props.selection.id : props.follow?.kind === "household" ? props.follow.id : null;
  ctx.crowd.drawSelection(ctx.decals, ctx.top, sel, cam.s, now);
}

/** Oriented vehicle seen in iso: footprint L×W (m), height H, light bar and headlights glowing after dusk. */
function vehicle(g: Graphics, p: Projector, r: StateResource, now: number, selected: boolean, lights: number, ox: number, oy: number) {
  const [a, b] = p.toAB(r.lon, r.lat);
  const hd = ((r.heading_deg ?? 0) * Math.PI) / 180;
  const fa = Math.sin(hd);
  const fb = -Math.cos(hd);
  const sa = -fb;
  const sb = fa;
  const big = r.kind === "truck" || r.kind === "generator" ? 1.3 : 1;
  const L = 6.2 * big;
  const W = 2.5 * big;
  const H = 2.4 * big;
  const corner = (u: number, v: number): [number, number] => [a + fa * u + sa * v, b + fb * u + sb * v];
  const iso = (x: number, y: number, z = 0): [number, number] => {
    const [sx, sy] = p.iso(x, y, z);
    return [sx - ox, sy - oy];
  };
  const base = [corner(L / 2, -W / 2), corner(L / 2, W / 2), corner(-L / 2, W / 2), corner(-L / 2, -W / 2)];
  const color = KIND[r.kind]?.color ?? 0x888888;
  g.poly(base.flatMap(([x, y]) => iso(x + 0.8, y - 0.3))).fill({ color: 0x000000, alpha: 0.3 });
  for (let i = 0; i < 4; i++) {
    const [a1, b1] = base[i];
    const [a2, b2] = base[(i + 1) % 4];
    const na = b2 - b1;
    const nb = -(a2 - a1);
    if (na + nb <= 0) continue;
    const len = Math.hypot(na, nb) || 1;
    g.poly([...iso(a1, b1, 0.35), ...iso(a2, b2, 0.35), ...iso(a2, b2, H), ...iso(a1, b1, H)]).fill(shadeHex(color, 0.6 * (na / len) ** 2 + 0.84 * (nb / len) ** 2 + 0.1)).stroke({ width: 0.12, color: 0x101010, alpha: 0.6 });
    // wheels
    g.poly([...iso(a1, b1, 0), ...iso(a2, b2, 0), ...iso(a2, b2, 0.4), ...iso(a1, b1, 0.4)]).fill({ color: 0x1a1a1a, alpha: 0.9 });
  }
  g.poly(base.flatMap(([x, y]) => iso(x, y, H))).fill(shadeHex(color, 1.08)).stroke({ width: selected ? 0.5 : 0.12, color: selected ? 0xffffff : 0x101010, alpha: selected ? 1 : 0.6 });
  const [wa1, wb1] = corner(L / 2 - 0.3, -W / 2 + 0.35);
  const [wa2, wb2] = corner(L / 2 - 0.3, W / 2 - 0.35);
  const [wa3, wb3] = corner(L / 2 - 1.5, W / 2 - 0.35);
  const [wa4, wb4] = corner(L / 2 - 1.5, -W / 2 + 0.35);
  g.poly([...iso(wa1, wb1, H + 0.02), ...iso(wa2, wb2, H + 0.02), ...iso(wa3, wb3, H + 0.02), ...iso(wa4, wb4, H + 0.02)]).fill(0x1d2a36);
  if (r.status === "en_route" || r.status === "returning" || r.status === "working") {
    const on = Math.floor(now * 5) % 2 === 0;
    const [la, lb] = corner(-0.2, -W / 4);
    const [ra, rb] = corner(-0.2, W / 4);
    g.rect(...iso(la, lb, H + 0.35), 0.7, 0.45).fill(on ? 0xff3b3b : 0x5a1010);
    g.rect(...iso(ra, rb, H + 0.35), 0.7, 0.45).fill(on ? 0x2a1a60 : 0x4d8dff);
    const glowAlpha = 0.35 + 0.65 * lights;
    g.circle(...iso(on ? la : ra, on ? lb : rb, H + 0.5), 2.2).fill({ color: on ? 0xff3030 : 0x3a7dff, alpha: 0.28 * glowAlpha });
  }
  if (lights > 0.05 && r.status !== "available") {
    const [ha, hb] = corner(L / 2 + 6, 0);
    const [l1a, l1b] = corner(L / 2, -W / 2 + 0.3);
    const [l2a, l2b] = corner(L / 2, W / 2 - 0.3);
    const [s1a, s1b] = corner(L / 2 + 7, -2.6);
    const [s2a, s2b] = corner(L / 2 + 7, 2.6);
    void ha;
    void hb;
    g.poly([...iso(l1a, l1b, 0.7), ...iso(s1a, s1b, 0), ...iso(s2a, s2b, 0), ...iso(l2a, l2b, 0.7)]).fill({ color: 0xfff1c8, alpha: 0.22 * lights });
  }
}

function shadeHex(c: number, k: number): number {
  const r = Math.min(255, Math.round(((c >> 16) & 255) * k));
  const g = Math.min(255, Math.round(((c >> 8) & 255) * k));
  const b = Math.min(255, Math.round((c & 255) * k));
  return (r << 16) | (g << 8) | b;
}

function drawVehicles(ctx: Ctx, props: IsoProps, now: number) {
  const sel = props.selection?.kind === "resource" ? props.selection.id : props.follow?.kind === "resource" ? props.follow.id : null;
  const lights = lightAt(props.t).lights;
  const seen = new Set<string>();
  for (const r of props.state.resources) {
    let g = ctx.vehicles.get(r.id);
    if (!g) {
      g = new Graphics();
      ctx.scene.objects.addChild(g);
      ctx.vehicles.set(r.id, g);
    }
    g.clear();
    if (!ctx.p.inside(r.lon, r.lat)) {
      g.visible = false;
      continue;
    }
    seen.add(r.id);
    const [a, b] = ctx.p.toAB(r.lon, r.lat);
    const [ox, oy] = ctx.p.iso(a, b);
    g.position.set(ox, oy);
    vehicle(g, ctx.p, r, now, r.id === sel, lights, ox, oy);
    g.zIndex = ctx.scene.depthFor(a, b, ox, oy, 4, 4);
    g.visible = true;
  }
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

  // landmarks (real buildings) and the illustrative clock
  if (ctx.cam.s > 0.75) {
    for (const lm of ctx.scene.labels) {
      const [x, y] = toScreen(ctx, ...p.iso(lm.at[0], lm.at[1], lm.at[2] + 4));
      pill(ctx, `lm:${lm.text}`, lm.text, x, y, { bg: 0x1b1f27, fg: 0xe9e3d6, size: 10 });
    }
  }
  pill(ctx, "clock", `${clockLabel(props.t)} · illustrative clock`, 92, ctx.app.screen.height - 14, { bg: 0x161a22, fg: 0xd9d3c6, size: 11 });

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
    const [gx, gy] = toScreen(ctx, ...p.lonlat(...waitLonLat(ctx.aw, household)));
    const urgent = household.status === "needs" || household.status === "unknown";
    if (urgent) g.ellipse(gx, gy, (14 + 10 * pulse) * Math.min(1.6, Math.max(0.6, ctx.cam.s * 0.5)), (7 + 5 * pulse) * Math.min(1.6, Math.max(0.6, ctx.cam.s * 0.5))).stroke({ width: 2, color, alpha: 0.85 - 0.5 * pulse });
    const py = gy - 30;
    g.moveTo(gx, gy - 4).lineTo(gx, py + 9).stroke({ width: 1.5, color, alpha: 0.9 });
    g.circle(gx, py, 10).fill(household.judge ? 0xffc542 : color).stroke({ width: 2, color: 0xffffff });
    // deadline ring: the share of the time left before the water reaches them
    if (household.deadline_s && waiting) {
      const left = Math.max(0, Math.min(1, (household.deadline_s - props.t) / household.deadline_s));
      g.moveTo(gx, py - 13).arc(gx, py, 13, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * left).stroke({ width: 2.5, color: left < 0.25 ? 0xe5484d : 0xffffff, alpha: 0.95 });
    }
    pill(ctx, `n:${household.household_id}`, String(peopleCount(household, 1)), gx, py + 7, { bg: household.judge ? 0xffc542 : color, fg: household.judge ? 0x1a1406 : 0xffffff, size: 11 });
    if (household.judge || (props.selection?.kind === "household" && props.selection.id === household.household_id)) {
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


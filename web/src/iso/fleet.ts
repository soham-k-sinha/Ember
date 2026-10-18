/**
 * The response fleet on the stage, modelled after the real vehicle types (D71): an ambulance-style high-roof
 * van, a box ambulance with a red cross on its roof, a wheelchair-accessible van with a rear lift, a box truck carrying a generator, a road-crew pickup, and
 * towed generator trailers. Each model is built once per heading (16) from shaded boxes and pre-rendered to a
 * texture; per frame a vehicle is a sprite plus a small additive layer for its flashing light bar, headlights
 * after dusk, and the selection ring. Positions and headings are the engine's playback tracks.
 */

import { Container, Graphics, Sprite, type Renderer, type Texture } from "pixi.js";
import { obox } from "./props";
import type { Projector } from "./project";
import type { StateResource } from "../types";

const HEADINGS = 16;
const RES = 12; // texture px per metre: sharp at the closest zoom

type Model = { draw: (g: Graphics, p: Projector, ang: number) => void; bar: { u: number; z: number; colors: [number, number] } | null; L: number };

const WHITE = 0xf1efe9;
const GLASS = 0x1c2832;
const TYRE = 0x161616;

/** Body helper: a box of length L along the heading, offset u forward of the vehicle centre. */
function part(g: Graphics, p: Projector, ang: number, u: number, L: number, W: number, z0: number, z1: number, color: number, edge = 0x101010, top = true) {
  const fa = Math.cos(ang);
  const fb = Math.sin(ang);
  obox(g, p, 0, 0, fa * u, fb * u, ang, L, W, z0, z1, color, edge, top);
}

/** A band painted on the body (stripe, windows): side faces only, so it never covers the body above it. */
function band(g: Graphics, p: Projector, ang: number, u: number, L: number, W: number, z0: number, z1: number, color: number, edge = 0x101010) {
  part(g, p, ang, u, L, W, z0, z1, color, edge, false);
}

function wheels(g: Graphics, p: Projector, ang: number, axles: number[], W: number) {
  for (const u of axles) part(g, p, ang, u, 0.8, W + 0.12, 0, 0.62, TYRE, 0x000000);
}

function shadow(g: Graphics, p: Projector, ang: number, L: number, W: number) {
  const fa = Math.cos(ang);
  const fb = Math.sin(ang);
  const pts = [[L / 2, -W / 2], [L / 2, W / 2], [-L / 2, W / 2], [-L / 2, -W / 2]].map(([u, v]) => p.iso(fa * u - fb * v + 0.5, fb * u + fa * v - 0.2));
  g.poly(pts.flat()).fill({ color: 0x000000, alpha: 0.3 });
}

const MODELS: Record<string, Model> = {
  // ambulance-style high-roof van: white body, coloured stripe, cab glass, roof light bar
  van: {
    L: 6.2,
    bar: { u: 1.0, z: 2.75, colors: [0xff3434, 0x3a7dff] },
    draw: (g, p, a) => {
      shadow(g, p, a, 6.2, 2.1);
      wheels(g, p, a, [2.05, -1.9], 2.0);
      part(g, p, a, -0.5, 4.9, 2.1, 0.45, 2.6, WHITE); // box body
      part(g, p, a, 2.35, 1.5, 2.0, 0.45, 1.25, WHITE); // bonnet
      part(g, p, a, 2.0, 0.9, 2.02, 1.25, 2.05, GLASS); // windscreen + cab glass
      band(g, p, a, -0.5, 4.92, 2.14, 1.05, 1.32, 0x2f6fe0, 0x1a3e80); // stripe
      part(g, p, a, 1.0, 0.5, 1.4, 2.6, 2.75, 0x2a2a2e); // light bar housing
    },
  },
  // box ambulance: white cab and taller box body, red stripe, red cross on the roof, red/white light bar
  ambulance: {
    L: 6.8,
    bar: { u: 1.55, z: 3.05, colors: [0xff2a2a, 0xffffff] },
    draw: (g, p, a) => {
      shadow(g, p, a, 6.8, 2.3);
      wheels(g, p, a, [2.3, -2.1], 2.2);
      part(g, p, a, -0.75, 4.6, 2.3, 0.5, 2.9, WHITE); // box body
      part(g, p, a, 2.25, 1.5, 2.0, 0.5, 2.05, WHITE); // cab
      part(g, p, a, 2.7, 0.6, 2.02, 1.3, 1.95, GLASS); // windscreen
      part(g, p, a, 3.25, 0.5, 2.0, 0.5, 1.2, WHITE); // bonnet
      band(g, p, a, -0.75, 4.62, 2.34, 1.15, 1.5, 0xd62828, 0x7a1010); // stripe
      band(g, p, a, -0.75, 4.62, 2.34, 2.55, 2.7, 0xd62828, 0x7a1010); // roofline band
      part(g, p, a, -0.75, 2.2, 0.55, 2.9, 2.94, 0xd62828, 0xd62828); // roof cross
      part(g, p, a, -0.75, 0.55, 2.0, 2.9, 2.94, 0xd62828, 0xd62828);
      part(g, p, a, 1.55, 0.45, 1.6, 2.9, 3.05, 0x2a2a2e); // light bar housing
    },
  },
  // wheelchair-accessible van: the same body in purple livery, side windows, a rear lift platform
  accessible_van: {
    L: 6.6,
    bar: { u: 1.0, z: 2.75, colors: [0xffb020, 0xffb020] },
    draw: (g, p, a) => {
      shadow(g, p, a, 6.6, 2.1);
      wheels(g, p, a, [2.05, -1.9], 2.0);
      part(g, p, a, -3.25, 0.7, 1.7, 0.35, 0.45, 0x8f969c); // lift platform
      part(g, p, a, -0.5, 4.9, 2.1, 0.45, 2.6, WHITE);
      part(g, p, a, 2.35, 1.5, 2.0, 0.45, 1.25, WHITE);
      part(g, p, a, 2.0, 0.9, 2.02, 1.25, 2.05, GLASS);
      band(g, p, a, -0.6, 3.6, 2.13, 1.55, 2.1, GLASS); // side windows
      band(g, p, a, -0.5, 4.92, 2.14, 1.05, 1.3, 0x8a4fe0, 0x4a2a80); // stripe
      part(g, p, a, 1.0, 0.5, 1.4, 2.6, 2.75, 0x2a2a2e);
    },
  },
  // generator truck: orange cab, flatbed with a diesel generator set
  truck: {
    L: 8.4,
    bar: { u: 2.9, z: 3.15, colors: [0xffb020, 0xffb020] },
    draw: (g, p, a) => {
      shadow(g, p, a, 8.4, 2.4);
      wheels(g, p, a, [3.0, -1.4, -2.7], 2.3);
      part(g, p, a, -1.1, 6.0, 2.4, 0.75, 1.05, 0x3b3f44); // bed
      part(g, p, a, 2.95, 2.3, 2.35, 0.6, 2.95, 0xe0782f, 0x6a3510); // cab
      part(g, p, a, 3.75, 0.7, 2.37, 1.75, 2.6, GLASS); // windscreen
      part(g, p, a, -1.2, 4.6, 2.2, 1.05, 2.9, 0x4f6b4a, 0x23331f); // generator enclosure
      band(g, p, a, -1.2, 4.62, 2.22, 2.2, 2.4, 0x3c5238, 0x1c2a19); // vent band
      part(g, p, a, -2.8, 0.5, 0.5, 2.9, 3.5, 0x2a2a2a); // exhaust stack
      part(g, p, a, 2.9, 0.5, 1.6, 2.95, 3.1, 0x2a2a2e);
    },
  },
  // road crew: white pickup with orange stripe, cones in the bed, amber beacon
  crew: {
    L: 5.6,
    bar: { u: 0.4, z: 2.15, colors: [0xffb020, 0xffb020] },
    draw: (g, p, a) => {
      shadow(g, p, a, 5.6, 2.0);
      wheels(g, p, a, [1.8, -1.6], 1.9);
      part(g, p, a, -1.5, 2.4, 2.0, 0.55, 1.15, WHITE); // bed
      part(g, p, a, 2.1, 1.4, 1.95, 0.55, 1.2, WHITE); // bonnet
      part(g, p, a, 0.55, 1.9, 1.95, 0.55, 2.0, WHITE); // cab
      part(g, p, a, 1.4, 0.4, 1.97, 1.25, 1.9, GLASS);
      band(g, p, a, 0.0, 5.0, 2.03, 0.8, 0.98, 0xff7a1a, 0x7a3500); // stripe
      for (const [u, v] of [[-1.0, -0.5], [-1.8, 0.4], [-2.3, -0.4]] as const) {
        const fa = Math.cos(a);
        const fb = Math.sin(a);
        obox(g, p, 0, 0, fa * u - fb * v, fb * u + fa * v, a, 0.35, 0.35, 1.15, 1.75, 0xff6a00, 0x803000); // cones
      }
      part(g, p, a, 0.4, 0.4, 1.3, 2.0, 2.12, 0x2a2a2e);
    },
  },
  // generator on a trailer behind a tow pickup
  generator: {
    L: 10.4,
    bar: { u: 3.4, z: 2.15, colors: [0xffb020, 0xffb020] },
    draw: (g, p, a) => {
      shadow(g, p, a, 10.4, 2.1);
      wheels(g, p, a, [4.4, 1.9, -3.0], 1.9);
      part(g, p, a, -0.6, 1.2, 0.2, 0.55, 0.7, 0x3a3a3a); // tow bar
      part(g, p, a, -3.0, 3.8, 2.0, 0.55, 0.85, 0x3b3f44); // trailer deck
      part(g, p, a, -3.0, 3.4, 1.8, 0.85, 2.3, 0xe8b51e, 0x6a520a); // generator set
      band(g, p, a, -3.0, 3.42, 1.82, 1.5, 1.75, 0xc79a12, 0x5a4508); // vent band
      part(g, p, a, 2.6, 2.4, 2.0, 0.55, 1.15, 0xdad6cc); // pickup bed
      part(g, p, a, 4.75, 1.3, 1.95, 0.55, 1.2, 0xdad6cc);
      part(g, p, a, 3.4, 1.9, 1.95, 0.55, 2.0, 0xdad6cc);
      part(g, p, a, 4.25, 0.4, 1.97, 1.25, 1.9, GLASS);
      part(g, p, a, 3.4, 0.4, 1.3, 2.0, 2.12, 0x2a2a2e);
    },
  },
};

type Frame = { tex: Texture; ax: number; ay: number };
type Unit = { root: Container; body: Sprite; fx: Graphics };

export class Fleet {
  private frames = new Map<string, Frame[]>();
  private units = new Map<string, Unit>();

  constructor(renderer: Renderer, private objects: Container, private p: Projector) {
    for (const [kind, model] of Object.entries(MODELS)) {
      const row: Frame[] = [];
      for (let h = 0; h < HEADINGS; h++) {
        const g = new Graphics();
        model.draw(g, p, (h / HEADINGS) * Math.PI * 2);
        const b = g.getLocalBounds();
        row.push({ tex: renderer.generateTexture({ target: g, resolution: RES, antialias: true }), ax: -b.minX / (b.maxX - b.minX), ay: -b.minY / (b.maxY - b.minY) });
        g.destroy();
      }
      this.frames.set(kind, row);
    }
  }

  update(resources: StateResource[], opts: { now: number; selected: string | null; lights: number; tint: number; depthFor: (a: number, b: number, px: number, py: number, halfW: number, height: number) => number }) {
    const seen = new Set<string>();
    for (const r of resources) {
      if (!this.p.inside(r.lon, r.lat)) continue;
      const kind = MODELS[r.kind] ? r.kind : "van";
      const model = MODELS[kind];
      let u = this.units.get(r.id);
      if (!u) {
        const root = new Container();
        const body = new Sprite();
        const fx = new Graphics();
        fx.blendMode = "add";
        root.addChild(body, fx);
        root.eventMode = "none";
        this.objects.addChild(root);
        u = { root, body, fx };
        this.units.set(r.id, u);
      }
      seen.add(r.id);
      const hd = ((r.heading_deg ?? 0) * Math.PI) / 180;
      const fa = Math.sin(hd); // compass heading → ground (a east, b south)
      const fb = -Math.cos(hd);
      const ang = Math.atan2(fb, fa);
      const h = ((Math.round((ang / (Math.PI * 2)) * HEADINGS) % HEADINGS) + HEADINGS) % HEADINGS;
      const fr = this.frames.get(kind)![h];
      if (u.body.texture !== fr.tex) u.body.texture = fr.tex;
      u.body.anchor.set(fr.ax, fr.ay);
      u.body.tint = opts.tint;
      const [a, b] = this.p.toAB(r.lon, r.lat);
      const [x, y] = this.p.iso(a, b);
      u.root.position.set(x, y);
      u.root.zIndex = opts.depthFor(a, b, x, y, model.L / 2, 3.5);
      u.root.visible = true;

      // light bar, headlights, selection: drawn in the vehicle's own frame around (0, 0)
      const g = u.fx;
      g.clear();
      const iso = (da: number, db: number, z = 0): [number, number] => this.p.iso(da, db, z);
      const active = r.status === "en_route" || r.status === "returning" || r.status === "working";
      if (active && model.bar) {
        const on = Math.floor(opts.now * 5 + r.id.length) % 2 === 0;
        const side = (v: number): [number, number] => iso(fa * model.bar!.u - fb * v, fb * model.bar!.u + fa * v, model.bar!.z);
        const glow = 0.4 + 0.6 * opts.lights;
        const [lx, ly] = side(-0.45);
        const [rx, ry] = side(0.45);
        g.circle(lx, ly, on ? 1.4 : 0.6).fill({ color: model.bar.colors[0], alpha: (on ? 0.9 : 0.35) * glow });
        g.circle(rx, ry, on ? 0.6 : 1.4).fill({ color: model.bar.colors[1], alpha: (on ? 0.35 : 0.9) * glow });
        g.circle(on ? lx : rx, on ? ly : ry, 3.2).fill({ color: on ? model.bar.colors[0] : model.bar.colors[1], alpha: 0.18 * glow });
      }
      if (opts.lights > 0.05 && r.status !== "available") {
        const nose = model.L / 2;
        const pts = [[nose, -0.8, 0.7], [nose + 8, -2.8, 0], [nose + 8, 2.8, 0], [nose, 0.8, 0.7]].map(([uu, v, z]) => iso(fa * uu - fb * v, fb * uu + fa * v, z));
        g.poly(pts.flat()).fill({ color: 0xfff1c8, alpha: 0.2 * opts.lights });
      }
      if (opts.selected === r.id) {
        const rx = model.L * 0.75;
        g.ellipse(0, 0, rx, rx * 0.5).stroke({ color: 0xffffff, width: 0.35, alpha: 0.9 });
      }
    }
    for (const [id, u] of this.units) if (!seen.has(id)) u.root.visible = false;
  }
}

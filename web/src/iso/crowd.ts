/**
 * The people on the stage, drawn the Physical Realities way (D71): every person is a pooled sprite
 * pair (figure + white clothing tinted by state) that keeps its identity for as long as it is on
 * stage, so its look, height, stride and facing carry from frame to frame.
 *
 *  - Walk cycle from the distance actually displayed this frame (stride phase capped per second,
 *    so fast playback still reads as walking instead of a leg blur).
 *  - Facing from screen-horizontal motion with hysteresis (no flicker); standing people face what
 *    they are waiting for (the van that came for them, the street).
 *  - Small jumps in a standing person's target (a slot shifting) become an offset removed by a
 *    critically damped spring; big jumps (a seek) snap.
 *  - A ground mark under each person carries the state by shape as well as colour.
 *  - Depth from the scene's occlusion-aware sort, so people pass behind and in front of buildings.
 * Positions come in already computed (engine playback, walker plan); nothing here decides anything.
 */

import { Container, Graphics, Sprite } from "pixi.js";
import { LOOKS, POSES, RES, type Atlas, type Pose, type Shape } from "./atlas";
import { KZ, type Projector } from "./project";
import { figureScale, inCrowdView } from "./density";

export type Agent = {
  id: string;
  a: number; // ground metres (east)
  b: number; // ground metres (south)
  color: number; // clothing + ground mark
  shape: Shape;
  moving: boolean; // on the move (legs cycle while the display actually moves)
  pose?: Pose; // pose while standing still (wave, sit)
  faceTo?: [number, number]; // ground point to face while standing
  household?: number; // clicking selects this household
  alpha?: number;
  /** Someone the story is about: when a building hides them, draw them see-through on top instead. */
  xray?: boolean;
};

type Guest = {
  c: Container;
  person: Sprite;
  cloth: Sprite;
  decal: Sprite;
  look: number;
  height: number;
  phase: number;
  face: 1 | -1;
  faceAcc: number;
  lastA: number;
  lastB: number;
  off: { x: number; y: number; vx: number; vy: number };
  px: number;
  py: number;
  k: number;
  household?: number;
  stamp: number;
  // cached painter's depth: recomputed after ~0.8 m of movement or a zoom change
  zA: number;
  zB: number;
  zK: number;
  z: number;
  behind: boolean;
};

const WALK: Pose[] = ["walkA", "stand", "walkB", "stand"];

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

/** Critically damped spring toward 0 for a 2D offset (SmoothDamp form). */
function damp(o: Guest["off"], smoothS: number, dtS: number) {
  const w = 2 / smoothS;
  const x = w * dtS;
  const e = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
  const tx = (o.vx + w * o.x) * dtS;
  const ty = (o.vy + w * o.y) * dtS;
  o.vx = (o.vx - w * tx) * e;
  o.vy = (o.vy - w * ty) * e;
  o.x = (o.x + tx) * e;
  o.y = (o.y + ty) * e;
  if (Math.abs(o.x) < 1e-4 && Math.abs(o.y) < 1e-4 && Math.abs(o.vx) < 1e-3 && Math.abs(o.vy) < 1e-3) o.x = o.y = o.vx = o.vy = 0;
}

export type View = { x0: number; y0: number; x1: number; y1: number };
type DepthFn = (a: number, b: number, px: number, py: number, halfW: number, height: number, out?: { behind: boolean }) => number;

export class Crowd {
  private guests = new Map<string, Guest>();

  /** People drawn this frame (for the ?perf readout). */
  visibleCount(): number {
    let n = 0;
    for (const g of this.guests.values()) if (g.c.visible) n++;
    return n;
  }
  private free: Guest[] = [];
  private stamp = 0;
  private figureH: number;
  private hidden = { behind: false };

  constructor(
    private objects: Container,
    private decals: Container,
    private atlas: Atlas,
    private p: Projector,
    private depthFor: DepthFn,
  ) {
    this.figureH = atlas.figureM * KZ;
  }

  /** After a seek: no strides or springs carried across the jump. */
  reset() {
    for (const g of this.guests.values()) {
      g.lastA = g.lastB = NaN;
      g.off.x = g.off.y = g.off.vx = g.off.vy = 0;
    }
  }

  private guestFor(id: string): Guest {
    let g = this.guests.get(id);
    if (g) return g;
    const h = hashStr(id);
    g = this.free.pop();
    if (!g) {
      const pf = this.atlas.person[0][0];
      const cf = this.atlas.cloth[0];
      const df = this.atlas.decal.circle;
      const person = new Sprite(pf.tex);
      person.anchor.set(pf.ax, pf.ay);
      const cloth = new Sprite(cf.tex);
      cloth.anchor.set(cf.ax, cf.ay);
      const c = new Container();
      c.eventMode = "none"; // household picking is handled explicitly by pick()
      c.addChild(person, cloth);
      const decal = new Sprite(df.tex);
      decal.eventMode = "none";
      decal.anchor.set(df.ax, df.ay);
      this.objects.addChild(c);
      this.decals.addChild(decal);
      g = { c, person, cloth, decal, look: 0, height: 1, phase: 0, face: 1, faceAcc: 0, lastA: NaN, lastB: NaN, off: { x: 0, y: 0, vx: 0, vy: 0 }, px: 0, py: 0, k: 1, stamp: 0, zA: NaN, zB: NaN, zK: 0, z: 0, behind: false };
    }
    g.look = Math.floor(h * LOOKS * 97) % LOOKS;
    g.height = 0.9 + ((h * 997) % 1) * 0.17;
    g.phase = (h * 13) % 4;
    g.face = h > 0.5 ? 1 : -1;
    g.faceAcc = 0;
    g.lastA = g.lastB = NaN;
    g.zA = g.zB = NaN;
    g.off.x = g.off.y = g.off.vx = g.off.vy = 0;
    this.guests.set(id, g);
    return g;
  }

  update(agents: Agent[], dtS: number, camS: number, view: View, peopleTint: number) {
    const stamp = ++this.stamp;
    const k = figureScale(this.figureH, camS);
    const base = 1 / RES;
    for (const agent of agents) {
      // Cull before allocating sprites, animation state or performing building-depth queries.
      const [rawX, rawY] = this.p.iso(agent.a, agent.b);
      if (!inCrowdView(rawX, rawY, view, this.figureH * k * 1.1, 0.5 * k)) continue;
      const g = this.guestFor(agent.id);
      g.stamp = stamp;
      g.household = agent.household;

      // spring away small jumps of a standing person's target; snap big ones
      if (!Number.isNaN(g.lastA) && !agent.moving) {
        const ja = agent.a + g.off.x - g.lastA;
        const jb = agent.b + g.off.y - g.lastB;
        const j = Math.hypot(ja, jb);
        if (j > 0.05 && j < 4) {
          g.off.x -= ja;
          g.off.y -= jb;
        }
      }
      damp(g.off, 0.22, dtS);
      const a = agent.a + g.off.x;
      const b = agent.b + g.off.y;

      // walk cycle and facing from the displayed motion
      const da = Number.isNaN(g.lastA) ? 0 : a - g.lastA;
      const db = Number.isNaN(g.lastB) ? 0 : b - g.lastB;
      const moved = Math.hypot(da, db);
      g.lastA = a;
      g.lastB = b;
      let pose: Pose = agent.pose ?? "stand";
      if (agent.moving && moved > 0.0005 && moved < 60) {
        g.phase = (g.phase + Math.min(moved * 2.4, dtS * 9)) % 4;
        pose = WALK[Math.floor(g.phase)];
        g.faceAcc = g.faceAcc * 0.85 + (da - db);
        if (g.faceAcc > 0.04) g.face = 1;
        else if (g.faceAcc < -0.04) g.face = -1;
      } else if (agent.faceTo) {
        const du = agent.faceTo[0] - agent.faceTo[1] - (a - b);
        if (Math.abs(du) > 0.3) g.face = du > 0 ? 1 : -1;
      }

      const [px, py] = this.p.iso(a, b);
      g.px = px;
      g.py = py;
      g.k = k;
      const hPlane = this.figureH * k * g.height;
      const on = inCrowdView(px, py, view, hPlane, 0.5 * k);
      g.c.visible = on;
      g.decal.visible = on;
      if (!on) continue;

      const pi = POSES.indexOf(pose);
      const pf = this.atlas.person[g.look][pi];
      const cf = this.atlas.cloth[pi];
      if (g.person.texture !== pf.tex) g.person.texture = pf.tex;
      if (g.cloth.texture !== cf.tex) g.cloth.texture = cf.tex;
      g.cloth.tint = mul(agent.color, peopleTint);
      g.person.tint = peopleTint;
      const s = base * k * g.height;
      g.c.position.set(px, py);
      g.c.scale.set(s * g.face, s);
      if (Number.isNaN(g.zA) || Math.abs(a - g.zA) + Math.abs(b - g.zB) > 0.8 || g.zK !== k) {
        g.z = this.depthFor(a, b, px, py, 0.4 * k, hPlane, this.hidden);
        g.behind = this.hidden.behind;
        g.zA = a;
        g.zB = b;
        g.zK = k;
      }
      let z = g.z + (a + b - g.zA - g.zB); // keep sliding with the motion between recomputes
      let alpha = agent.alpha ?? 1;
      if (agent.xray && g.behind) {
        z = 1e6 + a + b;
        alpha *= 0.55;
      }
      if (g.c.zIndex !== z) g.c.zIndex = z;
      g.c.alpha = alpha;
      const df = this.atlas.decal[agent.shape];
      if (g.decal.texture !== df.tex) g.decal.texture = df.tex;
      g.decal.tint = agent.color;
      g.decal.alpha = alpha;
      g.decal.position.set(px, py);
      g.decal.scale.set(base * Math.min(k, 2.2));
    }
    // people who left the stage this frame go back to the pool
    for (const [id, g] of this.guests) {
      if (g.stamp === stamp) continue;
      g.c.visible = false;
      g.decal.visible = false;
      this.guests.delete(id);
      this.free.push(g);
    }
  }

  /** Household of the front-most person under a screen point (generous, screen-space hit area). */
  pick(sx: number, sy: number, cam: { x: number; y: number; s: number }): number | null {
    let best: number | null = null;
    let bestD = Infinity;
    for (const g of this.guests.values()) {
      if (g.household == null || !g.c.visible) continue;
      const hPx = this.figureH * g.height * g.k * cam.s;
      const fx = cam.x + g.px * cam.s;
      const fy = cam.y + g.py * cam.s - hPx * 0.55;
      const d = Math.hypot(sx - fx, (sy - fy) * (hPx > 24 ? 0.5 : 0.8));
      if (d > Math.max(13, hPx * 0.5) || d >= bestD) continue;
      best = g.household;
      bestD = d;
    }
    return best;
  }

  /** Selection marks: a pulsing ring under each member, a thread between them, a marker over the head. */
  drawSelection(ground: Graphics, top: Graphics, household: number | null, camS: number, now: number) {
    if (household == null) return;
    const members = [...this.guests.values()].filter((g) => g.household === household && g.c.visible);
    if (!members.length) return;
    const px1 = 1 / camS;
    const pulse = 0.5 + 0.5 * Math.sin(now * 3.85);
    const ring = (g: Guest, r: number, color: number, width: number, alpha: number) => {
      const rx = r * g.k * 1.25;
      ground.ellipse(g.px, g.py, rx, rx * 0.5).stroke({ color: 0x000000, width: width + 2 * px1, alpha: alpha * 0.45 });
      ground.ellipse(g.px, g.py, rx, rx * 0.5).stroke({ color, width, alpha });
    };
    const lead = members[0];
    for (const m of members.slice(1)) {
      ground.moveTo(lead.px, lead.py).lineTo(m.px, m.py).stroke({ color: 0xf2ead8, width: 1.2 * px1, alpha: 0.45 });
      ring(m, 0.7, 0xf2ead8, 1.3 * px1, 0.8);
    }
    ring(lead, 0.95 + pulse * 0.12, 0xffffff, 2.2 * px1, 1);
    ring(lead, 1.35 + pulse * 0.35, 0xf3d79a, 1.2 * px1, 0.35 + 0.35 * (1 - pulse));
    const head = lead.py - this.figureH * lead.height * lead.k - 0.45 * lead.k - pulse * 0.15 * lead.k;
    const w = 0.42 * lead.k;
    const h = 0.5 * lead.k;
    top.poly([lead.px - w, head - h, lead.px + w, head - h, lead.px, head]).fill({ color: 0xf3d79a }).stroke({ color: 0x1b1a17, width: 1.4 * px1 });
  }
}

function mul(a: number, b: number): number {
  if (b === 0xffffff) return a;
  const r = (((a >> 16) & 255) * ((b >> 16) & 255)) / 255;
  const g = (((a >> 8) & 255) * ((b >> 8) & 255)) / 255;
  const bl = ((a & 255) * (b & 255)) / 255;
  return (Math.round(r) << 16) | (Math.round(g) << 8) | Math.round(bl);
}

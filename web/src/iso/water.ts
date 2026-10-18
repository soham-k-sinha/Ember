/**
 * Flood water on the stage, risen over the real ground. The stage carries a 4 m elevation grid (USGS 3DEP via
 * the AWS open terrain tiles). The water surface starts at the Charles and rises smoothly through each flood
 * stage of the scenario; a cell is under water when it is lower than the surface, connected to the river through
 * other wet cells, and inside the area of the flood stage being approached (the scenario's own polygon, a little
 * widened). So water spreads up the low streets and stops at rises, instead of filling straight-edged shapes.
 * Purely visual: the engine's road closures still switch at the scenario's keyframe times.
 *
 * Fallback when a stage has no elevation grid: the keyframe polygons, each fading in over ten minutes.
 */

import { CanvasSource, Container, Graphics, Matrix, Sprite, Texture, TilingSprite } from "pixi.js";
import { groundMatrix } from "./ground";
import type { Diorama } from "./data";
import type { Projector } from "./project";
import type { FloodGeometry, ScenarioKeyframe } from "../types";

const BUFFER_M = 26; // stage areas widened by this much: the scenario drew them by hand
const QUANTILE = 0.96; // at its keyframe, the surface stands over this share of the stage's ground (rises stay dry)
const LEAD_S = 1800; // the first stage's water starts rising this long before its keyframe
const STEP_M = 0.02; // recompute the wet area when the surface moves by this much

type Grid = { E: Float32Array; w: number; h: number; cell: number };

function decode(elev: NonNullable<Diorama["elev"]>): Grid {
  const bin = atob(elev.data);
  const u16 = new Uint16Array(bin.length / 2);
  for (let i = 0; i < u16.length; i++) u16[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
  const E = new Float32Array(u16.length);
  for (let i = 0; i < u16.length; i++) E[i] = elev.offset_m + u16[i] * elev.scale_m;
  return { E, w: elev.w, h: elev.h, cell: elev.cell_m };
}

function polysOf(geometry: FloodGeometry): [number, number][][][] {
  return geometry.type === "Polygon" ? [geometry.coordinates as [number, number][][]] : (geometry.coordinates as [number, number][][][]);
}

const tex = (canvas: HTMLCanvasElement) => new Texture({ source: new CanvasSource({ resource: canvas, scaleMode: "linear" }) });

function rippleTexture(): Texture {
  const c = document.createElement("canvas");
  c.width = 192;
  c.height = 96;
  const ctx = c.getContext("2d")!;
  ctx.lineCap = "round";
  let s = 7;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 26; i++) {
    const x = rnd() * 192;
    const y = rnd() * 96;
    const w = 10 + rnd() * 26;
    ctx.strokeStyle = `rgba(255,255,255,${0.25 + rnd() * 0.35})`;
    ctx.lineWidth = 1 + rnd() * 1.2;
    for (const dx of [-192, 0, 192]) {
      ctx.beginPath();
      ctx.moveTo(x + dx, y);
      ctx.quadraticCurveTo(x + dx + w / 2, y - 2.5, x + dx + w, y);
      ctx.stroke();
    }
  }
  return new Texture({ source: new CanvasSource({ resource: c, autoGenerateMipmaps: true, scaleMode: "linear" }) });
}

export class FloodWater {
  readonly root = new Container();
  private grid: Grid | null = null;
  private seed!: Uint8Array; // the Charles (always wet, drawn by the ground already)
  private env: Uint8Array[] = []; // per keyframe: its area, widened
  private times: number[] = [];
  private levels: number[] = []; // surface at each keyframe (m)
  private level0 = 0;
  private wet!: Uint8Array;
  private queue!: Int32Array;
  private canvas!: HTMLCanvasElement;
  private maskCanvas!: HTMLCanvasElement;
  private sprite!: Sprite;
  private maskSprite!: Sprite;
  private ripples!: TilingSprite;
  private key = "";
  private on = false;
  private fallback: Array<{ t: number; fill: Graphics; edge: Graphics }> = [];

  constructor(private p: Projector, keyframes: ScenarioKeyframe[], data: Diorama | null) {
    this.root.eventMode = "none";
    const frames = [...keyframes].sort((x, y) => x.t_s - y.t_s);
    if (data?.elev && frames.length) this.build(decode(data.elev), frames, data);
    else this.buildFallback(frames);
  }

  // ---------- elevation-based ----------

  private raster(draw: (ctx: CanvasRenderingContext2D, toPx: (lon: number, lat: number) => [number, number]) => void): Uint8Array {
    const g = this.grid!;
    const c = document.createElement("canvas");
    c.width = g.w;
    c.height = g.h;
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    const { a0, b0 } = this.p.bounds;
    const toPx = (lon: number, lat: number): [number, number] => {
      const [a, b] = this.p.toAB(lon, lat);
      return [(a - a0) / g.cell, (b - b0) / g.cell];
    };
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "#fff";
    draw(ctx, toPx);
    const px = ctx.getImageData(0, 0, g.w, g.h).data;
    const out = new Uint8Array(g.w * g.h);
    for (let i = 0; i < out.length; i++) out[i] = px[i * 4 + 3] > 96 ? 1 : 0;
    return out;
  }

  private build(grid: Grid, frames: ScenarioKeyframe[], data: Diorama) {
    this.grid = grid;
    const n = grid.w * grid.h;
    const ring = (ctx: CanvasRenderingContext2D, pts: [number, number][], toPx: (lon: number, lat: number) => [number, number]) => {
      pts.forEach(([lon, lat], i) => {
        const [x, y] = toPx(lon, lat);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
    };
    this.seed = this.raster((ctx, toPx) => {
      ctx.beginPath();
      for (const w of data.water) {
        if (!w.ring) continue;
        ring(ctx, w.ring, toPx);
        for (const hole of w.holes) ring(ctx, hole, toPx);
      }
      ctx.fill("evenodd");
    });
    const { E } = grid;
    let prev = -Infinity;
    // the river's own surface: the typical height of the cells the Charles covers
    const riverH: number[] = [];
    for (let i = 0; i < n; i++) if (this.seed[i]) riverH.push(E[i]);
    riverH.sort((x, y) => x - y);
    this.level0 = riverH.length ? riverH[Math.floor(riverH.length * 0.5)] + 0.15 : 0.5;
    prev = this.level0;
    for (const f of frames) {
      const env = this.raster((ctx, toPx) => {
        ctx.beginPath();
        for (const [outer] of polysOf(f.geometry)) ring(ctx, outer, toPx);
        ctx.fill();
        ctx.lineWidth = (2 * BUFFER_M) / grid.cell;
        ctx.lineJoin = "round";
        ctx.stroke();
      });
      const hs: number[] = [];
      for (let i = 0; i < n; i++) if (env[i] && !this.seed[i]) hs.push(E[i]);
      hs.sort((x, y) => x - y);
      const L = hs.length ? hs[Math.min(hs.length - 1, Math.floor(hs.length * QUANTILE))] : prev + 0.3;
      prev = Math.max(prev + 0.05, L);
      this.env.push(env);
      this.times.push(f.t_s);
      this.levels.push(prev);
    }
    this.wet = new Uint8Array(n);
    this.queue = new Int32Array(n);
    this.canvas = document.createElement("canvas");
    this.canvas.width = grid.w;
    this.canvas.height = grid.h;
    this.maskCanvas = document.createElement("canvas");
    this.maskCanvas.width = grid.w;
    this.maskCanvas.height = grid.h;
    const m = new Matrix(...groundMatrix(this.p, 1 / grid.cell));
    this.sprite = new Sprite(tex(this.canvas));
    this.sprite.setFromMatrix(m);
    this.maskSprite = new Sprite(tex(this.maskCanvas));
    this.maskSprite.setFromMatrix(m);
    const { a0, a1, b0, b1 } = this.p.bounds;
    const corners = [this.p.iso(a0, b0), this.p.iso(a1, b0), this.p.iso(a1, b1), this.p.iso(a0, b1)];
    const x0 = Math.min(...corners.map((c) => c[0]));
    const y0 = Math.min(...corners.map((c) => c[1]));
    this.ripples = new TilingSprite({ texture: rippleTexture(), width: Math.max(...corners.map((c) => c[0])) - x0, height: Math.max(...corners.map((c) => c[1])) - y0 });
    this.ripples.position.set(x0, y0);
    this.ripples.tileScale.set(0.35, 0.35);
    this.ripples.alpha = 0.3;
    this.ripples.mask = this.maskSprite;
    this.root.addChild(this.sprite, this.ripples, this.maskSprite);
  }

  /** Water surface (m) and the stage area it may spread in, at time t. */
  private surface(t: number): { level: number; env: Uint8Array | null } {
    const T = this.times;
    if (t < T[0] - LEAD_S) return { level: -Infinity, env: null };
    if (t < T[0]) return { level: this.level0 + (this.levels[0] - this.level0) * ((t - (T[0] - LEAD_S)) / LEAD_S), env: this.env[0] };
    for (let k = 0; k < T.length - 1; k++) {
      if (t < T[k + 1]) {
        const f = (t - T[k]) / (T[k + 1] - T[k]);
        return { level: this.levels[k] + (this.levels[k + 1] - this.levels[k]) * f, env: this.env[k + 1] };
      }
    }
    return { level: this.levels[T.length - 1], env: this.env[T.length - 1] };
  }

  private recompute(level: number, env: Uint8Array) {
    const { E, w, h } = this.grid!;
    const wet = this.wet;
    const seed = this.seed;
    wet.fill(0);
    let head = 0;
    let tail = 0;
    for (let i = 0; i < w * h; i++) {
      if (seed[i]) {
        wet[i] = 2; // river
        this.queue[tail++] = i;
      }
    }
    while (head < tail) {
      const i = this.queue[head++];
      const x = i % w;
      const y = (i / w) | 0;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) {
        if (j < 0 || wet[j] || !env[j] || E[j] >= level) continue;
        wet[j] = 1;
        this.queue[tail++] = j;
      }
    }
    const ctx = this.canvas.getContext("2d")!;
    const img = ctx.createImageData(w, h);
    const mctx = this.maskCanvas.getContext("2d")!;
    const mimg = mctx.createImageData(w, h);
    const d = img.data;
    const md = mimg.data;
    for (let i = 0; i < w * h; i++) {
      if (wet[i] !== 1) continue;
      const depth = Math.max(0, Math.min(1, (level - E[i]) / 1.6));
      const x = i % w;
      const y = (i / w) | 0;
      const edge = (x > 0 && !wet[i - 1]) || (x < w - 1 && !wet[i + 1]) || (y > 0 && !wet[i - w]) || (y < h - 1 && !wet[i + w]);
      const o = i * 4;
      if (edge) {
        // foam where the water meets dry ground
        d[o] = 234; d[o + 1] = 252; d[o + 2] = 255; d[o + 3] = 240;
      } else {
        // floodwater is a light cyan, apart from the dark river it spills out of (reads on a projector): shallow → deep
        d[o] = Math.round(127 - 66 * depth);
        d[o + 1] = Math.round(220 - 68 * depth);
        d[o + 2] = Math.round(239 - 52 * depth);
        d[o + 3] = Math.round(205 + 40 * depth);
      }
      md[o] = md[o + 1] = md[o + 2] = md[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    mctx.putImageData(mimg, 0, 0);
    this.sprite.texture.source.update();
    this.maskSprite.texture.source.update();
  }

  // ---------- fallback: keyframe polygons ----------

  private buildFallback(frames: ScenarioKeyframe[]) {
    for (let i = frames.length - 1; i >= 0; i--) {
      const fill = new Graphics();
      const edge = new Graphics();
      for (const [outer, ...holes] of polysOf(frames[i].geometry)) {
        const pts = outer.flatMap(([lon, lat]) => this.p.lonlat(lon, lat));
        fill.poly(pts).fill({ color: 0x4c7c9b, alpha: 1 });
        for (const hole of holes) fill.poly(hole.flatMap(([lon, lat]) => this.p.lonlat(lon, lat))).cut();
        edge.poly(pts).stroke({ width: 0.9, color: 0xeaf6ff, alpha: 0.85 });
      }
      this.fallback.push({ t: frames[i].t_s, fill, edge });
      this.root.addChild(fill, edge);
    }
  }

  update(t: number, now: number, _liveGeometry: FloodGeometry | null, tintColor: number) {
    this.root.tint = tintColor;
    if (!this.grid) {
      for (const l of this.fallback) {
        const f = Math.max(0, Math.min(1, (t - l.t) / 600));
        l.fill.visible = l.edge.visible = f > 0;
        l.fill.alpha = 0.82 * (0.35 + 0.65 * f);
      }
      return;
    }
    const { level, env } = this.surface(t);
    const on = env != null && level > -Infinity;
    this.on = on;
    this.sprite.visible = this.ripples.visible = on;
    if (!on) return;
    const key = `${Math.round(level / STEP_M)}|${this.env.indexOf(env)}`;
    if (key !== this.key) {
      this.key = key;
      this.recompute(level, env);
    }
    this.ripples.tilePosition.set((now * 6) % 1e4, (now * 2.2) % 1e4);
  }

  /** Whether stage point (a, b) is under the flood right now (the river itself is not). */
  wetAt(a: number, b: number): boolean {
    if (!this.grid || !this.on) return false;
    const { a0, b0 } = this.p.bounds;
    const x = Math.floor((a - a0) / this.grid.cell);
    const y = Math.floor((b - b0) / this.grid.cell);
    if (x < 0 || y < 0 || x >= this.grid.w || y >= this.grid.h) return false;
    return this.wet[y * this.grid.w + x] === 1;
  }

  /** Surface height now (m above the datum), for labels and debugging. */
  levelAt(t: number): number | null {
    if (!this.grid) return null;
    const s = this.surface(t);
    return Number.isFinite(s.level) ? s.level : null;
  }
}

/**
 * Flood water on the stage, drawn from the scenario's flood keyframes (the same polygons the engine
 * closes roads with). Each stage of the flood fades in over ten minutes after its keyframe instead of
 * popping, so the water reads as spreading; ground that has been under water longer is drawn deeper
 * and darker; slow ripples drift across the surface, and a foam line marks the advancing edge.
 * Purely visual: the engine's closures still switch at the keyframe times.
 */

import { CanvasSource, Container, Graphics, Texture, TilingSprite } from "pixi.js";
import type { Projector } from "./project";
import type { FloodGeometry, ScenarioKeyframe } from "../types";

const RAMP_S = 600; // seconds over which a new flood stage spreads in
const DEPTH = [0x5d8aa6, 0x4c7c9b, 0x3f6e8e, 0x335f80, 0x2a5372]; // shallow → deep

type Layer = { t: number; polys: number[][][]; fill: Graphics; edge: Graphics };

function polysOf(geometry: FloodGeometry, p: Projector): number[][][] {
  const list = geometry.type === "Polygon" ? [geometry.coordinates as [number, number][][]] : (geometry.coordinates as [number, number][][][]);
  return list.map((poly) => poly.map((ring) => ring.flatMap(([lon, lat]) => p.lonlat(lon, lat))));
}

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
  private layers: Layer[] = [];
  private ripples: TilingSprite;
  private mask = new Graphics();
  private maskKey = -1;
  private live: { key: unknown; layer: Layer | null } = { key: null, layer: null };

  constructor(private p: Projector, keyframes: ScenarioKeyframe[]) {
    this.root.eventMode = "none";
    const frames = [...keyframes].sort((x, y) => x.t_s - y.t_s);
    // newest (largest, shallowest) at the bottom, older (deeper) stacked above it
    for (let i = frames.length - 1; i >= 0; i--) {
      const polys = polysOf(frames[i].geometry, p);
      const depth = DEPTH[Math.min(DEPTH.length - 1, frames.length - 1 - i)];
      const fill = new Graphics();
      const edge = new Graphics();
      for (const [outer, ...holes] of polys) {
        fill.poly(outer).fill({ color: depth, alpha: 1 });
        for (const hole of holes) fill.poly(hole).cut();
        // wet band just outside the water, then a foam line on the edge
        edge.poly(outer).stroke({ width: 3.2, color: 0x1d2a30, alpha: 0.22 });
        edge.poly(outer).stroke({ width: 0.9, color: 0xeaf6ff, alpha: 0.85 });
      }
      this.layers.push({ t: frames[i].t_s, polys, fill, edge });
      this.root.addChild(fill);
    }
    const { a0, a1, b0, b1 } = p.bounds;
    const corners = [p.iso(a0, b0), p.iso(a1, b0), p.iso(a1, b1), p.iso(a0, b1)];
    const x0 = Math.min(...corners.map((c) => c[0]));
    const x1 = Math.max(...corners.map((c) => c[0]));
    const y0 = Math.min(...corners.map((c) => c[1]));
    const y1 = Math.max(...corners.map((c) => c[1]));
    this.ripples = new TilingSprite({ texture: rippleTexture(), width: x1 - x0, height: y1 - y0 });
    this.ripples.position.set(x0, y0);
    this.ripples.tileScale.set(0.35, 0.35);
    this.ripples.alpha = 0.32;
    this.ripples.mask = this.mask;
    this.root.addChild(this.ripples, this.mask);
    for (const layer of this.layers) this.root.addChild(layer.edge);
  }

  update(t: number, now: number, liveGeometry: FloodGeometry | null, tintColor: number) {
    let active = 0;
    for (const layer of this.layers) {
      const f = Math.max(0, Math.min(1, (t - layer.t) / RAMP_S));
      const on = f > 0;
      if (on) active++;
      layer.fill.visible = on;
      layer.fill.alpha = 0.82 * (0.35 + 0.65 * f);
      layer.edge.visible = on;
      // the foam line is brightest while that stage is still spreading
      layer.edge.alpha = on ? (f < 1 ? 1 : 0.55) * (0.75 + 0.25 * Math.sin(now * 1.7 + layer.t)) : 0;
    }
    // a live flood polygon the keyframes do not have (reports, edits): one more layer
    if (liveGeometry && !this.layers.some((l) => l.t <= t && l.polys.length) && this.live.key !== liveGeometry) {
      this.live.layer?.fill.destroy();
      this.live.layer?.edge.destroy();
      const polys = polysOf(liveGeometry, this.p);
      const fill = new Graphics();
      const edge = new Graphics();
      for (const [outer, ...holes] of polys) {
        fill.poly(outer).fill({ color: DEPTH[1], alpha: 0.8 });
        for (const hole of holes) fill.poly(hole).cut();
        edge.poly(outer).stroke({ width: 0.9, color: 0xeaf6ff, alpha: 0.85 });
      }
      this.root.addChildAt(fill, 0);
      this.root.addChild(edge);
      this.live = { key: liveGeometry, layer: { t: -Infinity, polys, fill, edge } };
    }
    const key = active + (this.live.layer ? 100 : 0);
    if (key !== this.maskKey) {
      this.maskKey = key;
      this.mask.clear();
      const shapes = [...this.layers.filter((l) => l.t <= t), ...(this.live.layer ? [this.live.layer] : [])];
      for (const layer of shapes) for (const [outer] of layer.polys) this.mask.poly(outer).fill(0xffffff);
      this.ripples.visible = shapes.length > 0;
    }
    this.ripples.tilePosition.set((now * 6) % 1e4, (now * 2.2) % 1e4);
    this.root.tint = tintColor;
  }
}

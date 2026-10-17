/**
 * Sharp ground when zoomed in. The whole stage is baked once at 2 px per metre (fine from afar);
 * zoomed in, the 128 m tiles in view are painted again at 8 px per metre (and their cast shadows
 * at 4 px per metre) with the same painter, on demand, at most one per frame, and kept in a small
 * least-recently-used cache. The coarse shadow layer is swapped for the sharp one only when every
 * tile in view is ready, so shadows never double up or blink.
 */

import { CanvasSource, Container, Matrix, Sprite, Texture } from "pixi.js";
import { bakeTile, groundMatrix, TILE_M, TILE_P, TILE_SP, type GroundInputs, type ShadowShape } from "./ground";
import type { Projector } from "./project";

export const HI_S = 2.2; // camera scale (screen px per plane unit) from which tiles are used
const MAX_TILES = 28;

type Tile = { ground: Sprite; shadow: Sprite; used: number };

const tex = (canvas: HTMLCanvasElement) => new Texture({ source: new CanvasSource({ resource: canvas, autoGenerateMipmaps: true, scaleMode: "linear" }) });

export class GroundTiles {
  readonly ground = new Container();
  readonly shadow = new Container();
  private tiles = new Map<string, Tile>();
  private frame = 0;

  constructor(private inputs: GroundInputs, private shadows: ShadowShape[]) {
    this.ground.eventMode = "none";
    this.shadow.eventMode = "none";
  }

  /**
   * Show the tiles covering the plane-space view (bake one more if needed). Returns true when the
   * sharp shadows cover the whole view (the caller then hides the coarse shadow layer).
   */
  update(view: { x0: number; y0: number; x1: number; y1: number }, camS: number, tint: number): boolean {
    this.frame++;
    for (const t of this.tiles.values()) {
      t.ground.visible = false;
      t.shadow.visible = false;
    }
    if (camS < HI_S) return false;
    const p: Projector = this.inputs.p;
    const { a0, a1, b0, b1 } = p.bounds;
    // ground (a, b) under the view's corners: a = y + x/2, b = y − x/2
    const corners = [[view.x0, view.y0], [view.x1, view.y0], [view.x0, view.y1], [view.x1, view.y1]].map(([x, y]) => [y + x / 2, y - x / 2]);
    const ga0 = Math.max(a0, Math.min(...corners.map((c) => c[0])) - 8);
    const ga1 = Math.min(a1, Math.max(...corners.map((c) => c[0])) + 8);
    const gb0 = Math.max(b0, Math.min(...corners.map((c) => c[1])) - 8);
    const gb1 = Math.min(b1, Math.max(...corners.map((c) => c[1])) + 8);
    let complete = true;
    let baked = false;
    for (let i = Math.floor((ga0 - a0) / TILE_M); a0 + i * TILE_M < ga1; i++) {
      for (let j = Math.floor((gb0 - b0) / TILE_M); b0 + j * TILE_M < gb1; j++) {
        const ta = a0 + i * TILE_M;
        const tb = b0 + j * TILE_M;
        // skip tiles whose iso diamond misses the view (the (a, b) box of a screen rectangle over-covers)
        const pts = [[ta, tb], [ta + TILE_M, tb], [ta, tb + TILE_M], [ta + TILE_M, tb + TILE_M]].map(([a, b]) => p.iso(a, b));
        if (Math.max(...pts.map((q) => q[0])) < view.x0 || Math.min(...pts.map((q) => q[0])) > view.x1) continue;
        if (Math.max(...pts.map((q) => q[1])) < view.y0 || Math.min(...pts.map((q) => q[1])) > view.y1) continue;
        const key = `${i},${j}`;
        let t = this.tiles.get(key);
        if (!t) {
          if (baked) {
            complete = false;
            continue;
          }
          baked = true;
          const out = bakeTile(this.inputs, this.shadows, ta, tb);
          const ground = new Sprite(tex(out.ground));
          ground.setFromMatrix(new Matrix(...groundMatrix(p, TILE_P, [ta, tb])));
          const shadow = new Sprite(tex(out.shadow));
          shadow.setFromMatrix(new Matrix(...groundMatrix(p, TILE_SP, [ta, tb])));
          this.ground.addChild(ground);
          this.shadow.addChild(shadow);
          t = { ground, shadow, used: this.frame };
          this.tiles.set(key, t);
          this.evict();
        }
        t.used = this.frame;
        t.ground.visible = true;
        t.shadow.visible = true;
        if (t.ground.tint !== tint) t.ground.tint = tint;
      }
    }
    if (!complete) for (const t of this.tiles.values()) t.shadow.visible = false;
    return complete;
  }

  private evict() {
    if (this.tiles.size <= MAX_TILES) return;
    const oldest = [...this.tiles.entries()].sort((x, y) => x[1].used - y[1].used).slice(0, this.tiles.size - MAX_TILES);
    for (const [key, t] of oldest) {
      t.ground.destroy({ texture: true, textureSource: true });
      t.shadow.destroy({ texture: true, textureSource: true });
      this.tiles.delete(key);
    }
  }
}

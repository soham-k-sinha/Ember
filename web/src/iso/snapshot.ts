/**
 * District-zoom performance (D96): from afar the static city (1,100 building shapes, ~2,800 trees) costs most of
 * the frame to walk, yet does not change. Below SNAP_S the static objects are drawn once into one texture at
 * screen resolution and shown as a single sprite; only moving things (people, cars, the fleet, signals) are drawn
 * live on top. The image is baked in neutral light and tinted live, so the evening never forces a rebuild; it is
 * rebuilt only when the camera settles at a new zoom (≈0.1 s, once), and while the camera moves it just scales. Close up, everything is drawn live with exact depth sorting.
 */

import { Container, Sprite, type Renderer, type Texture } from "pixi.js";

export const SNAP_S = 0.95; // below this, figures are at their minimum on-screen size anyway

export class StaticSnapshot {
  readonly sprite = new Sprite();
  private key = "";
  private tex: Texture | null = null;

  constructor(private renderer: Renderer) {
    this.sprite.eventMode = "none";
    this.sprite.visible = false;
  }

  get active() {
    return this.sprite.visible;
  }

  /**
   * Show the snapshot at camera scale s (rebuild it if stale and the camera is still). `statics` are the objects
   * to bake; they are hidden afterwards. Returns whether the snapshot is in use this frame.
   */
  update(s: number, still: boolean, objects: Container, statics: Container[], dynamics: Container[], dpr: number, bake: { before: () => void; after: () => void; tint: number }): boolean {
    if (s >= SNAP_S) {
      this.sprite.visible = false;
      return false;
    }
    const zoomKey = Math.round(Math.log2(s) * 5); // ~15 % zoom steps
    const key = `${zoomKey}`;
    if (key !== this.key && (still || !this.tex)) {
      this.key = key;
      // bake: statics shown, moving things hidden
      const dynVis = dynamics.map((d) => d.visible);
      for (const d of dynamics) d.visible = false;
      for (const st of statics) st.visible = true;
      bake.before();
      const b = objects.getLocalBounds();
      const res = Math.min(s * dpr * 1.15, 4096 / Math.max(b.width, b.height));
      const tex = this.renderer.generateTexture({ target: objects, resolution: res, antialias: true });
      bake.after();
      dynamics.forEach((d, i) => (d.visible = dynVis[i]));
      this.tex?.destroy(true);
      this.tex = tex;
      this.sprite.texture = tex;
      this.sprite.position.set(b.x, b.y);
    }
    if (!this.tex) return false;
    for (const st of statics) st.visible = false;
    this.sprite.visible = true;
    this.sprite.tint = bake.tint;
    return true;
  }
}

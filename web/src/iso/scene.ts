/**
 * The static stage, built once from the real district (D52): a model slab with earth sides, the baked
 * ground (textures, kerbs, shore, AO), the cast-shadow and lamp-light layers, and every building,
 * tree and street lamp in one back-to-front container. Returns handles the view tints each frame
 * for the evening light. The resources and the flood are drawn on top by IsoView.
 */

import { Container, Graphics, Matrix, Sprite, Texture, CanvasSource } from "pixi.js";
import { buildAtlas, RES, type Atlas, type TreeKind } from "./atlas";
import { drawBuilding } from "./build3d";
import type { Diorama, DioBuilding } from "./data";
import { bakeGround, groundMatrix, P, SHADOW_P, type TreeSpot } from "./ground";
import { hashN } from "./palette";
import type { Projector } from "./project";

const SLAB_M = 4.5;

export type Bounds = { x0: number; y0: number; x1: number; y1: number };
export type BuildingRec = { b: DioBuilding; id: number; holder: Container; lite: Container; full: Container | null; bounds: Bounds };
export type Cullable = { node: Container; bounds: Bounds };

export type StaticScene = {
  buildings: BuildingRec[];
  cullables: Cullable[];
  light: { tint: number; lights: number };
  /** Build (once) and show the detailed version of a building: windows, doors, rooftop units. */
  ensureFull: (rec: BuildingRec) => Container;
  atlas: Atlas;
  slab: Graphics;
  ground: Sprite;
  shadow: Sprite;
  pools: Sprite;
  objects: Container; // buildings, trees, lamps (+ vehicles and people added by the view), back to front
  slabMask: Graphics;
  lit: Container[]; // tinted by the world light
  glows: Graphics[]; // building windows/doors (additive), alpha = lights
  lampGlows: Sprite[];
  labels: Array<{ text: string; at: [number, number, number] }>;
};

const tex = (canvas: HTMLCanvasElement) => new Texture({ source: new CanvasSource({ resource: canvas, autoGenerateMipmaps: true, scaleMode: "linear" }) });

export function buildStatic(data: Diorama, p: Projector): StaticScene {
  const atlas = buildAtlas();
  const { a0, a1, b0, b1 } = p.bounds;
  const inside = (a: number, b: number) => a >= a0 && a <= a1 && b >= b0 && b <= b1;

  // buildings first: their cast shadows are baked into the ground
  const objects = new Container();
  objects.sortableChildren = true;
  const lit: Container[] = [];
  const glows: Graphics[] = [];
  const shadows: Array<Array<[number, number]>> = [];
  const footprints: Array<Array<[number, number]>> = [];
  const labels: StaticScene["labels"] = [];
  const seen = new Set<string>();
  const buildings: BuildingRec[] = [];
  const cullables: Cullable[] = [];
  const light = { tint: 0xffffff, lights: 0 };
  data.buildings.forEach((b, i) => {
    const built = drawBuilding(p, b, i, false);
    const holder = new Container();
    holder.zIndex = built.depth;
    holder.addChild(built.node);
    objects.addChild(holder);
    lit.push(built.node.children[0] as Container);
    let x0 = Infinity;
    let x1 = -Infinity;
    let y0 = Infinity;
    let y1 = -Infinity;
    for (const [a, bb] of built.foot) {
      const [x, y] = p.iso(a, bb);
      x0 = Math.min(x0, x);
      x1 = Math.max(x1, x);
      y0 = Math.min(y0, y - built.topM * 1.22 - 2);
      y1 = Math.max(y1, y + 1);
    }
    buildings.push({ b, id: i, holder, lite: built.node, full: null, bounds: { x0, y0, x1, y1 } });
    shadows.push(built.shadow);
    footprints.push(built.foot);
    if (built.label && built.labelAt && !seen.has(built.label)) {
      seen.add(built.label);
      labels.push({ text: built.label, at: built.labelAt });
    }
  });

  // trees from the city's LiDAR crowns / street-tree inventory
  const trees: Array<TreeSpot & { kind: TreeKind }> = [];
  data.trees.forEach((t, i) => {
    if (hashN(i, 1) > 0.7) return;
    const [a, b] = p.toAB(t[0], t[1]);
    if (!inside(a, b)) return;
    const k = hashN(i, 2);
    const kind: TreeKind = t[2] < 6 ? "shrub" : k < 0.34 ? "oak" : k < 0.6 ? "oakDark" : k < 0.86 ? "elm" : "pine";
    trees.push({ a, b, r: Math.max(1.6, Math.min(6, t[3])), h: t[2], kind });
  });
  for (const t of trees) {
    const frame = atlas.tree[t.kind];
    const s = new Sprite(frame.tex);
    s.anchor.set(frame.ax, frame.ay);
    const crown = t.kind === "shrub" ? 0.9 : t.kind === "pine" ? 2.0 : 2.4;
    const scale = Math.max(0.55, Math.min(1.7, t.r / crown));
    s.scale.set(scale / RES);
    const [x, y] = p.iso(t.a, t.b);
    s.position.set(x, y);
    s.zIndex = t.a + t.b + 0.3;
    objects.addChild(s);
    const h = frame.h * (scale / RES);
    const w = frame.w * (scale / RES);
    cullables.push({ node: s, bounds: { x0: x - w / 2, y0: y - h, x1: x + w / 2, y1: y + 2 } });
  }

  // the ground image, cast shadows and lamp pools
  const bake = bakeGround(data, p, shadows, trees, footprints);
  const ground = new Sprite(tex(bake.ground));
  ground.setFromMatrix(new Matrix(...groundMatrix(p, P)));
  const shadow = new Sprite(tex(bake.shadow));
  shadow.setFromMatrix(new Matrix(...groundMatrix(p, SHADOW_P)));
  shadow.alpha = 0.45;
  const pools = new Sprite(tex(bake.pools));
  pools.setFromMatrix(new Matrix(...groundMatrix(p, SHADOW_P)));
  pools.blendMode = "add";
  pools.alpha = 0;

  // street lamps (+ their glows, faded in at dusk)
  const lampGlows: Sprite[] = [];
  for (const l of bake.lamps) {
    const post = new Sprite(atlas.lamp.tex);
    post.anchor.set(atlas.lamp.ax, atlas.lamp.ay);
    post.scale.set(1 / RES);
    const [x, y] = p.iso(l.a, l.b);
    post.position.set(x, y);
    const c = new Container();
    c.addChild(post);
    for (const [r, alpha, tint] of [[3.6, 0.45, 0xffb868], [0.9, 1, 0xfff0d0]] as const) {
      const g = new Sprite(atlas.glow.tex);
      g.anchor.set(0.5);
      g.scale.set((r * 2) / atlas.glow.w);
      g.position.set(x, y - 4.05 * 1.22);
      g.tint = tint;
      g.blendMode = "add";
      g.alpha = 0;
      (g as Sprite & { base?: number }).base = alpha;
      c.addChild(g);
      lampGlows.push(g);
    }
    c.zIndex = l.a + l.b + 0.2;
    objects.addChild(c);
    cullables.push({ node: c, bounds: { x0: x - 4, y0: y - 8, x1: x + 4, y1: y + 1 } });
    lit.push(post as unknown as Container);
  }

  // slab: the model sits on a block of earth (two visible sides), like a table-top diorama
  const corners = [p.iso(a0, b0), p.iso(a1, b0), p.iso(a1, b1), p.iso(a0, b1)];
  const slab = new Graphics();
  const dz = SLAB_M * 1.22 * 4;
  const down = (pt: [number, number]): [number, number] => [pt[0], pt[1] + dz];
  const [ne, se, sw] = [corners[1], corners[2], corners[3]];
  slab.poly([...ne, ...se, ...down(se), ...down(ne)]).fill(0x5d4632);
  slab.poly([...se, ...sw, ...down(sw), ...down(se)]).fill(0x735840);
  slab.poly([...se, ...down(se)]).stroke({ width: 1, color: 0x3b2c1f, alpha: 0.6 });
  // strata lines
  for (const f of [0.35, 0.7]) {
    slab.moveTo(ne[0], ne[1] + dz * f).lineTo(se[0], se[1] + dz * f).lineTo(sw[0], sw[1] + dz * f).stroke({ width: 1.2, color: 0x000000, alpha: 0.18 });
  }
  slab.poly(corners.flat()).stroke({ width: 1.4, color: 0xe8dcc4, alpha: 0.5 });
  const slabMask = new Graphics().poly(corners.flat()).fill(0xffffff);

  const ensureFull = (rec: BuildingRec) => {
    if (rec.full) return rec.full;
    const built = drawBuilding(p, rec.b, rec.id, true);
    const body = built.node.children[0] as Container;
    body.tint = light.tint;
    lit.push(body);
    const glow = (built.node as Container & { glow?: Graphics }).glow;
    if (glow) {
      glow.alpha = light.lights;
      glow.visible = light.lights > 0.01;
      glows.push(glow);
    }
    rec.holder.addChild(built.node);
    rec.full = built.node;
    return built.node;
  };

  return { buildings, cullables, light, ensureFull, atlas, slab, ground, shadow, pools, objects, slabMask, lit: [ground as unknown as Container, slab as unknown as Container, ...lit, ...objects.children.filter((c) => c instanceof Sprite) as unknown as Container[]], glows, lampGlows, labels };
}

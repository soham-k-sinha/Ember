import scenario from "../../contracts/fixtures/scenario.fixture.json" with { type: "json" };
import state from "../../contracts/fixtures/state.fixture.json" with { type: "json" };
import town from "../../contracts/fixtures/town.fixture.json" with { type: "json" };
import { lineIntersectsGeometry } from "../src/geo.ts";
import type { MultiPolygon, Polygon } from "geojson";

type Edge = { id: number; geom: [number, number][] };
const edges = (town as { edges: Edge[] }).edges;
const keyframe = (scenario as { hazard: { keyframes: Array<{ t_s: number; geometry: Polygon | MultiPolygon }> } }).hazard.keyframes
  .find((frame) => frame.t_s === 3600);
if (!keyframe) throw new Error("missing 3600 keyframe");

const geometric = new Set(
  edges.filter((edge) => lineIntersectsGeometry(edge.geom, keyframe.geometry)).map((edge) => edge.id),
);
const published = new Set(
  (state as { closures: Array<{ edge_id: number }> }).closures.map((closure) => closure.edge_id),
);
let hit = 0;
for (const id of published) if (geometric.has(id)) hit += 1;
const precision = geometric.size === 0 ? 0 : hit / geometric.size;
const recall = published.size === 0 ? 0 : hit / published.size;
console.log(JSON.stringify({
  published: published.size,
  geometric: geometric.size,
  overlap: hit,
  precision: Number(precision.toFixed(3)),
  recall: Number(recall.toFixed(3)),
}));
if (recall < 0.9) {
  console.error("geometry missed too many published closures");
  process.exit(1);
}

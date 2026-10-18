import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import type { Diorama } from "../src/iso/data.ts";

// the stage modules import each other without extensions (Vite style); resolve those to .ts here
register(
  "data:text/javascript,export async function resolve(s,c,n){try{return await n(s,c)}catch(e){if(/^\\.\\.?\\//.test(s)&&!/\\.[a-z]+$/.test(s))return n(s+'.ts',c);throw e}}",
  import.meta.url,
);
const { AmbientTraffic, AMBIENT_CARS } = await import("../src/iso/ambient.ts");
const { projector } = await import("../src/iso/project.ts");

const data = JSON.parse(readFileSync(new URL("../public/diorama/stage.json", import.meta.url), "utf8")) as Diorama;
const p = projector(data.bbox);
// every junction on one fixed axis, red for the second: a stub of the real signal cycle (no Pixi in node)
const junctions = (data.signals ?? []).map(([lon, lat]) => {
  const [a, b] = p.toAB(lon, lat);
  return { a, b, axes: [{ ua: 1, ub: 0 }, { ua: 0, ub: 1 }] as [{ ua: number; ub: number }, { ua: number; ub: number }], offset: 0 };
});
let red = false;
const signals = { junctions, stateFor: () => (red ? 2 : 0) } as never;
const traffic = new AmbientTraffic(data, p, signals, () => false);
const view = { x0: 1e6, y0: 1e6, x1: 1e6 + 1, y1: 1e6 + 1 }; // nothing on screen: free to spawn anywhere

traffic.step(1 / 60, 0, 0, view);
assert.equal(traffic.cars.length, AMBIENT_CARS, "the everyday traffic fills the stage at the start");
const lanes = () => {
  const by = new Map<string, number[]>();
  for (const c of traffic.cars) by.set(`${c.L}:${c.d}`, [...(by.get(`${c.L}:${c.d}`) ?? []), c.s]);
  return by;
};
for (let i = 0; i < 60 * 30; i++) traffic.step(1 / 60, i / 60, 0, view);
const moving = traffic.cars.filter((c) => c.v > 2).length;
assert(moving > AMBIENT_CARS * 0.5, `most cars are moving on green (${moving})`);
for (const [, ss] of lanes()) {
  ss.sort((x, y) => x - y);
  for (let i = 1; i < ss.length; i++) assert(ss[i] - ss[i - 1] > 3, "cars in a lane never overlap");
}
red = true;
for (let i = 0; i < 60 * 40; i++) traffic.step(1 / 60, 30 + i / 60, 0, view);
const queued = traffic.cars.filter((c) => c.v < 0.3).length;
assert(queued > 40, `a long red builds queues at the signalised junctions (${queued})`);
red = false;
for (let i = 0; i < 60 * 30; i++) traffic.step(1 / 60, 70 + i / 60, 0, view);
assert(traffic.cars.filter((c) => c.v < 0.3).length < queued, "queues clear on green");
assert(AmbientTraffic.target(9000) < AMBIENT_CARS * 0.4, "the district empties out as the evacuation runs");
const wet = new AmbientTraffic(data, p, signals, () => true);
wet.step(1 / 60, 0, 0, view);
assert.equal(wet.cars.length, 0, "no car is placed in floodwater");
console.log(`Traffic checks passed: ${AMBIENT_CARS} cars, no overlaps, ${queued} queued on red, queues clear, none in water.`);

import assert from "node:assert/strict";
import { CrowdBudget, inCrowdView, populationAtZoom } from "../src/iso/density.ts";

function run(budget: CrowdBudget, elapsedMs: number, frameMs: number, requested = 1400) {
  for (let t = 0; t < elapsedMs; t += frameMs) budget.sample(frameMs, requested);
}

assert.equal(populationAtZoom(0.4), 175, "district overview keeps its previous population");
assert.equal(populationAtZoom(2), 1400, "close-ups can request twice the old maximum");
assert.equal(populationAtZoom(9), 1400, "zoom cannot create an unbounded crowd");

const healthy = new CrowdBudget();
assert.equal(healthy.sample(1000 / 60, 1400), 700, "higher density starts at the old budget");
run(healthy, 9000, 1000 / 60);
assert.equal(healthy.limit, 1400, "sustained spare frame time unlocks the denser crowd");
run(healthy, 2500, 40);
assert(healthy.limit < 700, "sustained slow frames shed decorative people");
run(healthy, 20000, 40);
assert.equal(healthy.limit, 100, "fallback remains bounded under continuous overload");
run(healthy, 20000, 1000 / 60);
assert.equal(healthy.limit, 1400, "density recovers after pressure clears");
const beforePause = healthy.limit;
healthy.sample(60000, 1400);
assert.equal(healthy.limit, beforePause, "returning from a background tab does not punish density");
run(healthy, 20000, 500);
assert.equal(healthy.limit, 100, "repeated severe stalls still trigger overload protection");

const overview = new CrowdBudget();
run(overview, 30000, 1000 / 60, 175);
assert.equal(overview.sample(1000 / 60, 1400), 700, "overview idle time cannot unlock a sudden close-up spike");

const view = { x0: -10, y0: -10, x1: 10, y1: 10 };
assert(inCrowdView(0, 25, view, 20, 1), "a visible head is retained when its feet are below the view");
assert(inCrowdView(15, 0, view, 20, 2), "figures straddling the side edge retain their motion margin");
assert(!inCrowdView(10000, 10000, view, 20, 1), "distant figures are rejected before sprite allocation");
assert(!inCrowdView(0, -20, view, 20, 1), "figures entirely above the view are rejected");
console.log("Crowd checks passed: density growth, overload recovery, background gaps, viewport edges.");

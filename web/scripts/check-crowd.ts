import assert from "node:assert/strict";
import { BASE_STROLLERS, CrowdBudget, inCrowdView, MAX_STROLLERS, populationAtZoom } from "../src/iso/density.ts";

function run(budget: CrowdBudget, elapsedMs: number, frameMs: number, requested = MAX_STROLLERS) {
  for (let t = 0; t < elapsedMs; t += frameMs) budget.sample(frameMs, requested);
}

const district = populationAtZoom(0.4);
assert(district >= 400 && district <= BASE_STROLLERS, "the district overview reads as busy without the close-up crowd");
assert.equal(populationAtZoom(2), MAX_STROLLERS, "close-ups request the full crowd");
assert.equal(populationAtZoom(9), MAX_STROLLERS, "zoom cannot create an unbounded crowd");

const healthy = new CrowdBudget();
assert.equal(healthy.sample(1000 / 60, MAX_STROLLERS), BASE_STROLLERS, "density starts at the base budget");
run(healthy, 40000, 1000 / 60);
assert.equal(healthy.limit, MAX_STROLLERS, "sustained spare frame time unlocks the denser crowd");
run(healthy, 6000, 40);
assert(healthy.limit < BASE_STROLLERS, "sustained slow frames shed decorative people");
run(healthy, 20000, 40);
assert.equal(healthy.limit, 100, "fallback remains bounded under continuous overload");
run(healthy, 60000, 1000 / 60);
assert.equal(healthy.limit, MAX_STROLLERS, "density recovers after pressure clears");
const beforePause = healthy.limit;
healthy.sample(60000, MAX_STROLLERS);
assert.equal(healthy.limit, beforePause, "returning from a background tab does not punish density");
run(healthy, 20000, 500);
assert.equal(healthy.limit, 100, "repeated severe stalls still trigger overload protection");

const overview = new CrowdBudget();
run(overview, 30000, 1000 / 60, populationAtZoom(0.4));
assert.equal(overview.sample(1000 / 60, MAX_STROLLERS), BASE_STROLLERS, "overview idle time cannot unlock a sudden close-up spike");

const view = { x0: -10, y0: -10, x1: 10, y1: 10 };
assert(inCrowdView(0, 25, view, 20, 1), "a visible head is retained when its feet are below the view");
assert(inCrowdView(15, 0, view, 20, 2), "figures straddling the side edge retain their motion margin");
assert(!inCrowdView(10000, 10000, view, 20, 1), "distant figures are rejected before sprite allocation");
assert(!inCrowdView(0, -20, view, 20, 1), "figures entirely above the view are rejected");
console.log("Crowd checks passed: density growth, overload recovery, background gaps, viewport edges.");

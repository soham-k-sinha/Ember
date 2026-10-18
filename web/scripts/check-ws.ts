import { readFileSync } from "node:fs";
import { readEnvelope, scatterFromEnvelopes, seqDecision } from "../src/live.ts";
import { buildOpening, type OpeningScenario } from "../src/opening.ts";
import { detectArrivals, type Doors } from "../src/arrivals.ts";
import type { Comparison, StateSnapshot, Town } from "../src/types.ts";

const root = new URL("../..", import.meta.url);
const events = JSON.parse(readFileSync(new URL("contracts/fixtures/ws-events.fixture.json", root), "utf8")) as unknown[];
if (!Array.isArray(events) || events.length < 7) throw new Error("ws fixture missing");

let expected: number | null = null;
const seen = new Set<string>();
for (const raw of events) {
  const envelope = readEnvelope(raw);
  if (envelope.kind !== "envelope" || !envelope.event) {
    throw new Error(`unreadable event ${JSON.stringify(raw).slice(0, 120)}`);
  }
  const decision = seqDecision(expected, envelope.seq);
  if (decision !== "accept") throw new Error(`expected accept for seq ${envelope.seq}, got ${decision}`);
  expected = envelope.seq + 1;
  seen.add(envelope.event.type);
  const data = (raw as { data?: Record<string, unknown> }).data ?? {};
  if (envelope.event.type === "assignment") {
    for (const key of ["plan_version", "change", "assignment_id", "assignment"]) {
      if (!(key in data)) throw new Error(`assignment event missing ${key}`);
    }
    if (data.assignment !== null && typeof data.assignment !== "object") {
      throw new Error("assignment event should carry the assignment object or null");
    }
  }
  if (envelope.event.type === "scatter_point") {
    for (const key of ["run_id", "batch_id", "candidate", "seed", "metrics"]) {
      if (!(key in data)) throw new Error(`scatter_point missing ${key}`);
    }
    const point = envelope.event.point;
    if (point.candidate === "ember" && !point.chosen) throw new Error("ember candidate should be the chosen plan");
    if (point.candidate !== "ember" && point.chosen) throw new Error("only ember is the chosen candidate");
  }
}
for (const type of ["state", "plan", "assignment", "message", "report", "scatter_point", "metrics"]) {
  if (!seen.has(type)) throw new Error(`missing ${type}`);
}
if (scatterFromEnvelopes(events).length < 2) throw new Error("scatter fixture did not parse");

const skipped = events.filter((event) => (event as { seq: number }).seq !== 2);
let cursor: number | null = null;
let gap = false;
for (const raw of skipped) {
  const envelope = readEnvelope(raw);
  if (envelope.kind !== "envelope") throw new Error("gap fixture unreadable");
  const decision = seqDecision(cursor, envelope.seq);
  if (decision === "gap") {
    gap = true;
    break;
  }
  if (decision === "accept") cursor = envelope.seq + 1;
}
if (!gap) throw new Error("skipped seq was not detected");

// the published comparison the web shows as the baseline (fixtures.ts reads it as is)
const parsed = JSON.parse(readFileSync(new URL("contracts/fixtures/comparison.fixture.json", root), "utf8")) as Comparison;
if (!parsed.nominal?.baseline || !parsed.nominal.ember || !Array.isArray(parsed.metrics)) throw new Error("comparison fixture rejected");
const reached = parsed.metrics.find((metric) => metric.metric === "people_reached_before_deadline");
if (!reached) throw new Error("missing reached metric");
const delta = parsed.nominal.ember.people_reached_before_deadline! - parsed.nominal.baseline.people_reached_before_deadline!;
if (delta !== 37) throw new Error(`B-A for people reached should be 37, got ${delta}`);
if (reached.diff_mean == null) throw new Error("comparison metric missing diff_mean");
if (parsed.plans.ember.versions.length < 2) throw new Error("missing ember versions");

const example = JSON.parse(readFileSync(new URL("contracts/fixtures/scenario.fixture.json", root), "utf8")) as { scenario_id: string };
const allston = JSON.parse(readFileSync(new URL("scenarios/allston_flood_v1/scenario.json", root), "utf8")) as OpeningScenario;
const town = JSON.parse(readFileSync(new URL("contracts/fixtures/town.fixture.json", root), "utf8")) as Town;
const opening = buildOpening(allston, town);
if (opening.scenario_id !== "allston_flood_v1") throw new Error(`opening scenario is ${opening.scenario_id}`);
if (opening.scenario_id === example.scenario_id) throw new Error("opening picture is still the example flood");
const judge = opening.households.find((household) => household.judge);
if (!judge || judge.household_id !== 10296) throw new Error("judge household should be #10296");
if (opening.facilities.length !== 6) throw new Error(`expected 6 facilities, got ${opening.facilities.length}`);
if (!opening.facilities.some((facility) => facility.id === "treehouse-shelter")) {
  throw new Error("Treehouse shelter missing from the opening picture");
}

// arrivals (D112): the WS event, and the same moment seen from a replay or a status
const arrivalEvent = readEnvelope({ type: "arrival", seq: 153, t_s: 60, data: { t_s: 60, household_id: 6746, resource_id: "van-1", resource_name: "Van 1", player: 1, call: false } });
if (arrivalEvent.kind !== "envelope" || arrivalEvent.event?.type !== "arrival") throw new Error("arrival event not read");
if (arrivalEvent.event.arrival.player !== 1 || arrivalEvent.event.arrival.resource_name !== "Van 1") throw new Error("arrival data misread");
const home = { ...judge, household_id: 6746, judge: false, status: "assigned" as const, assignment_id: "a-1" };
const at = (t: number, status: StateSnapshot["households"][number]["status"]): StateSnapshot => ({
  ...opening,
  t_s: t,
  households: [{ ...home, status }],
  resources: [{ id: "van-1", kind: "van", name: "Van 1", lon: home.lon, lat: home.lat, node: home.node, edge_id: null, status: "working", assignment_id: "a-1", eta_s: null, fuel_l: 40 }],
  plan: { version: 2, created_at_t_s: 0, assignments: [{ id: "a-1", plan_version: 2, resource_id: "van-1", task: "rescue", target: { household_id: 6746 }, eta_s: 900, deadline_s: 4500, status: "confirmed", rationale: "" }], unresolved: [], info_requests: [] },
});
const watched = new Map([[6746, { player: 1, onCall: true }]]);
const doors: Doors = new Map([[6746, { t: 900, resource_id: "van-1" }]]);
const seenReached = new Map<number, boolean>();
if (detectArrivals(seenReached, at(1000, "assigned"), watched, 1000, doors).length !== 0) throw new Error("a first sighting must not alert");
seenReached.clear();
if (detectArrivals(seenReached, at(890, "assigned"), watched, 890, doors).length !== 0) throw new Error("alerted before the door");
const byDoor = detectArrivals(seenReached, at(905, "assigned"), watched, 905, doors);
if (byDoor.length !== 1 || byDoor[0].t_s !== 900 || byDoor[0].player !== 1 || !byDoor[0].call) throw new Error("door arrival missed");
if (detectArrivals(seenReached, at(910, "assigned"), watched, 910, doors).length !== 0) throw new Error("alerted twice");
const noReplay = new Map<number, boolean>();
detectArrivals(noReplay, at(890, "confirmed"), watched, 890, new Map());
if (detectArrivals(noReplay, at(1500, "picked_up"), watched, 1500, new Map())[0]?.resource_name !== "Van 1") throw new Error("status arrival missed");

console.log(JSON.stringify({
  events: events.length,
  types: [...seen],
  versions: parsed.plans.ember.versions.map((version) => version.version),
  reachedDelta: delta,
  scenario: opening.scenario_id,
  judge: judge.household_id,
  facilities: opening.facilities.map((facility) => facility.id),
}));

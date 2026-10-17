import { readFileSync } from "node:fs";
import { asComparison, readEnvelope, scatterFromEnvelopes, seqDecision } from "../src/live.ts";
import { buildOpening, type OpeningScenario } from "../src/opening.ts";
import type { Town } from "../src/types.ts";

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

const comparison = JSON.parse(readFileSync(new URL("contracts/fixtures/comparison.fixture.json", root), "utf8")) as unknown;
const parsed = asComparison(comparison);
if (!parsed) throw new Error("comparison fixture rejected");
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

console.log(JSON.stringify({
  events: events.length,
  types: [...seen],
  versions: parsed.plans.ember.versions.map((version) => version.version),
  reachedDelta: delta,
  scenario: opening.scenario_id,
  judge: judge.household_id,
  facilities: opening.facilities.map((facility) => facility.id),
}));

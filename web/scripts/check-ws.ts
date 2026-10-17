import { readFileSync } from "node:fs";
import { asComparison, readEnvelope, seqDecision } from "../src/live.ts";

const events = JSON.parse(readFileSync("/tmp/ws-events.fixture.json", "utf8")) as unknown[];
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
}
for (const type of ["state", "plan", "assignment", "message", "report", "scatter_point", "metrics"]) {
  if (!seen.has(type)) throw new Error(`missing ${type}`);
}

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

const comparison = JSON.parse(readFileSync(new URL("../../contracts/fixtures/comparison.fixture.json", import.meta.url), "utf8")) as unknown;
const parsed = asComparison(comparison);
if (!parsed) throw new Error("comparison fixture rejected");
const reached = parsed.metrics.find((metric) => metric.metric === "people_reached_before_deadline");
if (!reached) throw new Error("missing reached metric");
const delta = parsed.nominal.ember.people_reached_before_deadline! - parsed.nominal.baseline.people_reached_before_deadline!;
if (delta !== 37) throw new Error(`B-A for people reached should be 37, got ${delta}`);
if (parsed.plans.ember.versions.length < 2) throw new Error("missing ember versions");
console.log(JSON.stringify({
  events: events.length,
  types: [...seen],
  versions: parsed.plans.ember.versions.map((version) => version.version),
  reachedDelta: delta,
}));

import type {
  Assignment,
  Closure,
  FacilityState,
  HouseholdStatus,
  LngLat,
  PlanMetrics,
  PlanSnapshot,
  ResourceStatus,
  StateSnapshot,
  Target,
} from "./types";

/** contracts/playback.schema.json v0.1: one plan simulated over the whole horizon (D70). */
export type Change<T> = [number, T];

export type Track = {
  id: string;
  kind: string;
  name: string;
  path: LngLat[];
  t: number[];
  status: Change<ResourceStatus>[];
  on_board: Change<number>[];
  assignment: Change<string | null>[];
};

export type PlaybackEvent = {
  t_s: number;
  kind: string;
  assignment_id?: string;
  resource_id?: string;
  household_id?: number;
  facility_id?: string;
  people?: number;
  met_deadline?: boolean;
  reason?: string;
  from?: string;
  to?: string;
  [key: string]: unknown;
};

export type Outcome = {
  assignment_id: string;
  resource_id: string;
  task: string;
  target: Target;
  status: string;
  reason?: string;
  arrive_t: number | null;
  pickup_t: number | null;
  complete_t: number | null;
  deadline_s: number | null;
  met_deadline: boolean | null;
  people: number;
};

export type Playback = {
  version: string;
  scenario_id: string;
  planner: string;
  plan_version: number | null;
  t0: number;
  dt: number;
  t_end_s: number;
  synthetic?: string[];
  t_s: number[];
  tracks: Track[];
  households: { household_id: number; deadline_s?: number | null; status: Change<HouseholdStatus>[] }[];
  facilities: { id: string; state: Change<FacilityState>[]; generator: Change<string | null>[] }[];
  wastewater: Record<string, { storage_m3: number[]; overflow_m3: number[] }>;
  on_site?: Record<string, number[]>;
  closures: [number, number, number | null][];
  events: PlaybackEvent[];
  reports?: Array<{ id?: string; t_s?: number; kind?: string; household_id?: number; facility_id?: string; note?: string; text?: string; source?: string }>;
  outcomes: Outcome[];
  plan: {
    version: number | null;
    planner?: string | null;
    trigger?: string | null;
    created_at_t_s?: number;
    assignments: Array<Omit<Assignment, "plan_version" | "eta_s" | "deadline_s" | "status" | "rationale"> & {
      eta_s?: number;
      deadline_s?: number | null;
      status?: string;
      rationale?: string;
    }>;
    unresolved?: PlanSnapshot["unresolved"];
    info_requests?: PlanSnapshot["info_requests"];
    metrics?: PlanMetrics;
  };
  metrics: PlanMetrics;
  /** v0.2 (D73): synthetic background cars from the scenario's staged evacuation */
  traffic?: {
    synthetic: true;
    rule: string;
    config?: Record<string, unknown>;
    bin_s?: number;
    metrics?: Record<string, number>;
    cars: Array<{ id: string; path: LngLat[]; t: number[] }>;
  };
};

export function asPlayback(value: unknown): Playback | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (!Array.isArray(record.tracks) || !Array.isArray(record.t_s) || typeof record.plan !== "object") return null;
  return value as Playback;
}

/** Last index i with xs[i] <= t (−1 if none). */
export function floorIndex(xs: number[], t: number): number {
  let lo = 0;
  let hi = xs.length - 1;
  if (hi < 0 || xs[0] > t) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (xs[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export function changeAt<T>(changes: Change<T>[], t: number, fallback: T): T {
  let lo = 0;
  let hi = changes.length - 1;
  if (hi < 0 || changes[0][0] > t) return changes[0]?.[1] ?? fallback;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (changes[mid][0] <= t) lo = mid;
    else hi = mid - 1;
  }
  return changes[lo][1];
}

/** Compass heading (deg, clockwise from north) from a to b; null when they coincide. */
export function headingOf(a: LngLat, b: LngLat): number | null {
  const k = Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  const dx = (b[0] - a[0]) * k;
  const dy = b[1] - a[1];
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return null;
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
}

export type TrackPose = { position: LngLat; heading: number; moving: boolean; index: number };

/** Position along a polyline with timestamps (tracks and walkers share this). */
export function poseAt(path: LngLat[], times: number[], t: number, lastHeading = 0): TrackPose {
  if (path.length === 0) return { position: [0, 0], heading: lastHeading, moving: false, index: 0 };
  const i = floorIndex(times, t);
  if (i < 0) return { position: path[0], heading: headingNear(path, 0, lastHeading), moving: false, index: 0 };
  if (i >= path.length - 1) {
    return { position: path[path.length - 1], heading: headingNear(path, path.length - 1, lastHeading), moving: false, index: path.length - 1 };
  }
  const a = path[i];
  const b = path[i + 1];
  const span = times[i + 1] - times[i];
  const f = span > 0 ? Math.min(1, Math.max(0, (t - times[i]) / span)) : 1;
  const heading = headingOf(a, b);
  return {
    position: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f],
    heading: heading ?? headingNear(path, i, lastHeading),
    moving: heading != null,
    index: i,
  };
}

/** Heading of the nearest non-degenerate segment, looking back first (a parked van keeps its last direction). */
function headingNear(path: LngLat[], i: number, fallback: number): number {
  for (let j = Math.min(i, path.length - 1); j > 0; j--) {
    const h = headingOf(path[j - 1], path[j]);
    if (h != null) return h;
  }
  for (let j = Math.max(0, i); j < path.length - 1; j++) {
    const h = headingOf(path[j], path[j + 1]);
    if (h != null) return h;
  }
  return fallback;
}

/** The rest of a track until it next stops (where the vehicle is heading right now). */
export function pathAhead(track: Track, t: number): LngLat[] {
  const pose = poseAt(track.path, track.t, t);
  if (!pose.moving) return [];
  const out: LngLat[] = [pose.position];
  for (let j = pose.index + 1; j < track.path.length; j++) {
    const p = track.path[j];
    const prev = out[out.length - 1];
    out.push(p);
    if (prev[0] === p[0] && prev[1] === p[1]) break;
    if (j + 1 < track.path.length && track.t[j + 1] - track.t[j] > 0 && headingOf(p, track.path[j + 1]) == null) break;
  }
  return out;
}

function tickIndex(pb: Playback, t: number): number {
  return Math.max(0, floorIndex(pb.t_s, t));
}

/** What the map and panels need at clock t, from a playback over a base snapshot (scenario picture or GET /state). */
export function stateFromPlayback(pb: Playback, base: StateSnapshot, t: number): StateSnapshot {
  const k = tickIndex(pb, t);
  const hhById = new Map(pb.households.map((household) => [household.household_id, household]));
  const facById = new Map(pb.facilities.map((facility) => [facility.id, facility]));
  const trackById = new Map(pb.tracks.map((track) => [track.id, track]));
  const outcomeByAssignment = new Map(pb.outcomes.map((outcome) => [outcome.assignment_id, outcome]));
  const planVersion = pb.plan.version ?? pb.plan_version ?? base.plan_version ?? 1;

  const assignments: Assignment[] = pb.plan.assignments.map((assignment) => {
    const outcome = outcomeByAssignment.get(assignment.id);
    return {
      ...assignment,
      plan_version: planVersion,
      eta_s: outcome?.arrive_t ?? assignment.eta_s ?? 0,
      deadline_s: assignment.deadline_s ?? outcome?.deadline_s ?? null,
      status: assignmentStatus(outcome, t, assignment.status ?? "proposed"),
      rationale: assignment.rationale ?? "",
    } as Assignment;
  });
  const assignmentByHousehold = new Map<number, Assignment>();
  for (const assignment of assignments) {
    if ("household_id" in assignment.target && !assignmentByHousehold.has(assignment.target.household_id)) {
      assignmentByHousehold.set(assignment.target.household_id, assignment);
    }
  }

  const households = base.households.map((household) => {
    const row = hhById.get(household.household_id);
    if (!row) return household;
    const assignment = assignmentByHousehold.get(household.household_id);
    return {
      ...household,
      status: changeAt(row.status, t, household.status),
      deadline_s: row.deadline_s ?? household.deadline_s,
      assignment_id: assignment?.id ?? household.assignment_id,
    };
  });

  const facilities = base.facilities.map((facility) => {
    const row = facById.get(facility.id);
    const water = pb.wastewater[facility.id];
    const state = row ? changeAt(row.state, t, facility.state) : facility.state;
    return {
      ...facility,
      state,
      powered_by: row ? changeAt(row.generator, t, null) : facility.powered_by,
      people_on_site: pb.on_site?.[facility.id]?.[k] ?? facility.people_on_site,
      wastewater: facility.wastewater && water
        ? {
            ...facility.wastewater,
            storage_m3: water.storage_m3[k] ?? facility.wastewater.storage_m3,
            overflow_m3: water.overflow_m3[k] ?? facility.wastewater.overflow_m3,
            series: { t_s: pb.t_s.slice(0, k + 1), storage_m3: water.storage_m3.slice(0, k + 1), overflow_m3: water.overflow_m3.slice(0, k + 1) },
          }
        : facility.wastewater,
    };
  });

  const resources = base.resources.map((resource) => {
    const track = trackById.get(resource.id);
    if (!track) return resource;
    const pose = poseAt(track.path, track.t, t);
    const assignmentId = changeAt(track.assignment, t, null);
    const outcome = assignmentId ? outcomeByAssignment.get(assignmentId) : undefined;
    return {
      ...resource,
      lon: pose.position[0],
      lat: pose.position[1],
      heading_deg: pose.heading,
      status: changeAt(track.status, t, resource.status),
      people_on_board: changeAt(track.on_board, t, 0),
      assignment_id: assignmentId,
      eta_s: outcome?.arrive_t != null && outcome.arrive_t > t ? outcome.arrive_t : null,
    };
  });

  const closures: Closure[] = pb.closures
    .filter(([, from, reopened]) => from <= t && (reopened == null || reopened > t))
    .map(([edge_id, from]) => ({ edge_id, closed_from_t_s: from, source: "hazard" as const }));

  const reached = pb.events
    .filter((event) => event.kind === "pickup" && event.t_s <= t && event.met_deadline)
    .reduce((sum, event) => sum + (event.people ?? 0), 0);
  const unreached = pb.events
    .filter((event) => event.kind === "deadline_missed" && event.t_s <= t)
    .reduce((sum, event) => {
      const household = base.households.find((item) => item.household_id === event.household_id);
      const needs = household?.needs;
      return sum + (needs && needs !== "unknown" && typeof needs.people === "number" ? needs.people : 1);
    }, 0);
  const overflow = Object.values(pb.wastewater).reduce((sum, water) => sum + (water.overflow_m3[k] ?? 0), 0);

  const plan: PlanSnapshot = {
    version: planVersion,
    parent_version: null,
    created_at_t_s: pb.plan.created_at_t_s ?? 0,
    trigger: pb.plan.trigger ?? undefined,
    planner: (pb.planner as PlanSnapshot["planner"]) ?? "ember",
    assignments,
    changes: base.plan?.version === planVersion ? base.plan.changes : [],
    unresolved: pb.plan.unresolved ?? [],
    info_requests: pb.plan.info_requests ?? [],
    search: base.plan?.version === planVersion ? base.plan.search : undefined,
    metrics: { ...pb.metrics, projected: true },
  };

  return {
    ...base,
    t_s: t,
    plan_version: planVersion,
    households,
    facilities,
    resources,
    closures: base.source === "backend" ? mergeClosures(base.closures, closures, t) : closures,
    plan,
    metrics: {
      people_reached_before_deadline: reached,
      people_unreached: unreached,
      overflow_m3: overflow,
      projected: false,
    },
  };
}

function mergeClosures(published: Closure[], replay: Closure[], t: number): Closure[] {
  const byId = new Map(replay.map((closure) => [closure.edge_id, closure]));
  for (const closure of published) if (closure.closed_from_t_s <= t) byId.set(closure.edge_id, closure);
  return [...byId.values()];
}

function assignmentStatus(outcome: Outcome | undefined, t: number, planned: string): string {
  if (!outcome) return planned;
  if (outcome.status === "infeasible" && (outcome.arrive_t == null || t >= outcome.arrive_t)) return "cancelled";
  if (outcome.arrive_t == null) return planned;
  if (t < outcome.arrive_t) return outcome.status === "pending" ? planned : "en_route";
  if (outcome.complete_t == null || t < outcome.complete_t) return "working";
  return "done";
}

export type TimelineItem = { t_s: number; text: string; tone?: "good" | "bad" | "info" };

const RESOURCE_NAME = (pb: Playback, id: string | undefined) =>
  pb.tracks.find((track) => track.id === id)?.name ?? id ?? "a vehicle";

/** Plain-language history of one household from the replay (events, reports) up to clock t. */
export function householdTimeline(pb: Playback, householdId: number, t: number): TimelineItem[] {
  const ids = new Set(
    pb.plan.assignments
      .filter((assignment) => "household_id" in assignment.target && assignment.target.household_id === householdId)
      .map((assignment) => assignment.id),
  );
  const items: TimelineItem[] = [];
  for (const report of pb.reports ?? []) {
    if (report.household_id === householdId && (report.t_s ?? 0) <= t) {
      items.push({ t_s: report.t_s ?? 0, text: `Report: ${report.note ?? report.text ?? report.kind ?? "new information"}`, tone: "info" });
    }
  }
  for (const event of pb.events) {
    if (event.t_s > t) break;
    const mine = event.household_id === householdId || (event.assignment_id != null && ids.has(event.assignment_id));
    if (!mine) continue;
    const who = RESOURCE_NAME(pb, event.resource_id ?? pb.plan.assignments.find((a) => a.id === event.assignment_id)?.resource_id);
    if (event.kind === "dispatch") items.push({ t_s: event.t_s, text: `${who} dispatched to them` });
    else if (event.kind === "arrive") items.push({ t_s: event.t_s, text: `${who} arrived at the door` });
    else if (event.kind === "pickup") {
      items.push({
        t_s: event.t_s,
        text: `${event.people ?? "?"} picked up${event.met_deadline ? ", before the water" : ", after the deadline"}`,
        tone: event.met_deadline ? "good" : "bad",
      });
    } else if (event.kind === "dropoff") items.push({ t_s: event.t_s, text: "Dropped off at the shelter", tone: "good" });
    else if (event.kind === "deadline_missed") items.push({ t_s: event.t_s, text: "Water reached them before help did", tone: "bad" });
    else if (event.kind === "assignment_infeasible") items.push({ t_s: event.t_s, text: `${who} could not reach them: ${event.reason ?? "cut off"}`, tone: "bad" });
  }
  return items.sort((a, b) => a.t_s - b.t_s);
}

export function resourceTimeline(pb: Playback, resourceId: string, t: number): TimelineItem[] {
  const items: TimelineItem[] = [];
  const label = (event: PlaybackEvent) => {
    const assignment = pb.plan.assignments.find((a) => a.id === event.assignment_id);
    if (!assignment) return "";
    return "household_id" in assignment.target ? `household #${assignment.target.household_id}` : assignment.target.facility_id;
  };
  for (const event of pb.events) {
    if (event.t_s > t) break;
    const assignment = pb.plan.assignments.find((a) => a.id === event.assignment_id);
    if (event.resource_id !== resourceId && assignment?.resource_id !== resourceId) continue;
    if (event.kind === "dispatch") items.push({ t_s: event.t_s, text: `Dispatched → ${label(event)}` });
    else if (event.kind === "arrive") items.push({ t_s: event.t_s, text: `Arrived at ${label(event)}` });
    else if (event.kind === "pickup") items.push({ t_s: event.t_s, text: `Picked up ${event.people ?? "?"}`, tone: event.met_deadline ? "good" : "bad" });
    else if (event.kind === "dropoff") items.push({ t_s: event.t_s, text: "Dropped off at the shelter", tone: "good" });
    else if (event.kind === "generator_connected") items.push({ t_s: event.t_s, text: `Generator connected at ${event.facility_id}`, tone: "good" });
    else if (event.kind === "resource_failed") items.push({ t_s: event.t_s, text: "Broke down", tone: "bad" });
    else if (event.kind === "assignment_infeasible") items.push({ t_s: event.t_s, text: `Gave up: ${event.reason ?? "cut off"}`, tone: "bad" });
  }
  return items;
}

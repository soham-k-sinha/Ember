import { lineIntersectsGeometry } from "./geo";
import { scenario, town } from "./fixtures";
import type {
  Assignment,
  Closure,
  FloodGeometry,
  HouseholdStatus,
  JudgeClosure,
  LngLat,
  ScenarioKeyframe,
  StateFacility,
  StateHousehold,
  StateResource,
  StateSnapshot,
  Target,
  TownEdge,
} from "./types";

const edgeById = new Map<number, TownEdge>(town.edges.map((edge) => [edge.id, edge]));
const nodePos = new Map<number, LngLat>(town.nodes.map((node) => [node.id, [node.lon, node.lat]]));

const STATUS_COLOR: Record<HouseholdStatus, [number, number, number]> = {
  unknown: [245, 182, 66],
  needs: [240, 92, 72],
  assigned: [96, 165, 250],
  confirmed: [52, 211, 183],
  picked_up: [125, 211, 252],
  safe: [110, 220, 130],
  unreached: [236, 72, 153],
};

export function householdColor(household: StateHousehold): [number, number, number] {
  return STATUS_COLOR[household.status];
}

export function peopleCount(household: StateHousehold, fallback = 2): number {
  const needs = household.needs;
  if (needs !== "unknown" && typeof needs.people === "number") return needs.people;
  return fallback;
}

/** Where a household's people wait: on the street a few metres from the nearest road node, toward the home. */
export function curb(lon: number, lat: number, node: number | undefined): LngLat {
  const at = node != null ? nodePos.get(node) : undefined;
  if (!at) return [lon, lat];
  const dx = lon - at[0];
  const dy = lat - at[1];
  const d = Math.hypot(dx * 82_000, dy * 111_000);
  if (d < 1) return at;
  const f = Math.min(1, 7 / d);
  return [at[0] + dx * f, at[1] + dy * f];
}

export function edgeRecord(id: number): TownEdge | undefined {
  return edgeById.get(id);
}

/** A named street at this road node ("Soldiers Field Road"), if one meets it. */
export function streetAt(node: number): string | undefined {
  return town.edges.find((edge) => (edge.u === node || edge.v === node) && edge.name)?.name ?? undefined;
}

export function assistedIds(state: StateSnapshot): Set<number> {
  return new Set(state.households.map((household) => household.household_id));
}

function activeKeyframe(t: number): ScenarioKeyframe | null {
  let current: ScenarioKeyframe | null = null;
  for (const frame of scenario.hazard.keyframes) {
    if (frame.t_s <= t) current = frame;
  }
  return current;
}

export function floodGeometry(state: StateSnapshot, t: number): FloodGeometry | null {
  if (state.scenario_id !== scenario.scenario_id) return state.hazard.geometry;
  const frame = activeKeyframe(t);
  if (
    frame &&
    state.hazard.keyframe_t_s != null &&
    frame.t_s === state.hazard.keyframe_t_s &&
    state.hazard.geometry
  ) {
    return state.hazard.geometry;
  }
  return frame?.geometry ?? state.hazard.geometry;
}

/** Closures published in the state snapshot, plus judge clicks, plus edges that
 * later flood polygons of the same scenario cover. A snapshot's own keyframe is
 * left to `state.closures` so a published list is not redrawn. */
export function closedEdges(
  state: StateSnapshot,
  t: number,
  judge: JudgeClosure[],
): Closure[] {
  const byId = new Map<number, Closure>();
  for (const closure of state.closures) {
    if (closure.closed_from_t_s <= t) byId.set(closure.edge_id, closure);
  }
  for (const closure of judge) {
    if (closure.closed_from_t_s <= t) {
      byId.set(closure.edge_id, {
        edge_id: closure.edge_id,
        closed_from_t_s: closure.closed_from_t_s,
        source: "judge",
      });
    }
  }

  if (state.scenario_id !== scenario.scenario_id) return [...byId.values()];

  const publishedHorizon = state.closures.reduce(
    (max, closure) => Math.max(max, closure.closed_from_t_s),
    0,
  );
  for (const frame of scenario.hazard.keyframes) {
    if (frame.t_s > t || frame.t_s <= publishedHorizon) continue;
    for (const edge of town.edges) {
      if (byId.has(edge.id)) continue;
      if (lineIntersectsGeometry(edge.geom, frame.geometry)) {
        byId.set(edge.id, {
          edge_id: edge.id,
          closed_from_t_s: frame.t_s,
          source: "hazard",
        });
      }
    }
  }
  return [...byId.values()];
}

export function householdById(state: StateSnapshot, id: number): StateHousehold | undefined {
  return state.households.find((household) => household.household_id === id);
}

export function facilityById(state: StateSnapshot, id: string): StateFacility | undefined {
  return state.facilities.find((facility) => facility.id === id);
}

export function resourceById(state: StateSnapshot, id: string): StateResource | undefined {
  return state.resources.find((resource) => resource.id === id);
}

export function assignmentById(state: StateSnapshot, id: string | null): Assignment | undefined {
  if (!id || !state.plan) return undefined;
  return state.plan.assignments.find((assignment) => assignment.id === id);
}

export function assignmentForTarget(state: StateSnapshot, target: Target): Assignment | undefined {
  return state.plan?.assignments.find((assignment) => {
    if ("household_id" in target && "household_id" in assignment.target) {
      return assignment.target.household_id === target.household_id;
    }
    if ("facility_id" in target && "facility_id" in assignment.target) {
      return assignment.target.facility_id === target.facility_id;
    }
    return false;
  });
}

/** A thread or target as the projector names it: "Judge", "Player 2", a facility's name, else "#id". */
export function targetName(state: StateSnapshot, target: Target): string {
  if ("household_id" in target) {
    const household = householdById(state, target.household_id);
    if (household?.judge) return "Judge";
    return household?.label && !/^household/i.test(household.label) ? household.label : `#${target.household_id}`;
  }
  return facilityById(state, target.facility_id)?.name ?? target.facility_id;
}

export function closureFor(
  closures: Closure[],
  edgeId: number,
): Closure | undefined {
  return closures.find((closure) => closure.edge_id === edgeId);
}

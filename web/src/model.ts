import { lineIntersectsGeometry } from "./geo";
import { scenario, town } from "./fixtures";
import type {
  Assignment,
  Closure,
  FloodGeometry,
  JudgeClosure,
  PlanSnapshot,
  ScenarioKeyframe,
  Selection,
  StateFacility,
  StateHousehold,
  StateResource,
  StateSnapshot,
  Target,
  TownEdge,
} from "./types";

const edgeById = new Map<number, TownEdge>(town.edges.map((edge) => [edge.id, edge]));

export function edgeRecord(id: number): TownEdge | undefined {
  return edgeById.get(id);
}

export function assistedIds(state: StateSnapshot): Set<number> {
  return new Set(state.households.map((household) => household.household_id));
}

export function activeKeyframe(t: number): ScenarioKeyframe | null {
  let current: ScenarioKeyframe | null = null;
  for (const frame of scenario.hazard.keyframes) {
    if (frame.t_s <= t) current = frame;
  }
  return current;
}

export function floodGeometry(state: StateSnapshot, t: number): FloodGeometry | null {
  const frame = activeKeyframe(t);
  if (
    frame &&
    state.hazard.keyframe_t_s != null &&
    frame.t_s === state.hazard.keyframe_t_s &&
    state.hazard.geometry
  ) {
    return state.hazard.geometry;
  }
  return frame?.geometry ?? null;
}

/** Closures published in the state snapshot, plus judge clicks, plus edges the
 * later flood polygons cover. The 80-minute fixture is used verbatim for its
 * own keyframe so the map matches `state.fixture.json`. */
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

  const publishedHorizon = state.closures.reduce(
    (max, closure) => Math.max(max, closure.closed_from_t_s),
    0,
  );
  const frame = activeKeyframe(t);
  if (frame && frame.t_s > publishedHorizon) {
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

export function assignmentsOf(plan: PlanSnapshot | null): Assignment[] {
  return plan?.assignments ?? [];
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

export function positionForTarget(
  state: StateSnapshot,
  target: Target,
): [number, number] | null {
  if ("household_id" in target) {
    const household = householdById(state, target.household_id);
    return household ? [household.lon, household.lat] : null;
  }
  const facility = facilityById(state, target.facility_id);
  return facility ? [facility.lon, facility.lat] : null;
}

export function closureFor(
  closures: Closure[],
  edgeId: number,
): Closure | undefined {
  return closures.find((closure) => closure.edge_id === edgeId);
}

export function isSameSelection(a: Selection | null, b: Selection | null): boolean {
  if (a == null || b == null) return a === b;
  return a.kind === b.kind && a.id === b.id;
}

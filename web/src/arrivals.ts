import type { Outcome } from "./playback";
import type { Arrival, HouseholdStatus, StateSnapshot } from "./types";

const REACHED = new Set<HouseholdStatus>(["picked_up", "safe"]);

/** When each household's vehicle reaches its door in the replay (the outcome's arrive_t), and which vehicle. */
export type Doors = Map<number, { t: number; resource_id: string }>;

export function doorsFrom(outcomes: Outcome[] | undefined): Doors {
  const doors: Doors = new Map();
  for (const outcome of outcomes ?? []) {
    if (outcome.arrive_t == null || !("household_id" in outcome.target)) continue;
    const id = outcome.target.household_id;
    const known = doors.get(id);
    if (!known || outcome.arrive_t < known.t) doors.set(id, { t: outcome.arrive_t, resource_id: outcome.resource_id });
  }
  return doors;
}

/**
 * Arrivals since the last look: a watched household (a player's, or the judge's) whose vehicle is now at its door,
 * by the replay's arrival time, or else by its status turning to picked up. `seen` holds whether each one was
 * reached at the last look; the first sighting only records it, so a reload never alerts on what already happened,
 * and a household that is not reached again (the clock went back) can alert again.
 */
export function detectArrivals(
  seen: Map<number, boolean>,
  state: StateSnapshot,
  watched: Map<number, { player: number | null; onCall: boolean }>,
  t: number,
  doors: Doors,
): Arrival[] {
  const found: Arrival[] = [];
  for (const household of state.households) {
    const who = watched.get(household.household_id) ?? (household.judge ? { player: null, onCall: false } : undefined);
    if (!who) continue;
    const door = doors.get(household.household_id);
    const reached = (door != null && t >= door.t) || REACHED.has(household.status);
    const before = seen.get(household.household_id);
    seen.set(household.household_id, reached);
    if (before !== false || !reached) continue;
    const assignments = state.plan?.assignments ?? [];
    const resourceId = door?.resource_id
      ?? (assignments.find((item) => item.id === household.assignment_id)
        ?? assignments.find((item) => "household_id" in item.target && item.target.household_id === household.household_id))?.resource_id;
    if (!resourceId) continue;
    found.push({
      t_s: door && t >= door.t ? door.t : t,
      household_id: household.household_id,
      resource_id: resourceId,
      resource_name: state.resources.find((item) => item.id === resourceId)?.name ?? resourceId,
      player: who.player,
      call: who.onCall,
    });
  }
  return found;
}

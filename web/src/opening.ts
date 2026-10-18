import type {
  FloodGeometry,
  Needs,
  Scenario,
  StateFacility,
  StateHousehold,
  StateResource,
  StateSnapshot,
  Town,
} from "./types";

type InflowPoint = [number, number];

type ScenarioWastewater = {
  storage_m3: number;
  storage_max_m3: number;
  pump_m3ph?: number;
  inflow_m3ph?: number | InflowPoint[];
};

type ScenarioFacility = {
  id: string;
  type: string;
  name: string;
  asset_id?: number;
  node?: number;
  synthetic?: boolean;
  critical?: boolean;
  connector?: string;
  backup_endurance_s?: number;
  depends_on?: string[];
  capacity_people?: number;
  consequence?: string;
  wastewater?: ScenarioWastewater;
  events?: Array<{ t_s: number; state?: string; note?: string }>;
};

type ScenarioResource = {
  id: string;
  kind: string;
  name: string;
  at_facility?: string;
  capacity_people?: number;
  accessible?: boolean;
  kw?: number;
  connector?: string;
  fuel_l?: number;
};

type ScenarioHousehold = {
  household_id: number;
  label?: string;
  judge?: boolean;
  phone_role?: "resident" | "none";
  needs: Needs;
};

export type OpeningScenario = Scenario & {
  synthetic?: string[];
  facilities: ScenarioFacility[];
  resources: ScenarioResource[];
  households: ScenarioHousehold[];
};

function inflowAt(schedule: ScenarioWastewater["inflow_m3ph"], t: number): number {
  if (typeof schedule === "number") return schedule;
  if (!schedule || schedule.length === 0) return 0;
  let rate = schedule[0][1];
  for (const [at, value] of schedule) {
    if (at <= t) rate = value;
  }
  return rate;
}

function placeFacility(facility: ScenarioFacility, town: Town): { lon: number; lat: number; node: number } {
  if (facility.asset_id != null) {
    const asset = town.assets.find((item) => item.id === facility.asset_id);
    if (!asset) throw new Error(`scenario facility ${facility.id} asset_id ${facility.asset_id} is not in the town fixture`);
    return { lon: asset.lon, lat: asset.lat, node: asset.node };
  }
  if (facility.node != null) {
    const node = town.nodes.find((item) => item.id === facility.node);
    if (!node) throw new Error(`scenario facility ${facility.id} node ${facility.node} is not in the town fixture`);
    return { lon: node.lon, lat: node.lat, node: node.id };
  }
  throw new Error(`scenario facility ${facility.id} has neither asset_id nor node`);
}

/** t = 0 picture of a scenario: places, needs, and fleet from the scenario file,
 * geometry from the town fixture. Not a simulated plan. */
export function buildOpening(scenario: OpeningScenario, town: Town): StateSnapshot {
  const facilities: StateFacility[] = scenario.facilities.map((facility) => {
    const place = placeFacility(facility, town);
    const water = facility.wastewater;
    return {
      id: facility.id,
      type: facility.type,
      name: facility.name,
      lon: place.lon,
      lat: place.lat,
      node: place.node,
      synthetic: facility.synthetic,
      critical: facility.critical,
      state: "ok",
      state_since_t_s: 0,
      endurance_left_s: facility.backup_endurance_s ?? null,
      powered_by: null,
      threatened_at_s: facility.events?.[0]?.t_s ?? null,
      depends_on: facility.depends_on ?? [],
      consequence: facility.consequence,
      capacity_people: facility.capacity_people,
      wastewater: water
        ? {
            storage_m3: water.storage_m3,
            storage_max_m3: water.storage_max_m3,
            inflow_m3ph: inflowAt(water.inflow_m3ph, 0),
            pumped_m3ph: water.pump_m3ph ?? 0,
            overflow_m3: 0,
          }
        : null,
    };
  });
  const facilityById = new Map(facilities.map((facility) => [facility.id, facility]));
  const resources: StateResource[] = scenario.resources.map((resource) => {
    const home = resource.at_facility ? facilityById.get(resource.at_facility) : undefined;
    if (!home) throw new Error(`resource ${resource.id} at_facility ${resource.at_facility ?? "?"} is not in the scenario`);
    return {
      id: resource.id,
      kind: resource.kind,
      name: resource.name,
      lon: home.lon,
      lat: home.lat,
      node: home.node,
      edge_id: null,
      status: "available",
      assignment_id: null,
      eta_s: null,
      capacity_people: resource.capacity_people,
      people_on_board: 0,
      accessible: resource.accessible,
      kw: resource.kw,
      connector: resource.connector,
      fuel_l: resource.fuel_l ?? 0,
    };
  });
  const households: StateHousehold[] = scenario.households.map((household) => {
    const place = town.households.find((item) => item.id === household.household_id);
    if (!place) {
      throw new Error(`assisted household ${household.household_id} is not in the town fixture`);
    }
    const unknown = household.needs === "unknown";
    return {
      household_id: household.household_id,
      label: household.label,
      lon: place.lon,
      lat: place.lat,
      node: place.node,
      judge: household.judge,
      phone_role: household.phone_role,
      needs: household.needs,
      needs_source: unknown ? undefined : "scenario",
      deadline_s: null,
      status: unknown ? "unknown" : "needs",
      assignment_id: null,
    };
  });
  const times = scenario.hazard.keyframes.map((frame) => frame.t_s);
  return {
    version: "0.3",
    scenario_id: scenario.scenario_id,
    t_s: 0,
    plan_version: null,
    source: "scenario",
    synthetic: scenario.synthetic,
    hazard: {
      keyframe_t_s: null,
      geometry: null as FloodGeometry | null,
      next_keyframe_t_s: times[0] ?? null,
      keyframe_times_s: times,
    },
    closures: [],
    households,
    facilities,
    resources,
    plan: null,
    reports: [],
    messages: [],
    metrics: {},
  };
}

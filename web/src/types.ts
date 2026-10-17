import type { Feature, GeoJsonProperties, MultiPolygon, Polygon } from "geojson";

export type LngLat = [number, number];

export type FloodGeometry = Polygon | MultiPolygon;

export type HouseholdStatus =
  | "unknown"
  | "needs"
  | "assigned"
  | "confirmed"
  | "picked_up"
  | "safe"
  | "unreached";

export type FacilityState = "ok" | "backup" | "down";

export type ResourceStatus =
  | "available"
  | "en_route"
  | "working"
  | "returning"
  | "reserved"
  | "stalled"
  | "out_of_service";

export type Needs =
  | "unknown"
  | {
      people?: number;
      mobility?: boolean;
      accessible_vehicle?: boolean;
      medical?: boolean;
    };

export type Target = { household_id: number } | { facility_id: string };

export type TownEdge = {
  id: number;
  u: number;
  v: number;
  length_m: number;
  highway: string;
  name: string | null;
  geom: LngLat[];
};

export type TownHousehold = {
  id: number;
  lon: number;
  lat: number;
  node: number;
  zone: number;
  size: number;
  vehicles: number;
};

export type Town = {
  meta: {
    version: string;
    center: LngLat;
    synthetic: string[];
    counts: { households: number; edges: number };
  };
  venue: { name: string; lon: number; lat: number; node: number; source?: string };
  edges: TownEdge[];
  households: TownHousehold[];
};

export type ScenarioKeyframe = {
  t_s: number;
  label?: string;
  geometry: FloodGeometry;
};

export type Scenario = {
  version: string;
  scenario_id: string;
  name: string;
  description?: string;
  synthetic?: string[];
  t_end_s: number;
  tick_s?: number;
  hazard: {
    type: string;
    source?: string;
    keyframes: ScenarioKeyframe[];
  };
  district?: { name: string; geometry: FloodGeometry };
};

export type Closure = {
  edge_id: number;
  closed_from_t_s: number;
  source: "hazard" | "report" | "plan" | "judge";
  report_id?: string;
  confidence?: number;
};

export type StateHousehold = {
  household_id: number;
  label?: string;
  lon: number;
  lat: number;
  node: number;
  judge?: boolean;
  phone_role?: "resident" | "none";
  needs: Needs;
  needs_source?: "scenario" | "report";
  deadline_s: number | null;
  status: HouseholdStatus;
  assignment_id: string | null;
};

export type Wastewater = {
  storage_m3: number;
  storage_max_m3: number;
  inflow_m3ph: number;
  pumped_m3ph: number;
  overflow_m3: number;
  series?: { t_s: number[]; storage_m3: number[]; overflow_m3: number[] };
};

export type StateFacility = {
  id: string;
  type: string;
  name: string;
  lon: number;
  lat: number;
  node: number;
  synthetic?: boolean;
  critical?: boolean;
  state: FacilityState;
  state_since_t_s?: number;
  endurance_left_s: number | null;
  powered_by: string | null;
  threatened_at_s: number | null;
  depends_on: string[];
  consequence?: string;
  people_on_site?: number;
  capacity_people?: number;
  wastewater: Wastewater | null;
};

export type StateResource = {
  id: string;
  kind: string;
  name: string;
  lon: number;
  lat: number;
  node: number | null;
  edge_id: number | null;
  heading_deg?: number | null;
  status: ResourceStatus;
  assignment_id: string | null;
  eta_s: number | null;
  capacity_people?: number;
  people_on_board?: number;
  accessible?: boolean;
  kw?: number;
  connector?: string;
  fuel_l: number;
  km_driven?: number;
};

export type Assignment = {
  id: string;
  plan_version: number;
  resource_id: string;
  task: "rescue" | "protect" | "clear_road";
  target: Target;
  dropoff_facility_id?: string | null;
  eta_s: number;
  deadline_s: number | null;
  slack_s?: number | null;
  status: string;
  rationale: string;
  route_edges?: number[];
  route?: LngLat[];
};

export type PlanChange = {
  assignment_id: string;
  change: "added" | "removed" | "retargeted" | "eta_changed" | "resource_changed" | "status_changed";
  note?: string;
};

export type Unresolved = {
  target: Target;
  need: string;
  blocked_by: string;
  would_unblock?: string;
  alternatives?: string[];
};

export type InfoRequest = {
  id: string;
  to: Target;
  question: string;
  why: string;
};

export type PlanMetrics = {
  projected?: boolean;
  people_reached_before_deadline?: number;
  people_unreached?: number;
  unresolved_needs?: number;
  hospital_outage_s?: number;
  service_outage_s_total?: number;
  overflow_m3?: number;
  fuel_l?: number;
  vehicle_km?: number;
  infeasible_assignments?: number;
  reserve_remaining?: number;
  replan_latency_s?: number | null;
};

export type PlanSnapshot = {
  version: number;
  parent_version?: number | null;
  created_at_t_s: number;
  trigger?: string;
  planner?: "ember" | "baseline" | "example";
  reserved?: string[];
  search?: unknown;
  assignments: Assignment[];
  changes?: PlanChange[];
  unresolved: Unresolved[];
  info_requests: InfoRequest[];
  metrics?: PlanMetrics;
};

export type Report = {
  id: string;
  source: string;
  kind: string;
  household_id?: number;
  facility_id?: string;
  assignment_id?: string;
  plan_version?: number | null;
  observed_at_t_s: number;
  confidence?: number;
  resolved?: boolean;
  text?: string;
  payload?: Record<string, unknown>;
};

export type ThreadRef = { household_id: number } | { facility_id: string };

export type Message = {
  id: string;
  thread: ThreadRef;
  direction: "in" | "out";
  text: string;
  t_s: number;
  plan_version?: number | null;
  assignment_id?: string | null;
  report_id?: string | null;
};

export type StateSnapshot = {
  version: string;
  scenario_id: string;
  t_s: number;
  plan_version: number | null;
  source?: "engine-example" | "simulator" | "backend";
  synthetic?: string[];
  hazard: {
    keyframe_t_s: number | null;
    geometry: FloodGeometry | null;
    next_keyframe_t_s: number | null;
    keyframe_times_s?: number[];
  };
  closures: Closure[];
  households: StateHousehold[];
  facilities: StateFacility[];
  resources: StateResource[];
  plan: PlanSnapshot | null;
  reports: Report[];
  messages: Message[];
  metrics: PlanMetrics;
};

export type Trajectories = {
  version: string;
  trips: { id: number; path: LngLat[]; t: number[]; final: number }[];
};

export type ComparisonMetric = {
  metric: string;
  label: string;
  better: "higher" | "lower";
  unit: string;
  baseline_mean: number;
  ember_mean: number;
  diff_mean: number;
  diff_min: number;
  diff_max: number;
  sentence: string;
};

export type EmberPlanVersion = {
  version: number;
  t_s: number;
  trigger: string;
  changes?: number;
  wall_s?: number;
};

export type Comparison = {
  version: string;
  scenario_id: string;
  headline: string[];
  notes: string[];
  nominal: { baseline: PlanMetrics; ember: PlanMetrics };
  plans: {
    baseline: { planner: string; assignments: number; rule?: string };
    ember: { planner: string; assignments: number; versions: EmberPlanVersion[] };
  };
  metrics: ComparisonMetric[];
};

/** One robustness run. Shape follows contracts/ws-events.schema.json on aryaman/ws-events and is provisional until Soham signs off. */
export type ScatterPoint = {
  runId: string;
  batchId: string;
  nTotal: number | null;
  planVersion: number | null;
  candidate: string;
  seed: number;
  peopleUnreached: number;
  overflowM3: number;
  chosen: boolean;
};

export type AssignmentEvent = {
  plan_version: number;
  change: PlanChange["change"];
  assignment_id: string;
  assignment: Assignment | null;
  note?: string;
};

export type Selection =
  | { kind: "household"; id: number }
  | { kind: "facility"; id: string }
  | { kind: "resource"; id: string }
  | { kind: "edge"; id: number };

export type JudgeClosure = {
  edge_id: number;
  closed_from_t_s: number;
};

export type FloodFeature = Feature<FloodGeometry, GeoJsonProperties>;

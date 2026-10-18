import type { Needs, PlanSnapshot, StateSnapshot, Target } from "./types";

export function formatSim(t: number): string {
  const s = Math.max(0, Math.round(t));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  const sec = s % 60;
  return `${m}m ${String(sec).padStart(2, "0")}s`;
}

export function formatMinutes(t: number | null | undefined): string {
  if (t == null || Number.isNaN(t)) return "—";
  return formatSim(t);
}

export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function formatNeeds(needs: Needs | unknown): string {
  if (needs == null) return "not recorded";
  if (typeof needs === "string") return needs;
  if (typeof needs !== "object") return String(needs);
  const record = needs as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof record.people === "number") parts.push(`${record.people} people`);
  if (record.mobility === true) parts.push("mobility need");
  if (record.accessible_vehicle === true) parts.push("accessible vehicle");
  if (record.medical === true) parts.push("medical");
  return parts.length > 0 ? parts.join(" · ") : JSON.stringify(needs);
}

export function targetLabel(target: Target): string {
  if ("household_id" in target) return `household #${target.household_id}`;
  return target.facility_id;
}

export function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

/** A phone handle for the projector: only its last 2 digits. */
export function maskHandle(handle: string): string {
  return `••${handle.replace(/\D/g, "").slice(-2)}`;
}

/** Wall seconds the planner took to produce this version. */
export function replanSeconds(plan: PlanSnapshot): number | null {
  const search = plan.search as { wall_s?: unknown } | undefined;
  return plan.metrics?.replan_latency_s ?? (typeof search?.wall_s === "number" ? search.wall_s : null);
}

/** One line for what a new plan version changed: "Van 2 rerouted · 3 households reassigned". */
export function planDiff(plan: PlanSnapshot, state: StateSnapshot): string {
  const byId = new Map(plan.assignments.map((assignment) => [assignment.id, assignment]));
  const name = (id: string) => state.resources.find((resource) => resource.id === id)?.name ?? id;
  const rerouted = new Set<string>();
  const sent: string[] = [];
  let reassigned = 0;
  let added = 0;
  let removed = 0;
  for (const change of plan.changes ?? []) {
    const assignment = byId.get(change.assignment_id);
    if (change.change === "removed") removed += 1;
    else if (!assignment) continue;
    else if (change.change === "eta_changed") rerouted.add(name(assignment.resource_id));
    else if ("facility_id" in assignment.target) {
      const id = assignment.target.facility_id;
      sent.push(`${name(assignment.resource_id)} → ${state.facilities.find((item) => item.id === id)?.name ?? id}`);
    } else if (change.change === "added") added += 1;
    else reassigned += 1;
  }
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts = [
    ...sent,
    ...(rerouted.size > 2 ? [count(rerouted.size, "vehicle", "vehicles") + " rerouted"] : [...rerouted].map((who) => `${who} rerouted`)),
    reassigned ? `${count(reassigned, "household", "households")} reassigned` : "",
    added ? `${count(added, "new pickup", "new pickups")}` : "",
    removed ? `${count(removed, "job", "jobs")} cancelled` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

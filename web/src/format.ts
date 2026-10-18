import { robustOf } from "./live";
import { targetName } from "./model";
import type { Needs, PlanSnapshot, RobustSummary, StateSnapshot, Target } from "./types";

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
  return status === "unknown" ? "reply needed" : status.replaceAll("_", " ");
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

/** Where the robust fan-out ran: "90 Daytona sandboxes", "8 local workers". */
export function poolLabel(robust: RobustSummary): string {
  return `${robust.workers ?? "?"} ${robust.pool === "daytona" ? "Daytona sandboxes" : `${robust.pool} workers`}`;
}

/** How a version was made: "replanned in 0.7 s", or after Optimize "robust pick · 250 worlds · 2.1 s on 90 Daytona sandboxes". */
export function planTiming(plan: PlanSnapshot): string {
  const robust = robustOf(plan);
  if (robust) return `robust pick · ${robust.jobs} worlds · ${robust.fanout_wall_s?.toFixed(1) ?? "?"} s on ${poolLabel(robust)}`;
  const seconds = replanSeconds(plan);
  return seconds == null ? "" : `replanned in ${seconds.toFixed(1)} s`;
}

/** What set a version off, in words: who texted what, else the fact reported, else the planner's trigger. */
export function planCause(plan: PlanSnapshot, state: StateSnapshot): string {
  const id = plan.trigger?.match(/\br-[0-9a-f]{6,}/)?.[0];
  const report = state.reports.find((item) => item.id === id);
  if (!report) return plan.trigger ?? "";
  const said = state.messages.find((message) => message.report_id === id);
  const target: Target | null = said?.thread ?? (report.household_id != null ? { household_id: report.household_id } : report.facility_id ? { facility_id: report.facility_id } : null);
  const who = target ? targetName(state, target) : "Report";
  return said ? `${who} texted “${said.text}”` : report.text ?? `${who}: ${formatNeeds(report.payload)}`;
}

/** A name without its spec in brackets: "Generator 1 (500 kW, camlock)" → "Generator 1". */
export function shortName(name: string): string {
  return name.replace(/ \([^)]*\)$/, "");
}

/** One line for what a new plan version changed: "Van 2 rerouted · 3 households reassigned". */
export function planDiff(plan: PlanSnapshot, state: StateSnapshot): string {
  const byId = new Map(plan.assignments.map((assignment) => [assignment.id, assignment]));
  const name = (id: string) => shortName(state.resources.find((resource) => resource.id === id)?.name ?? id);
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
      sent.push(`${name(assignment.resource_id)} → ${shortName(state.facilities.find((item) => item.id === id)?.name ?? id)}`);
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

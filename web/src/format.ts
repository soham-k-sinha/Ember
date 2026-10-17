import type { Needs, Target } from "./types";

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

export function targetKey(target: Target): string {
  if ("household_id" in target) return `household:${target.household_id}`;
  return `facility:${target.facility_id}`;
}

export function targetLabel(target: Target): string {
  if ("household_id" in target) return `household #${target.household_id}`;
  return target.facility_id;
}

export function threadKey(thread: Target): string {
  return targetKey(thread);
}

export function threadLabel(thread: Target): string {
  if ("household_id" in thread) return `Resident · household #${thread.household_id}`;
  return `Operator · ${thread.facility_id}`;
}

export function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

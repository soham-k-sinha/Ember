import type {
  Assignment,
  Comparison,
  Message,
  PlanMetrics,
  PlanSnapshot,
  Report,
  ScatterPoint,
  StateSnapshot,
} from "./types";

export type LiveStatus = "idle" | "connecting" | "live" | "error";

export type LiveEvent =
  | { type: "state"; state: StateSnapshot }
  | { type: "plan"; plan: PlanSnapshot }
  | { type: "assignment"; assignment: Assignment }
  | { type: "message"; message: Message }
  | { type: "report"; report: Report }
  | { type: "scatter_point"; point: ScatterPoint }
  | { type: "metrics"; metrics: PlanMetrics }
  | { type: "comparison"; comparison: Comparison }
  | { type: "ignore" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asState(value: unknown): StateSnapshot | null {
  if (!isRecord(value)) return null;
  if (!Array.isArray(value.households) || !Array.isArray(value.facilities)) return null;
  if (!Array.isArray(value.resources) || !Array.isArray(value.closures)) return null;
  if (typeof value.t_s !== "number") return null;
  return value as StateSnapshot;
}

function asComparison(value: unknown): Comparison | null {
  if (!isRecord(value) || !isRecord(value.baseline) || !isRecord(value.ember)) return null;
  return value as Comparison;
}

function asScatter(value: unknown): ScatterPoint | null {
  if (!isRecord(value)) return null;
  const metrics = isRecord(value.metrics) ? value.metrics : value;
  const people = metrics.people_unreached ?? metrics.peopleUnreached;
  const overflow = metrics.overflow_m3 ?? metrics.overflowM3;
  if (typeof people !== "number" || typeof overflow !== "number") return null;
  const planId = String(value.plan_id ?? value.planId ?? value.id ?? "plan");
  return {
    id: String(value.id ?? `${planId}:${people}:${overflow}`),
    planId,
    peopleUnreached: people,
    overflowM3: overflow,
    chosen: Boolean(value.chosen ?? value.selected),
  };
}

export function parseLiveEvent(payload: unknown): LiveEvent {
  if (!isRecord(payload)) return { type: "ignore" };
  const name = String(payload.type ?? payload.event ?? payload.kind ?? "");
  const body = payload.data ?? payload.payload ?? payload;
  if (name === "state" || (!name && asState(body))) {
    const state = asState(name ? body : payload);
    return state ? { type: "state", state } : { type: "ignore" };
  }
  if (name === "plan" && isRecord(body) && Array.isArray(body.assignments)) {
    return { type: "plan", plan: body as PlanSnapshot };
  }
  if (name === "assignment" && isRecord(body) && typeof body.id === "string") {
    return { type: "assignment", assignment: body as Assignment };
  }
  if (name === "message" && isRecord(body) && typeof body.text === "string") {
    return { type: "message", message: body as Message };
  }
  if (name === "report" && isRecord(body) && typeof body.id === "string") {
    return { type: "report", report: body as Report };
  }
  if (name === "scatter_point") {
    const point = asScatter(body);
    return point ? { type: "scatter_point", point } : { type: "ignore" };
  }
  if (name === "metrics" && isRecord(body)) return { type: "metrics", metrics: body as PlanMetrics };
  if (name === "comparison") {
    const comparison = asComparison(body);
    return comparison ? { type: "comparison", comparison } : { type: "ignore" };
  }
  const comparison = asComparison(payload);
  if (comparison) return { type: "comparison", comparison };
  return { type: "ignore" };
}

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  const trimmed = text.trim();
  return trimmed ? `${response.status} ${trimmed.slice(0, 280)}` : `${response.status} ${response.statusText}`;
}

export async function getJson(url: string): Promise<unknown> {
  const response = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<unknown>;
}

export async function postJson(url: string, body: unknown): Promise<unknown> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error(await readError(response));
  const text = await response.text();
  if (!text) return null;
  return JSON.parse(text) as unknown;
}

export function openSocket(
  apiBase: string,
  onEvent: (event: LiveEvent) => void,
  onStatus: (status: LiveStatus, detail?: string) => void,
): () => void {
  let stopped = false;
  let socket: WebSocket | null = null;
  let retry = 0;
  let timer = 0;

  const connect = () => {
    if (stopped) return;
    onStatus("connecting");
    const wsBase = apiBase.replace(/^http/i, "ws").replace(/\/$/, "");
    socket = new WebSocket(`${wsBase}/ws`);
    socket.onopen = () => {
      retry = 0;
      onStatus("live");
    };
    socket.onmessage = (message) => {
      try {
        onEvent(parseLiveEvent(JSON.parse(String(message.data)) as unknown));
      } catch {
        onStatus("error", "The backend sent a message that was not JSON.");
      }
    };
    socket.onerror = () => {
      onStatus("error", "WebSocket connection failed.");
    };
    socket.onclose = () => {
      if (stopped) return;
      retry += 1;
      onStatus("error", "WebSocket closed. Reconnecting.");
      timer = window.setTimeout(connect, Math.min(8000, 1000 * retry));
    };
  };

  connect();
  return () => {
    stopped = true;
    window.clearTimeout(timer);
    socket?.close();
  };
}

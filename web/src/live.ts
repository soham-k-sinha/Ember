import type {
  AssignmentEvent,
  Comparison,
  Message,
  PlanMetrics,
  PlanSnapshot,
  Report,
  RobustSummary,
  ScatterPoint,
  StateSnapshot,
} from "./types";

export type LiveStatus = "idle" | "connecting" | "live" | "error";

export type LiveEvent =
  | { type: "state"; state: StateSnapshot }
  | { type: "plan"; plan: PlanSnapshot }
  | { type: "assignment"; event: AssignmentEvent }
  | { type: "message"; message: Message }
  | { type: "report"; report: Report }
  | { type: "scatter_point"; point: ScatterPoint }
  | { type: "metrics"; metrics: PlanMetrics }
  | { type: "ignore" };

const EVENT_TYPES = new Set([
  "state",
  "plan",
  "assignment",
  "message",
  "report",
  "scatter_point",
  "metrics",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asState(value: unknown): StateSnapshot | null {
  if (!isRecord(value)) return null;
  if (!Array.isArray(value.households) || !Array.isArray(value.facilities)) return null;
  if (!Array.isArray(value.resources) || !Array.isArray(value.closures)) return null;
  if (typeof value.t_s !== "number") return null;
  return value as StateSnapshot;
}

export function robustOf(plan: { search?: unknown } | null | undefined): RobustSummary | null {
  const search = plan?.search;
  if (!isRecord(search) || !isRecord(search.robust)) return null;
  const robust = search.robust;
  if (typeof robust.chosen !== "string" || typeof robust.batch_id !== "string") return null;
  return robust as RobustSummary;
}

export function asComparison(value: unknown): Comparison | null {
  if (!isRecord(value) || !isRecord(value.nominal)) return null;
  const nominal = value.nominal;
  if (!isRecord(nominal) || !isRecord(nominal.baseline) || !isRecord(nominal.ember)) return null;
  if (!Array.isArray(value.metrics) || !Array.isArray(value.headline)) return null;
  return value as Comparison;
}

function asScatter(value: unknown): ScatterPoint | null {
  if (!isRecord(value) || !isRecord(value.metrics)) return null;
  const metrics = value.metrics;
  if (typeof metrics.people_unreached !== "number" || typeof metrics.overflow_m3 !== "number") return null;
  if (typeof value.run_id !== "string" || typeof value.batch_id !== "string") return null;
  if (typeof value.candidate !== "string" || typeof value.seed !== "number") return null;
  return {
    runId: value.run_id,
    batchId: value.batch_id,
    nTotal: typeof value.n_total === "number" ? value.n_total : null,
    planVersion: typeof value.plan_version === "number" ? value.plan_version : null,
    candidate: value.candidate,
    seed: value.seed,
    peopleUnreached: metrics.people_unreached,
    overflowM3: metrics.overflow_m3,
    chosen: value.candidate === "ember",
  };
}

function asAssignmentEvent(value: unknown): AssignmentEvent | null {
  if (!isRecord(value)) return null;
  if (typeof value.plan_version !== "number" || typeof value.assignment_id !== "string") return null;
  if (typeof value.change !== "string") return null;
  if (value.assignment !== null && !isRecord(value.assignment)) return null;
  return value as AssignmentEvent;
}

function eventFrom(type: string, data: unknown): LiveEvent | null {
  if (type === "state") {
    const state = asState(data);
    return state ? { type: "state", state } : null;
  }
  if (type === "plan" && isRecord(data) && Array.isArray(data.assignments)) {
    return { type: "plan", plan: data as PlanSnapshot };
  }
  if (type === "assignment") {
    const event = asAssignmentEvent(data);
    return event ? { type: "assignment", event } : null;
  }
  if (type === "message" && isRecord(data) && typeof data.text === "string") {
    return { type: "message", message: data as Message };
  }
  if (type === "report" && isRecord(data) && typeof data.id === "string") {
    return { type: "report", report: data as Report };
  }
  if (type === "scatter_point") {
    const point = asScatter(data);
    return point ? { type: "scatter_point", point } : null;
  }
  if (type === "metrics" && isRecord(data)) return { type: "metrics", metrics: data as PlanMetrics };
  return null;
}

/** Envelope from contracts/ws-events.schema.json. Not residents/ws-events.schema.json. */
export type Envelope =
  | { kind: "invalid" }
  | { kind: "envelope"; seq: number; t_s: number; event: LiveEvent | null };

export function readEnvelope(payload: unknown): Envelope {
  if (!isRecord(payload)) return { kind: "invalid" };
  if (!EVENT_TYPES.has(String(payload.type))) return { kind: "invalid" };
  if (typeof payload.seq !== "number" || typeof payload.t_s !== "number" || !("data" in payload)) {
    return { kind: "invalid" };
  }
  return {
    kind: "envelope",
    seq: payload.seq,
    t_s: payload.t_s,
    event: eventFrom(String(payload.type), payload.data),
  };
}

export function scatterFromEnvelopes(events: unknown[]): ScatterPoint[] {
  if (!Array.isArray(events)) return [];
  const points: ScatterPoint[] = [];
  for (const raw of events) {
    const envelope = readEnvelope(raw);
    if (envelope.kind === "envelope" && envelope.event?.type === "scatter_point") {
      points.push(envelope.event.point);
    }
  }
  return points;
}

/** null expected means this is the first envelope on the connection and any seq is the baseline. */
export function seqDecision(expected: number | null, seq: number): "accept" | "duplicate" | "gap" {
  if (expected === null || seq === expected) return "accept";
  if (seq < expected) return "duplicate";
  return "gap";
}

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  const trimmed = text.trim();
  return trimmed ? `${response.status} ${trimmed.slice(0, 280)}` : `${response.status} ${response.statusText}`;
}

export async function getJson(url: string, timeoutMs = 8000): Promise<unknown> {
  const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<unknown>;
}

export async function postJson(url: string, body: unknown, timeoutMs = 8000): Promise<unknown> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
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
  onGap: () => Promise<void> | void,
): () => void {
  let stopped = false;
  let recovering = false;
  let socket: WebSocket | null = null;
  let retry = 0;
  let timer = 0;
  let expected: number | null = null;

  const connect = () => {
    if (stopped) return;
    expected = null;
    recovering = false;
    onStatus("connecting");
    const wsBase = apiBase.replace(/^http/i, "ws").replace(/\/$/, "");
    socket = new WebSocket(`${wsBase}/ws`);
    socket.onopen = () => {
      retry = 0;
      onStatus("live");
    };
    socket.onmessage = (message) => {
      if (recovering) return;
      let payload: unknown;
      try {
        payload = JSON.parse(String(message.data)) as unknown;
      } catch {
        onStatus("error", "The backend sent a message that was not JSON.");
        return;
      }
      const envelope = readEnvelope(payload);
      if (envelope.kind === "invalid") return;
      const decision = seqDecision(expected, envelope.seq);
      if (decision === "duplicate") return;
      if (decision === "gap") {
        recovering = true;
        onStatus("error", `Sequence skipped at ${envelope.seq}. Reloading GET /state.`);
        socket?.close();
        void Promise.resolve(onGap()).finally(() => {
          if (!stopped) connect();
        });
        return;
      }
      expected = envelope.seq + 1;
      if (envelope.event && envelope.event.type !== "ignore") onEvent(envelope.event);
    };
    socket.onerror = () => {
      onStatus("error", "WebSocket connection failed.");
    };
    socket.onclose = () => {
      if (stopped || recovering) return;
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

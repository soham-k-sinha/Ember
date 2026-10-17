import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { MapView, perf } from "./components/MapView";
import { Panels, snapshotNote, type PanelId } from "./components/Panels";
import {
  API_BASE,
  fixturePlaybacks,
  publishedComparison,
  publishedScatter,
  publishedState,
  scenario,
  town,
} from "./fixtures";
import type { LegendMode } from "./layers";
import { buildGraph, planWalkers, type BgHousehold } from "./people";
import { asPlayback, stateFromPlayback, type Playback } from "./playback";
import { loadFullTown, type FullTown } from "./townFull";
import { formatSim } from "./format";
import { asComparison, asState, getJson, openSocket, postJson, robustOf, type LiveStatus } from "./live";
import { activeKeyframe, closedEdges } from "./model";
import type {
  AssignmentEvent,
  Comparison,
  JudgeClosure,
  Message,
  PlanMetrics,
  PlanSnapshot,
  Report,
  ScatterPoint,
  Selection,
  StateSnapshot,
} from "./types";

type Mode = "fixture" | "live";
type Replay = "ember" | "baseline";

const SPEEDS = [10, 30, 60, 180, 600];

type Model = {
  mode: Mode;
  apiBase: string;
  liveStatus: LiveStatus;
  liveDetail: string | null;
  snapshot: StateSnapshot;
  previous: StateSnapshot | null;
  clock: number;
  playing: boolean;
  speed: number;
  comparison: Comparison | null;
  scatter: ScatterPoint[];
  scatterBatch: string | null;
  scatterTotal: number | null;
  plans: PlanSnapshot[];
  judge: JudgeClosure[];
  selection: Selection | null;
  notice: string | null;
  showHouseholds: boolean;
  showTrips: boolean;
  busy: string | null;
  tab: PanelId;
  legend: LegendMode;
  follow: Selection | null;
  replay: Replay;
  playbacks: { ember: Playback | null; baseline: Playback | null };
  playbackNote: string | null;
  showWalkers: boolean;
};

type Action =
  | { type: "tick"; dt: number }
  | { type: "clock"; t: number }
  | { type: "playing"; playing: boolean }
  | { type: "speed"; speed: number }
  | { type: "mode"; mode: Mode }
  | { type: "api"; apiBase: string }
  | { type: "live-status"; status: LiveStatus; detail?: string | null }
  | { type: "state"; state: StateSnapshot }
  | { type: "plan"; plan: PlanSnapshot }
  | { type: "comparison"; comparison: Comparison }
  | { type: "scatter"; point: ScatterPoint }
  | { type: "assignment"; event: AssignmentEvent }
  | { type: "message"; message: Message }
  | { type: "report"; report: Report }
  | { type: "metrics"; metrics: PlanMetrics }
  | { type: "select"; selection: Selection | null }
  | { type: "notice"; notice: string | null }
  | { type: "busy"; busy: string | null }
  | { type: "tab"; tab: PanelId }
  | { type: "households" }
  | { type: "walkers" }
  | { type: "legend"; legend: LegendMode }
  | { type: "follow"; follow: Selection | null }
  | { type: "replay"; replay: Replay }
  | { type: "playback"; planner: Replay; playback: Playback | null; note?: string | null }
  | { type: "trips" }
  | { type: "close"; edgeId: number; t: number }
  | { type: "undo"; edgeId: number };

function isRecordVersion(value: unknown): number | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const version = (value as { plan_version?: unknown }).plan_version;
  return typeof version === "number" ? version : null;
}

function planFromBody(value: unknown): PlanSnapshot | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.version !== "number" || !Array.isArray(record.assignments)) return null;
  if (Array.isArray(record.households)) return null;
  return value as PlanSnapshot;
}

function withPlan(plans: PlanSnapshot[], plan: PlanSnapshot | null): PlanSnapshot[] {
  if (!plan) return plans;
  if (plans.some((item) => item.version === plan.version)) {
    return plans.map((item) => (item.version === plan.version ? plan : item));
  }
  return [...plans, plan];
}

function reducer(state: Model, action: Action): Model {
  switch (action.type) {
    case "tick": {
      const next = Math.min(scenario.t_end_s, state.clock + action.dt * state.speed);
      return { ...state, clock: next, playing: next < scenario.t_end_s && state.playing };
    }
    case "clock":
      return { ...state, clock: Math.min(scenario.t_end_s, Math.max(0, action.t)) };
    case "playing":
      return { ...state, playing: action.playing };
    case "speed":
      return { ...state, speed: action.speed };
    case "mode":
      if (action.mode === "fixture") {
        return {
          ...state,
          mode: "fixture",
          liveStatus: "idle",
          liveDetail: null,
          snapshot: publishedState,
          previous: null,
          clock: 0,
          plans: withPlan([], publishedState.plan),
          comparison: publishedComparison,
          scatter: publishedScatter,
          scatterBatch: publishedScatter[0]?.batchId ?? null,
          scatterTotal: publishedScatter[0]?.nTotal ?? null,
          notice: "Fixture mode: allston_flood_v1 replayed end to end from the engine (contracts/fixtures/playback*.json). Press Play.",
          playbacks: { ...fixturePlaybacks },
          playbackNote: null,
        };
      }
      return {
        ...state,
        mode: "live",
        scatter: [],
        scatterBatch: null,
        scatterTotal: null,
        notice: null,
        playbacks: { ember: null, baseline: null },
        playbackNote: null,
      };
    case "api":
      return { ...state, apiBase: action.apiBase };
    case "live-status":
      return {
        ...state,
        liveStatus: action.status,
        liveDetail: action.detail === undefined ? state.liveDetail : action.detail,
      };
    case "state": {
      const previous = action.state.t_s === state.snapshot.t_s ? state.previous : state.snapshot;
      const follow = state.mode === "live" && state.playing;
      return {
        ...state,
        snapshot: action.state,
        previous,
        plans: withPlan(state.plans, action.state.plan),
        clock: follow ? state.clock : action.state.t_s,
      };
    }
    case "plan":
      return {
        ...state,
        plans: withPlan(state.plans, action.plan),
        snapshot: state.snapshot.plan_version === action.plan.version || state.snapshot.plan == null
          ? { ...state.snapshot, plan: action.plan, plan_version: action.plan.version }
          : state.snapshot,
      };
    case "comparison":
      return { ...state, comparison: action.comparison, tab: "compare" };
    case "scatter": {
      const sameBatch = state.scatterBatch === action.point.batchId;
      const existing = sameBatch ? state.scatter : [];
      if (existing.some((point) => point.runId === action.point.runId)) return state;
      return {
        ...state,
        scatterBatch: action.point.batchId,
        scatterTotal: action.point.nTotal ?? state.scatterTotal,
        scatter: [...existing, action.point],
      };
    }
    case "assignment": {
      if (!state.snapshot.plan) return state;
      const incoming = action.event;
      const kept = state.snapshot.plan.assignments.filter((item) => item.id !== incoming.assignment_id);
      const assignments = incoming.assignment == null || incoming.change === "removed"
        ? kept
        : [...kept, incoming.assignment];
      const changes = [
        ...(state.snapshot.plan.changes ?? []).filter(
          (change) => !(change.assignment_id === incoming.assignment_id && change.change === incoming.change),
        ),
        { assignment_id: incoming.assignment_id, change: incoming.change, note: incoming.note },
      ];
      const plan = {
        ...state.snapshot.plan,
        version: incoming.plan_version,
        assignments,
        changes,
      };
      return {
        ...state,
        snapshot: { ...state.snapshot, plan, plan_version: plan.version },
        plans: withPlan(state.plans, plan),
      };
    }
    case "message":
      return {
        ...state,
        snapshot: { ...state.snapshot, messages: [...state.snapshot.messages, action.message] },
      };
    case "report":
      return {
        ...state,
        snapshot: { ...state.snapshot, reports: [...state.snapshot.reports, action.report] },
      };
    case "metrics":
      return {
        ...state,
        snapshot: { ...state.snapshot, metrics: { ...state.snapshot.metrics, ...action.metrics } },
      };
    case "select":
      return {
        ...state,
        selection: action.selection,
        tab: action.selection ? "inspector" : state.tab,
        follow: action.selection && state.follow && (action.selection.kind !== state.follow.kind || action.selection.id !== state.follow.id) ? null : state.follow,
      };
    case "notice":
      return { ...state, notice: action.notice };
    case "busy":
      return { ...state, busy: action.busy };
    case "tab":
      return { ...state, tab: action.tab };
    case "households":
      return { ...state, showHouseholds: !state.showHouseholds };
    case "walkers":
      return { ...state, showWalkers: !state.showWalkers };
    case "legend":
      return { ...state, legend: action.legend };
    case "follow":
      return { ...state, follow: action.follow, selection: action.follow ?? state.selection };
    case "replay":
      return { ...state, replay: action.replay };
    case "playback":
      return {
        ...state,
        playbacks: { ...state.playbacks, [action.planner]: action.playback },
        playbackNote: action.note === undefined ? state.playbackNote : action.note,
      };
    case "trips":
      return { ...state, showTrips: !state.showTrips };
    case "close":
      if (state.judge.some((item) => item.edge_id === action.edgeId)) return state;
      return {
        ...state,
        judge: [...state.judge, { edge_id: action.edgeId, closed_from_t_s: action.t }],
      };
    case "undo":
      return { ...state, judge: state.judge.filter((item) => item.edge_id !== action.edgeId) };
    default:
      return state;
  }
}

const initial: Model = {
  mode: "fixture",
  apiBase: API_BASE,
  liveStatus: "idle",
  liveDetail: null,
  snapshot: publishedState,
  previous: null,
  clock: 0,
  playing: false,
  speed: 30,
  comparison: publishedComparison,
  scatter: publishedScatter,
  scatterBatch: publishedScatter[0]?.batchId ?? null,
  scatterTotal: publishedScatter[0]?.nTotal ?? null,
  plans: withPlan([], publishedState.plan),
  judge: [],
  selection: null,
  notice: "Fixture mode: allston_flood_v1 replayed end to end from the engine. Press Play, or jump to Judge's corner.",
  showHouseholds: true,
  showTrips: false,
  busy: null,
  tab: "ledger",
  legend: "status",
  follow: null,
  replay: "ember",
  playbacks: { ...fixturePlaybacks },
  playbackNote: null,
  showWalkers: true,
};

export function App() {
  const [model, dispatch] = useReducer(reducer, initial);
  if (import.meta.env.DEV) (window as unknown as { __clock?: (t: number, playing?: boolean) => void }).__clock = (t, playing = false) => {
    dispatch({ type: "playing", playing });
    dispatch({ type: "clock", t });
  };
  const playback = model.playbacks[model.replay];
  const replaying = playback != null && playback.scenario_id === model.snapshot.scenario_id;
  // the picture at the clock: the replay over the base snapshot, or the snapshot itself
  const display = useMemo(
    () => perf("display", () => (replaying && playback ? stateFromPlayback(playback, model.snapshot, model.clock) : model.snapshot)),
    [replaying, playback, model.snapshot, model.clock],
  );
  const closures = useMemo(
    () => perf("closures", () => closedEdges(display, model.clock, model.judge)),
    [display, model.clock, model.judge],
  );

  // every household (full shared town) for lit homes and the walking crowd; the fixture's 1-in-12 sample until it loads
  const [fullTown, setFullTown] = useState<FullTown | null>(null);
  useEffect(() => {
    let alive = true;
    void loadFullTown().then((loaded) => {
      if (alive) setFullTown(loaded);
    });
    return () => {
      alive = false;
    };
  }, []);
  const background: BgHousehold[] = useMemo(
    () => fullTown?.households ?? (town.households as BgHousehold[]),
    [fullTown],
  );
  const backgroundById = useMemo(() => new Map(background.map((household) => [household.id, household])), [background]);
  const graph = useMemo(
    () => buildGraph(town.nodes, town.edges, scenario.hazard.keyframes, playback?.closures),
    [playback],
  );
  const shelterNode = model.snapshot.facilities.find((facility) => facility.type === "shelter")?.node ?? null;
  const assistedKey = model.snapshot.households.map((household) => household.household_id).join(",");
  const walkers = useMemo(
    () =>
      planWalkers({
        households: background,
        assisted: new Set(model.snapshot.households.map((household) => household.household_id)),
        graph,
        shelterNode,
        exitNodes: fullTown?.exits ?? ((town as unknown as { exits?: number[] }).exits ?? []),
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [background, graph, shelterNode, assistedKey, fullTown],
  );
  const frame = model.snapshot.scenario_id === scenario.scenario_id ? activeKeyframe(model.clock) : null;
  const awayFromSnapshot = Math.abs(model.clock - model.snapshot.t_s) > 30;

  useEffect(() => {
    if (!model.playing) return;
    let frameId = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      dispatch({ type: "tick", dt });
      frameId = requestAnimationFrame(step);
    };
    frameId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameId);
  }, [model.playing]);

  useEffect(() => {
    if (model.mode !== "live") return;
    let stop = () => {};
    let cancelled = false;
    const run = async () => {
      dispatch({ type: "live-status", status: "connecting", detail: null });
      try {
        const body = await getJson(`${model.apiBase.replace(/\/$/, "")}/state`);
        const snapshot = asState(body);
        if (!cancelled && snapshot) {
          dispatch({ type: "state", state: snapshot });
          dispatch({
            type: "live-status",
            status: "connecting",
            detail: `state v${snapshot.version} · ${snapshot.scenario_id}`,
          });
        }
        if (!cancelled && !snapshot) {
          dispatch({
            type: "live-status",
            status: "error",
            detail: "GET /state did not return a state snapshot. Showing the last good picture.",
          });
        }
      } catch (error) {
        if (!cancelled) {
          dispatch({
            type: "live-status",
            status: "error",
            detail: error instanceof Error ? error.message : "GET /state failed.",
          });
        }
      }
      if (cancelled) return;
      // The backend broadcasts `plan` after a replan but not always a fresh `state`, so closed roads and
      // vehicle ETAs would stay stale; refetch GET /state shortly after a plan unless a `state` event lands.
      let refetch: number | undefined;
      const refetchState = async () => {
        refetch = undefined;
        try {
          const snapshot = asState(await getJson(`${model.apiBase.replace(/\/$/, "")}/state`));
          if (!cancelled && snapshot) dispatch({ type: "state", state: snapshot });
        } catch {
          // keep the last good picture; the socket status already reports connectivity
        }
      };
      const closeSocket = openSocket(
        model.apiBase,
        (event) => {
          if (event.type === "state") {
            window.clearTimeout(refetch);
            refetch = undefined;
            dispatch({ type: "state", state: event.state });
          } else if (event.type === "plan") {
            dispatch({ type: "plan", plan: event.plan });
            window.clearTimeout(refetch);
            refetch = window.setTimeout(() => void refetchState(), 300);
          } else if (event.type === "scatter_point") dispatch({ type: "scatter", point: event.point });
          else if (event.type === "assignment") dispatch({ type: "assignment", event: event.event });
          else if (event.type === "message") dispatch({ type: "message", message: event.message });
          else if (event.type === "report") dispatch({ type: "report", report: event.report });
          else if (event.type === "metrics") dispatch({ type: "metrics", metrics: event.metrics });
        },
        (status, detail) => dispatch({ type: "live-status", status, detail }),
        async () => {
          const body = await getJson(`${model.apiBase.replace(/\/$/, "")}/state`);
          const snapshot = asState(body);
          if (snapshot) dispatch({ type: "state", state: snapshot });
          else throw new Error("GET /state did not return a state snapshot.");
        },
      );
      stop = () => {
        window.clearTimeout(refetch);
        closeSocket();
      };
    };
    void run();
    return () => {
      cancelled = true;
      stop();
    };
  }, [model.mode, model.apiBase]);

  // live: fetch the replay of the current plan (and the baseline when asked) after every new plan version
  const livePlanVersion = model.mode === "live" ? model.snapshot.plan?.version ?? model.snapshot.plan_version : null;
  useEffect(() => {
    if (model.mode !== "live" || livePlanVersion == null) return;
    let cancelled = false;
    const root = model.apiBase.replace(/\/$/, "");
    const planners: Replay[] = model.replay === "baseline" ? ["ember", "baseline"] : ["ember"];
    for (const planner of planners) {
      getJson(`${root}/playback?planner=${planner}`, 30000)
        .then((body) => {
          if (cancelled) return;
          const pb = asPlayback(body);
          dispatch({ type: "playback", planner, playback: pb, note: pb ? null : "GET /playback returned no replay; vehicles move between snapshots." });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          dispatch({
            type: "playback",
            planner,
            playback: null,
            note: `Live replay unavailable (${error instanceof Error ? error.message : "GET /playback failed"}); vehicles move between snapshots.`,
          });
        });
    }
    return () => {
      cancelled = true;
    };
  }, [model.mode, model.apiBase, livePlanVersion, model.replay]);

  const clockRef = useRef(model.clock);
  clockRef.current = model.clock;
  const apiRef = useRef(model.apiBase);
  apiRef.current = model.apiBase;
  const modeRef = useRef(model.mode);
  modeRef.current = model.mode;
  const serverClock = useRef<number | null>(null);

  useEffect(() => {
    serverClock.current = model.mode === "live" ? model.snapshot.t_s : null;
  }, [model.mode, model.snapshot]);

  useEffect(() => {
    if (model.mode !== "live" || model.playing) return;
    if (serverClock.current == null) return;
    if (Math.abs(model.clock - serverClock.current) < 1) return;
    const handle = window.setTimeout(() => {
      void pushClock(apiRef.current, clockRef.current);
    }, 400);
    return () => window.clearTimeout(handle);
  }, [model.mode, model.playing, model.clock]);

  useEffect(() => {
    if (model.mode !== "live" || !model.playing) return;
    const handle = window.setInterval(() => {
      if (serverClock.current == null) return;
      void pushClock(apiRef.current, clockRef.current);
    }, 1200);
    return () => window.clearInterval(handle);
  }, [model.mode, model.playing]);

  async function pushClock(apiBase: string, t: number) {
    if (modeRef.current !== "live") return;
    try {
      await postJson(`${apiBase.replace(/\/$/, "")}/clock`, { t_s: t }, 20000);
    } catch (error) {
      dispatch({
        type: "notice",
        notice: error instanceof Error ? `Clock failed: ${error.message}` : "Clock failed.",
      });
    }
  }

  async function closeRoad(edgeId: number) {
    dispatch({ type: "close", edgeId, t: model.clock });
    if (model.mode !== "live") {
      dispatch({
        type: "notice",
        notice: "Fixture mode kept this closure on the map. Live mode also POSTs /disruption.",
      });
      return;
    }
    dispatch({ type: "busy", busy: "close" });
    try {
      const root = model.apiBase.replace(/\/$/, "");
      await postJson(`${root}/disruption`, { close_edges: [edgeId] }, 30000);
      const body = await getJson(`${root}/state`);
      const snapshot = asState(body);
      if (snapshot) dispatch({ type: "state", state: snapshot });
      dispatch({ type: "notice", notice: `POST /disruption closed edge ${edgeId} (both directions).` });
    } catch (error) {
      dispatch({
        type: "notice",
        notice: error instanceof Error ? `Close failed: ${error.message}` : "Close failed.",
      });
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  async function replan() {
    if (model.mode !== "live") {
      dispatch({ type: "notice", notice: "Replan needs the backend. Switch to live, then try again." });
      dispatch({ type: "tab", tab: "plans" });
      return;
    }
    dispatch({ type: "busy", busy: "replan" });
    try {
      const root = model.apiBase.replace(/\/$/, "");
      const body = await postJson(`${root}/replan`, {}, 30000);
      const plan = planFromBody(body);
      if (plan) dispatch({ type: "plan", plan });
      const snapshot = asState(await getJson(`${root}/state`));
      if (snapshot) dispatch({ type: "state", state: snapshot });
      const version = isRecordVersion(body);
      dispatch({
        type: "notice",
        notice: version == null ? "POST /replan returned." : `POST /replan returned plan v${version}.`,
      });
    } catch (error) {
      dispatch({
        type: "notice",
        notice: error instanceof Error ? `Replan failed: ${error.message}` : "Replan failed.",
      });
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  async function optimize() {
    if (model.mode !== "live") {
      dispatch({ type: "notice", notice: "Optimize runs on the backend (Daytona or the local pool). Switch to Live first." });
      dispatch({ type: "tab", tab: "scatter" });
      return;
    }
    dispatch({ type: "busy", busy: "optimize" });
    dispatch({ type: "tab", tab: "scatter" });
    const root = model.apiBase.replace(/\/$/, "");
    try {
      try {
        await postJson(`${root}/optimize?seeds=20&k=4`, {}, 15000);
      } catch (error) {
        // 409 = one is already running: watch that one instead of failing
        if (!(error instanceof Error && error.message.startsWith("409"))) throw error;
      }
      const deadline = Date.now() + 300_000;
      let last: unknown = null;
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const body = await getJson(`${root}/optimize`);
        if (typeof body === "object" && body !== null && (body as { running?: unknown }).running === false) {
          last = (body as { last?: unknown }).last ?? null;
          break;
        }
        if (Date.now() > deadline) throw new Error("still running after 5 min");
      }
      const snapshot = asState(await getJson(`${root}/state`));
      if (snapshot) dispatch({ type: "state", state: snapshot });
      const robust = robustOf(snapshot?.plan) ?? null;
      const error = typeof last === "object" && last !== null ? (last as { error?: unknown }).error : undefined;
      dispatch({
        type: "notice",
        notice: typeof error === "string"
          ? `Optimize failed: ${error}`
          : robust
            ? `${robust.jobs} runs on ${robust.pool}${robust.workers ? ` (${robust.workers} workers)` : ""}` +
              `${robust.fanout_wall_s != null ? ` in ${robust.fanout_wall_s.toFixed(1)} s` : ""}. ` +
              (robust.chosen !== robust.nominal_best
                ? `Chose ${robust.chosen} over the nominal best ${robust.nominal_best}: better in the worst 20% of worlds.`
                : `Kept ${robust.chosen}: the nominal best is also the most robust.`)
            : "Optimize finished.",
      });
    } catch (error) {
      dispatch({
        type: "notice",
        notice: error instanceof Error ? `Optimize failed: ${error.message}` : "Optimize failed.",
      });
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  async function compare() {
    if (model.mode !== "live") {
      dispatch({
        type: "notice",
        notice: "The table is the published comparison fixture. Live mode refreshes it from GET /comparison.",
      });
      dispatch({ type: "tab", tab: "compare" });
      return;
    }
    dispatch({ type: "busy", busy: "compare" });
    const root = model.apiBase.replace(/\/$/, "");
    try {
      const body = await getJson(`${root}/comparison?seeds=5`, 90000);
      const comparison = asComparison(body);
      if (!comparison) throw new Error("GET /comparison did not include nominal.baseline and nominal.ember.");
      dispatch({ type: "comparison", comparison });
      dispatch({
        type: "notice",
        notice: `Comparison loaded for ${comparison.scenario_id}. B − A is EMBER minus baseline. Spread, not confidence bounds.`,
      });
    } catch (error) {
      dispatch({
        type: "notice",
        notice: error instanceof Error ? `Comparison failed: ${error.message}` : "Comparison failed.",
      });
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  // KPIs show what the current plan is projected to achieve over the whole horizon; "so far" is the outcome at the clock
  const soFar = display.metrics;
  const projected = display.plan?.metrics;
  const metrics = projected ?? soFar;
  const planVersion = display.plan?.version ?? display.plan_version;
  const hospital = display.facilities.find((facility) => facility.type === "hospital");

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <p className="kicker">Ember</p>
          <h1>Allston flood</h1>
          <p className="meta">{snapshotNote(model.snapshot)}</p>
        </div>
        <div className="clock">
          <button className="primary" onClick={() => dispatch({ type: "playing", playing: !model.playing })}>
            {model.playing ? "Pause" : "Play"}
          </button>
          <label className="scrub">
            <span>{formatSim(model.clock)}</span>
            <input
              type="range"
              min={0}
              max={scenario.t_end_s}
              step={scenario.tick_s ?? 60}
              value={model.clock}
              onChange={(event) => dispatch({ type: "clock", t: Number(event.target.value) })}
            />
          </label>
          <div className="segmented small" role="group" aria-label="Speed">
            {SPEEDS.map((speed) => (
              <button key={speed} className={model.speed === speed ? "on" : ""} onClick={() => dispatch({ type: "speed", speed })}>
                {speed}×
              </button>
            ))}
          </div>
          <p className="meta">{frame ? frame.label ?? `Keyframe ${formatSim(frame.t_s)}` : "Dry"}</p>
        </div>
        <div className="mode">
          <div className="segmented" role="group" aria-label="Plan replayed on the map">
            <button className={model.replay === "ember" ? "on" : ""} onClick={() => dispatch({ type: "replay", replay: "ember" })}>
              EMBER plan
            </button>
            <button className={model.replay === "baseline" ? "on baseline" : ""} onClick={() => dispatch({ type: "replay", replay: "baseline" })}>
              Baseline
            </button>
          </div>
          <p className={`meta ${replaying ? "live-live" : ""}`}>
            {replaying
              ? `● Replaying ${playback?.planner === "baseline" ? "the baseline" : `plan v${playback?.plan_version ?? "?"}`}`
              : model.playbackNote ?? "Snapshots only"}
          </p>
          <div className="segmented" role="group" aria-label="Data source">
            <button
              className={model.mode === "fixture" ? "on" : ""}
              onClick={() => dispatch({ type: "mode", mode: "fixture" })}
            >
              Fixtures
            </button>
            <button
              className={model.mode === "live" ? "on" : ""}
              onClick={() => dispatch({ type: "mode", mode: "live" })}
            >
              Live
            </button>
          </div>
          <p className={`meta live-${model.liveStatus}`}>
            {model.mode === "fixture"
              ? "No backend"
              : model.liveDetail ?? model.liveStatus}
          </p>
        </div>
      </header>
      <section className="kpis" aria-label="Plan metrics">
        <p className="kpi-caption">
          <span>{projected ? "Projected" : "So far"}</span>
          <strong>plan v{planVersion ?? "—"}</strong>
        </p>
        <Kpi
          label="Reached by deadline"
          value={metrics?.people_reached_before_deadline}
          sub={projected && soFar ? `${soFar.people_reached_before_deadline ?? 0} so far` : undefined}
        />
        <Kpi label="Not reached" value={metrics?.people_unreached} tone={(metrics?.people_unreached ?? 0) > 0 ? "bad" : undefined} />
        <Kpi label="Unresolved needs" value={metrics?.unresolved_needs} />
        <Kpi
          label="Overflow to the Charles"
          value={metrics?.overflow_m3}
          unit="m³"
          tone={(metrics?.overflow_m3 ?? 0) > 0 ? "bad" : "good"}
          sub={projected && soFar ? `${Math.round(soFar.overflow_m3 ?? 0).toLocaleString("en-US")} m³ so far` : undefined}
        />
        <Kpi
          label="Hospital outage"
          value={metrics?.hospital_outage_s != null ? Math.round(metrics.hospital_outage_s / 60) : undefined}
          unit="min"
          tone={(metrics?.hospital_outage_s ?? 0) > 0 ? "bad" : "good"}
          sub={hospital ? `now: ${hospital.state}` : undefined}
        />
        <Kpi label="Roads closed" value={closures.length} />
        <Kpi label="Vehicle-km" value={metrics?.vehicle_km} digits={0} />
      </section>
      <main className="workspace">
      {awayFromSnapshot && !replaying ? (
        <p className="banner">
          Flood extent and road closures follow the clock. Household status, facility state,
          and resource positions stay at the {formatSim(model.snapshot.t_s)}{" "}
          {model.snapshot.source === "scenario" ? "scenario picture" : "snapshot"} until a newer state arrives.
        </p>
      ) : null}
        <MapView
          state={display}
          previous={replaying ? null : model.previous}
          t={model.clock}
          closures={closures}
          playback={replaying ? playback : null}
          walkers={walkers}
          background={background}
          backgroundById={backgroundById}
          showHouseholds={model.showHouseholds}
          showTrips={model.showTrips}
          showWalkers={model.showWalkers}
          legend={model.legend}
          onLegend={(legend) => dispatch({ type: "legend", legend })}
          selection={model.selection}
          follow={model.follow}
          onFollow={(follow) => dispatch({ type: "follow", follow })}
          onSelect={(selection) => dispatch({ type: "select", selection })}
        />
        <Panels
          tab={model.tab}
          onTab={(tab) => dispatch({ type: "tab", tab })}
          state={display}
          t={model.clock}
          closures={closures}
          selection={model.selection}
          playback={replaying ? playback : null}
          walkers={walkers}
          follow={model.follow}
          onFollow={(follow) => dispatch({ type: "follow", follow })}
          onSelect={(selection) => dispatch({ type: "select", selection })}
          comparison={model.comparison}
          scatter={model.scatter}
          scatterTotal={model.scatterTotal}
          plans={model.plans}
          judge={model.judge}
          notice={model.notice}
          busy={model.busy}
          onCloseRoad={(edgeId) => void closeRoad(edgeId)}
          onUndoClosure={(edgeId) => dispatch({ type: "undo", edgeId })}
          onReplan={() => void replan()}
          onCompare={() => void compare()}
          onOptimize={() => void optimize()}
        />
      </main>
      <footer className="foot">
        <label className="check">
          <input
            type="checkbox"
            checked={model.showHouseholds}
            onChange={() => dispatch({ type: "households" })}
          />
          Lit homes
        </label>
        <label className="check">
          <input type="checkbox" checked={model.showWalkers} onChange={() => dispatch({ type: "walkers" })} />
          Neighbours on foot (illustrative)
        </label>
        <label className="check">
          <input type="checkbox" checked={model.showTrips} onChange={() => dispatch({ type: "trips" })} />
          Ambient trips
        </label>
        <details>
          <summary>What is synthetic</summary>
          <p>
            {[
              ...(model.snapshot.synthetic ?? scenario.synthetic ?? []),
              "household names and members are generated from ids",
              "neighbours on foot, people gathering at doors and the walking share are illustrative (not simulated, not in any metric)",
              "vehicles, pickups, deadlines, facility states and overflow come from the engine's simulation",
            ].join(" · ")}
          </p>
        </details>
        {model.mode === "live" ? (
          <ApiField value={model.apiBase} onCommit={(apiBase) => dispatch({ type: "api", apiBase })} />
        ) : null}
      </footer>
    </div>
  );
}

function ApiField(props: { value: string; onCommit: (value: string) => void }) {
  return (
    <label className="api">
      API
      <input
        defaultValue={props.value}
        key={props.value}
        onBlur={(event) => {
          const next = event.target.value.trim();
          if (next && next !== props.value) props.onCommit(next);
        }}
      />
    </label>
  );
}

function Kpi(props: { label: string; value?: number; digits?: number; text?: string; unit?: string; sub?: string; tone?: "good" | "bad" }) {
  const text = props.text ?? (props.value == null ? "—" : props.value.toLocaleString("en-US", {
    maximumFractionDigits: props.digits ?? 0,
    minimumFractionDigits: props.digits ?? 0,
  }));
  return (
    <p className={props.tone ? `kpi ${props.tone}` : "kpi"}>
      <span>{props.label}</span>
      <strong>
        {text}
        {props.unit && props.value != null ? <small> {props.unit}</small> : null}
      </strong>
      {props.sub ? <em>{props.sub}</em> : null}
    </p>
  );
}

import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createClock, useClock, type Clock } from "./clock";
import { MapView, type Focus } from "./components/MapView";
import { Drawer } from "./components/Panels";
import { ArrivalAlerts, ScoreCard, Sources, Ticker, Toasts, useToasts } from "./components/Hud";
import { JoinBadge, PhotonView } from "./components/Photon";
import { ImpactView } from "./components/Impact";
import { DaytonaView } from "./components/Daytona";
import { API_BASE, fixturePlaybacks, publishedComparison, publishedScatter, publishedState, scenario, town } from "./fixtures";
import { buildGraph, planWalkers, type BgHousehold } from "./people";
import { asPlayback, stateFromPlayback, type Playback } from "./playback";
import { loadFullTown, type FullTown } from "./townFull";
import { formatSim, shortName } from "./format";
import { clockLabel } from "./iso/lighting";
import { asArrival, asCalls, asPhones, asState, getJson, openSocket, postJson, robustOf, type LiveStatus } from "./live";
import { closedEdges, householdById, targetName } from "./model";
import { detectArrivals, doorsFrom } from "./arrivals";
import type {
  Arrival,
  AssignmentEvent,
  Calls,
  Comparison,
  JudgeClosure,
  Message,
  Phone,
  PlanMetrics,
  PlanSnapshot,
  Report,
  RobustSummary,
  ScatterPoint,
  Selection,
  StateSnapshot,
} from "./types";

type Mode = "fixture" | "live";
type Replay = "ember" | "baseline";
type View = "live" | "photon" | "impact" | "daytona";

/** The four paths a judge is walked through; keys 1–4 switch. */
const VIEWS: Array<{ id: View; key: string; label: string }> = [
  { id: "live", key: "1", label: "Live" },
  { id: "photon", key: "2", label: "Photon · multiplayer" },
  { id: "impact", key: "3", label: "Impact" },
  { id: "daytona", key: "4", label: "Daytona" },
];

/** The stage camera on one home: about the Treehouse preset's zoom. */
const HOME_ZOOM = 17.3;

/** GET /health; `auto_hold` backends hold their clock at an arrival and report it as `hold` until resumed (D112). */
type Health = { max_players?: number; players?: number; voice_number?: string | null; reader?: string; auto_hold?: boolean; hold?: unknown };

const SPEEDS = [30, 60, 180, 600];
const MAX_PLAYERS = 25;
/** Earlier plan versions fetched on connect for the timeline. */
const PLAN_HISTORY = 12;
const NO_CALLS: Calls = { live: [], recent: [] };

type Model = {
  mode: Mode;
  apiBase: string;
  liveStatus: LiveStatus;
  liveDetail: string | null;
  snapshot: StateSnapshot;
  previous: StateSnapshot | null;
  playing: boolean;
  speed: number;
  comparison: Comparison | null;
  scatter: ScatterPoint[];
  scatterBatch: string | null;
  scatterTotal: number | null;
  /** the last robust optimisation (from the plan that carries it, or GET /optimize), kept after later replans drop it from the plan */
  robust: RobustSummary | null;
  plans: PlanSnapshot[];
  judge: JudgeClosure[];
  selection: Selection | null;
  busy: string | null;
  view: View;
  follow: Selection | null;
  replay: Replay;
  livePlaybacks: { ember: Playback | null; baseline: Playback | null };
  phones: Phone[];
  calls: Calls;
  flat: boolean;
};

type Action =
  | { type: "playing"; playing: boolean }
  | { type: "speed"; speed: number }
  | { type: "mode"; mode: Mode }
  | { type: "api"; apiBase: string }
  | { type: "live-status"; status: LiveStatus; detail?: string | null }
  | { type: "state"; state: StateSnapshot }
  | { type: "plan"; plan: PlanSnapshot }
  | { type: "history"; plan: PlanSnapshot }
  | { type: "scatter"; points: ScatterPoint[] }
  | { type: "robust"; robust: RobustSummary | null }
  | { type: "assignment"; event: AssignmentEvent }
  | { type: "message"; message: Message }
  | { type: "report"; report: Report }
  | { type: "metrics"; metrics: PlanMetrics }
  | { type: "select"; selection: Selection | null }
  | { type: "busy"; busy: string | null }
  | { type: "view"; view: View }
  | { type: "follow"; follow: Selection | null }
  | { type: "replay"; replay: Replay }
  | { type: "playback"; which: Replay; playback: Playback }
  | { type: "phones"; phones: Phone[] }
  | { type: "calls"; calls: Calls }
  | { type: "flat"; flat: boolean }
  | { type: "close"; edgeId: number; t: number }
  | { type: "undo"; edgeId: number };

function withPlan(plans: PlanSnapshot[], plan: PlanSnapshot | null): PlanSnapshot[] {
  if (!plan) return plans;
  if (plans.some((item) => item.version === plan.version)) {
    return plans.map((item) => (item.version === plan.version ? plan : item));
  }
  return [...plans, plan].sort((a, b) => a.version - b.version);
}

const fixtureModel = {
  liveStatus: "idle" as LiveStatus,
  liveDetail: null,
  snapshot: publishedState,
  previous: null,
  plans: [],
  comparison: publishedComparison,
  scatter: publishedScatter,
  scatterBatch: publishedScatter[0]?.batchId ?? null,
  scatterTotal: publishedScatter[0]?.nTotal ?? null,
  robust: null,
};
const liveScatter = { scatter: [], scatterBatch: null, scatterTotal: null };

function reducer(state: Model, action: Action): Model {
  switch (action.type) {
    case "playing":
      return { ...state, playing: action.playing };
    case "speed":
      return { ...state, speed: action.speed };
    case "mode":
      if (action.mode === state.mode) return state;
      return action.mode === "fixture"
        ? { ...state, ...fixtureModel, mode: "fixture" }
        : { ...state, ...liveScatter, mode: "live" };
    case "api":
      return { ...state, apiBase: action.apiBase };
    case "live-status":
      return {
        ...state,
        liveStatus: action.status,
        liveDetail: action.status === "live" ? null : action.detail === undefined ? state.liveDetail : action.detail,
      };
    case "state":
      return {
        ...state,
        snapshot: action.state,
        previous: action.state.t_s === state.snapshot.t_s ? state.previous : state.snapshot,
        plans: withPlan(state.plans, action.state.plan),
        robust: robustOf(action.state.plan) ?? state.robust,
      };
    case "plan":
      return {
        ...state,
        plans: withPlan(state.plans, action.plan),
        robust: robustOf(action.plan) ?? state.robust,
        snapshot: state.snapshot.plan_version === action.plan.version || state.snapshot.plan == null
          ? { ...state.snapshot, plan: action.plan, plan_version: action.plan.version }
          : state.snapshot,
      };
    case "scatter": {
      const batch = action.points[action.points.length - 1].batchId;
      const kept = state.scatterBatch === batch ? state.scatter : [];
      const seen = new Set(kept.map((point) => point.runId));
      const fresh: ScatterPoint[] = [];
      for (const point of action.points) {
        if (point.batchId !== batch || seen.has(point.runId)) continue;
        seen.add(point.runId);
        fresh.push(point);
      }
      return {
        ...state,
        scatterBatch: batch,
        scatterTotal: action.points[action.points.length - 1].nTotal ?? state.scatterTotal,
        scatter: [...kept, ...fresh],
      };
    }
    case "history":
      // an earlier version, fetched once on connect: the timeline only
      return { ...state, plans: withPlan(state.plans, action.plan) };
    case "robust":
      return { ...state, robust: action.robust };
    case "assignment": {
      // a new version arrives whole as `plan`; this patches the current one (a confirm or a decline)
      const current = state.snapshot.plan;
      const incoming = action.event;
      if (!current || incoming.plan_version !== current.version) return state;
      const kept = current.assignments.filter((item) => item.id !== incoming.assignment_id);
      const assignments = incoming.assignment == null || incoming.change === "removed"
        ? kept
        : [...kept, incoming.assignment];
      const plan = { ...current, assignments };
      return {
        ...state,
        snapshot: { ...state.snapshot, plan },
        plans: withPlan(state.plans, plan),
      };
    }
    case "message":
      // re-sent with its report_id once the text is understood: upsert by id
      return {
        ...state,
        snapshot: { ...state.snapshot, messages: [...state.snapshot.messages.filter((item) => item.id !== action.message.id), action.message] },
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
        follow: action.selection && state.follow && (action.selection.kind !== state.follow.kind || action.selection.id !== state.follow.id) ? null : state.follow,
      };
    case "busy":
      return { ...state, busy: action.busy };
    case "view":
      return { ...state, view: action.view };
    case "follow":
      return { ...state, follow: action.follow, selection: action.follow ?? state.selection };
    case "replay":
      return { ...state, replay: action.replay };
    case "playback":
      return { ...state, livePlaybacks: { ...state.livePlaybacks, [action.which]: action.playback } };
    case "phones":
      return { ...state, phones: action.phones };
    case "calls":
      return { ...state, calls: action.calls };
    case "flat":
      return { ...state, flat: action.flat };
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

// Live by default when the build names a backend; ?fixtures (or settings) shows the published fixtures
const query = new URLSearchParams(window.location.search);
const startLive = query.has("live") || (import.meta.env.VITE_API_BASE != null && !query.has("fixtures"));

const initial: Model = {
  ...fixtureModel,
  ...(startLive ? liveScatter : {}),
  mode: startLive ? "live" : "fixture",
  apiBase: API_BASE,
  playing: false,
  speed: 60,
  judge: [],
  selection: null,
  busy: null,
  view: "live",
  follow: null,
  replay: "ember",
  livePlaybacks: { ember: null, baseline: null },
  phones: [],
  calls: NO_CALLS,
  flat: false,
};

export function App() {
  const [model, dispatch] = useReducer(reducer, initial);
  const [clock] = useState(createClock);
  if (import.meta.env.DEV) (window as unknown as { __clock?: typeof clock }).__clock = clock;
  // panels and the score card follow the clock 4× a second; only the stage and the transport follow every frame
  const t = useClock(clock, 250);
  const [toasts, toast] = useToasts();
  const [sources, setSources] = useState(false);
  const [health, setHealth] = useState<Health>({});
  const [focus, setFocus] = useState<Focus | null>(null);
  const [spotlight, setSpotlight] = useState<{ household: number; resource: string } | null>(null);
  const [alerts, setAlerts] = useState<Arrival[]>([]);
  const [hold, setHold] = useState<Arrival | null>(null);
  const settings = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (settings.current?.open && !settings.current.contains(event.target as Node)) settings.current.open = false;
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  const root = model.apiBase.replace(/\/$/, "");
  const live = model.mode === "live";

  const playbacks = live ? model.livePlaybacks : fixturePlaybacks;
  const sameScenario = (pb: Playback | null) => (pb && pb.scenario_id === model.snapshot.scenario_id ? pb : null);
  const emberPb = sameScenario(playbacks.ember);
  const baselinePb = sameScenario(playbacks.baseline);
  const playback = model.replay === "baseline" ? baselinePb : emberPb;

  const emberNow = useMemo(() => (emberPb ? stateFromPlayback(emberPb, model.snapshot, t) : model.snapshot), [emberPb, model.snapshot, t]);
  const baselineNow = useMemo(() => (baselinePb ? stateFromPlayback(baselinePb, model.snapshot, t) : null), [baselinePb, model.snapshot, t]);
  const display = model.replay === "baseline" ? baselineNow ?? model.snapshot : emberNow;
  const closures = useMemo(() => closedEdges(display, t, model.judge), [display, t, model.judge]);
  const plans = withPlan(model.plans, model.plans.length === 0 ? emberNow.plan : null);
  const comparison = model.comparison?.scenario_id === model.snapshot.scenario_id ? model.comparison : null;
  const nominal = {
    ember: model.snapshot.plan?.metrics ?? emberNow.plan?.metrics,
    baseline: baselinePb?.metrics ?? comparison?.nominal.baseline,
  };
  const plan = model.snapshot.plan ?? emberNow.plan;

  // every household (full shared town) for the walking crowd; the fixture's 1-in-12 sample until it loads
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

  const phones = live ? model.phones : [];
  const calls = live ? model.calls : NO_CALLS;
  // each player's home, its player number, and whether EMBER has them on a call
  const watched = useMemo(() => {
    const onCall = new Set(calls.live.map((call) => call.handle));
    return new Map(
      phones
        .filter((phone) => phone.player != null && phone.household_id != null)
        .map((phone) => [phone.household_id!, { player: phone.player, onCall: onCall.has(phone.handle) }]),
    );
  }, [phones, calls]);
  const players = useMemo(
    () => new Map([...watched].map(([id, who]) => [id, { label: `Player ${who.player}`, onCall: who.onCall }])),
    [watched],
  );
  const playerCount = phones.filter((phone) => phone.player != null).length;
  const maxPlayers = health.max_players ?? MAX_PLAYERS;

  const playingRef = useRef(model.playing);
  playingRef.current = model.playing;
  // paused on an arrival: a late state event must not move the clock off it
  const holdRef = useRef(hold);
  holdRef.current = hold;
  const serverClock = useRef<number | null>(null);
  const applyState = (snapshot: StateSnapshot) => {
    dispatch({ type: "state", state: snapshot });
    serverClock.current = snapshot.t_s;
    if (!playingRef.current && !holdRef.current) clock.set(snapshot.t_s);
  };

  // arrivals: a vehicle reached a player's (or the judge's) home. The WS event, /health.hold and POST /clock's
  // held_by make it immediate; the same households' statuses catch it from the state too. Each one alerts once and
  // pauses the clock at the arrival. A backend that holds its clock (auto_hold) owns the pause: it shows while
  // /health.hold is set and clears when that does; otherwise the pause is this page's until Resume.
  const alerted = useRef(new Map<number, number>());
  const reached = useRef(new Map<number, boolean>());
  const arrive = (arrival: Arrival) => {
    if (alerted.current.has(arrival.household_id)) return;
    alerted.current.set(arrival.household_id, arrival.t_s);
    setAlerts((list) => [arrival, ...list.filter((item) => item.household_id !== arrival.household_id)].slice(0, 3));
    holdRef.current ??= arrival;
    setHold((held) => held ?? arrival);
    setHealth((current) => (current.auto_hold && current.hold == null ? { ...current, hold: arrival } : current));
    dispatch({ type: "playing", playing: false });
    // stop on the arrival itself while playing (and tell the backend's clock); a long scrub past it stays where it was dropped
    if (Math.abs(clock.get() - arrival.t_s) < 120) {
      clock.set(arrival.t_s);
      if (live) postJson(`${root}/clock`, { t_s: arrival.t_s }, 20000).catch(() => undefined);
    }
  };
  const arriveRef = useRef(arrive);
  arriveRef.current = arrive;
  const doors = useMemo(() => doorsFrom(emberPb?.outcomes), [emberPb]);
  const doorsSeen = useRef(doors);
  useEffect(() => {
    // live, nothing counts before the backend's first state; a new replay only re-records who is reached
    if (live && serverClock.current == null) return;
    const quiet = doorsSeen.current !== doors;
    doorsSeen.current = doors;
    const found = detectArrivals(reached.current, emberNow, watched, clock.get(), doors);
    if (!quiet) for (const arrival of found) arriveRef.current(arrival);
    // not reached any more (the clock went back): that home can alert again
    for (const [id, at] of alerted.current) if (reached.current.get(id) === false && clock.get() < at) alerted.current.delete(id);
  }, [live, emberNow, watched, t, doors]);
  const backendHold = asArrival(health.hold);
  useEffect(() => {
    if (backendHold) arriveRef.current(backendHold);
    // the backend let go (its call ended, or resumed elsewhere): so does this page
    else if (health.auto_hold) setHold(null);
    // a new hold is a new household
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendHold?.household_id]);
  const held = live && health.auto_hold ? backendHold : hold;
  const who = (arrival: Arrival) => (arrival.player != null ? `Player ${arrival.player}` : targetName(model.snapshot, { household_id: arrival.household_id }));

  useEffect(() => {
    if (!live) {
      serverClock.current = null;
      clock.set(0);
    }
  }, [live, clock]);

  useEffect(() => {
    if (!model.playing) return;
    let frameId = 0;
    let last = performance.now();
    const step = (now: number) => {
      const next = Math.min(scenario.t_end_s, clock.get() + Math.min(0.1, (now - last) / 1000) * model.speed);
      last = now;
      clock.set(next);
      if (next >= scenario.t_end_s) dispatch({ type: "playing", playing: false });
      else frameId = requestAnimationFrame(step);
    };
    frameId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameId);
  }, [model.playing, model.speed, clock]);

  useEffect(() => {
    if (!live) return;
    let stop = () => {};
    let cancelled = false;
    const run = async () => {
      dispatch({ type: "live-status", status: "connecting", detail: null });
      let latest = 0;
      try {
        const snapshot = asState(await getJson(`${root}/state`));
        if (!cancelled && snapshot) applyState(snapshot);
        latest = snapshot?.plan_version ?? 0;
        if (!cancelled && !snapshot) {
          dispatch({ type: "live-status", status: "error", detail: "GET /state did not return a state snapshot. Showing the last good picture." });
        }
      } catch (error) {
        if (!cancelled) dispatch({ type: "live-status", status: "error", detail: error instanceof Error ? error.message : "GET /state failed." });
      }
      if (cancelled) return;
      // the versions before this page loaded, for the plan timeline
      for (let version = Math.max(1, latest - PLAN_HISTORY); version < latest; version++) {
        getJson(`${root}/plan/${version}`)
          .then((plan) => !cancelled && dispatch({ type: "history", plan: plan as PlanSnapshot }))
          .catch(() => undefined);
      }
      // the last robust optimisation (a later replan drops it from the plan)
      getJson(`${root}/optimize`)
        .then((body) => dispatch({ type: "robust", robust: robustOf({ search: (body as { last?: unknown }).last }) }))
        .catch(() => undefined);
      // The backend broadcasts `plan` after a replan but not always a fresh `state`, so closed roads and
      // vehicle ETAs would stay stale; refetch GET /state shortly after a plan unless a `state` event lands.
      let refetch: number | undefined;
      const refetchState = async () => {
        refetch = undefined;
        try {
          const snapshot = asState(await getJson(`${root}/state`));
          if (!cancelled && snapshot) applyState(snapshot);
        } catch {
          // keep the last good picture; the socket status already reports connectivity
        }
      };
      // a 1,000-run fan-out streams 1,000 scatter points: hand them to React once per frame
      let pending: ScatterPoint[] = [];
      let flush = 0;
      const closeSocket = openSocket(
        model.apiBase,
        (event) => {
          if (event.type === "state") {
            window.clearTimeout(refetch);
            refetch = undefined;
            applyState(event.state);
          } else if (event.type === "plan") {
            dispatch({ type: "plan", plan: event.plan });
            window.clearTimeout(refetch);
            refetch = window.setTimeout(() => void refetchState(), 300);
          } else if (event.type === "scatter_point") {
            pending.push(event.point);
            flush ||= requestAnimationFrame(() => {
              flush = 0;
              dispatch({ type: "scatter", points: pending });
              pending = [];
            });
          } else if (event.type === "assignment") dispatch({ type: "assignment", event: event.event });
          else if (event.type === "message") dispatch({ type: "message", message: event.message });
          else if (event.type === "report") dispatch({ type: "report", report: event.report });
          else if (event.type === "metrics") dispatch({ type: "metrics", metrics: event.metrics });
          else if (event.type === "arrival") arriveRef.current(event.arrival);
        },
        (status, detail) => dispatch({ type: "live-status", status, detail }),
        async () => {
          const snapshot = asState(await getJson(`${root}/state`));
          if (snapshot) applyState(snapshot);
          else throw new Error("GET /state did not return a state snapshot.");
        },
      );
      stop = () => {
        window.clearTimeout(refetch);
        cancelAnimationFrame(flush);
        closeSocket();
      };
    };
    void run();
    return () => {
      cancelled = true;
      stop();
    };
  }, [live, root]);

  // live: the replays of the current plan and of the baseline on the same reports; a failed fetch keeps the last good one
  const livePlanVersion = live ? model.snapshot.plan?.version ?? model.snapshot.plan_version : null;
  const reportCount = model.snapshot.reports.length;
  useEffect(() => {
    if (!live || livePlanVersion == null) return;
    const abort = new AbortController();
    for (const which of ["ember", "baseline"] as const) {
      getJson(`${root}/playback?which=${which}`, 30000, abort.signal)
        .then((body) => {
          const pb = asPlayback(body);
          if (pb) dispatch({ type: "playback", which, playback: pb });
        })
        .catch(() => undefined);
    }
    return () => abort.abort();
  }, [live, root, livePlanVersion, reportCount]);

  // live: the roster, the calls in progress, and the player cap, call-in number and clock hold (no WebSocket events for these)
  useEffect(() => {
    if (!live) return;
    const poll = () => {
      getJson(`${root}/phones`)
        .then((body) => {
          const list = asPhones(body);
          if (list) dispatch({ type: "phones", phones: list });
        })
        .catch(() => undefined);
      getJson(`${root}/calls`)
        .then((body) => {
          const list = asCalls(body);
          if (list) dispatch({ type: "calls", calls: list });
        })
        .catch(() => undefined);
      getJson(`${root}/health`).then((body) => setHealth(body as Health)).catch(() => undefined);
    };
    poll();
    const handle = window.setInterval(poll, 2000);
    return () => window.clearInterval(handle);
  }, [live, root]);

  // live: the backend's clock follows the scrubber (debounced) and the play head
  useEffect(() => {
    if (!live) return;
    const push = () => {
      if (serverClock.current == null || Math.abs(clock.get() - serverClock.current) < 1) return;
      postJson(`${root}/clock`, { t_s: clock.get() }, 20000)
        .then((body) => {
          // a held backend clamps the clock to the arrival and says which one (covers a missed WS event)
          const arrival = asArrival((body as { held_by?: unknown } | null)?.held_by);
          if (arrival) arriveRef.current(arrival);
        })
        .catch((error: unknown) => toast(`Clock failed: ${error instanceof Error ? error.message : "POST /clock failed"}`, "error"));
    };
    if (model.playing) {
      const handle = window.setInterval(push, 1200);
      return () => window.clearInterval(handle);
    }
    let handle = 0;
    const stop = clock.subscribe(() => {
      window.clearTimeout(handle);
      handle = window.setTimeout(push, 400);
    });
    return () => {
      stop();
      window.clearTimeout(handle);
    };
  }, [live, model.playing, root, clock, toast]);

  async function closeRoad(edgeId: number) {
    dispatch({ type: "close", edgeId, t: clock.get() });
    if (!live) {
      toast("Closed on this map only. Live mode also tells the planner (POST /disruption).");
      return;
    }
    dispatch({ type: "busy", busy: "close" });
    try {
      await postJson(`${root}/disruption`, { close_edges: [edgeId] }, 30000);
      const snapshot = asState(await getJson(`${root}/state`));
      if (snapshot) applyState(snapshot);
      toast(`Road closed: edge ${edgeId}, both directions.`);
    } catch (error) {
      toast(error instanceof Error ? `Close failed: ${error.message}` : "Close failed.", "error");
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  /** Paired worlds per plan: 50 by default, 2000 for the large test; distinct plans determine total runs. */
  async function optimize(seeds?: number) {
    dispatch({ type: "view", view: "daytona" });
    if (!live) {
      toast("Optimize runs on the backend (Daytona, or the local pool): switch to Live in settings.");
      return;
    }
    dispatch({ type: "playing", playing: false });
    dispatch({ type: "busy", busy: seeds ? "stress" : "optimize" });
    try {
      // Stress-test one point in time. Synchronize the paused playhead before starting the batch.
      await postJson(`${root}/clock`, { t_s: clock.get() }, 20000);
      try {
        await postJson(`${root}/optimize${seeds ? `?seeds=${seeds}` : ""}`, {}, 15000);
      } catch (error) {
        // 409 = one is already running: watch that one instead of failing
        if (!(error instanceof Error && error.message.startsWith("409"))) throw error;
      }
      const deadline = Date.now() + 300_000;
      let last: unknown = null;
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        let body: unknown;
        try {
          body = await getJson(`${root}/optimize`, 20000);
        } catch (error) {
          // A busy backend or a short connection loss must not hide a batch still streaming over WS.
          if (Date.now() > deadline) throw error;
          continue;
        }
        if (typeof body === "object" && body !== null && (body as { running?: unknown }).running === false) {
          last = (body as { last?: unknown }).last ?? null;
          break;
        }
        if (Date.now() > deadline) throw new Error("still running after 5 min");
      }
      const snapshot = asState(await getJson(`${root}/state`));
      if (snapshot) applyState(snapshot);
      const error = typeof last === "object" && last !== null ? (last as { error?: unknown }).error : undefined;
      const robust = robustOf({ search: last });
      if (robust) dispatch({ type: "robust", robust });
      if (typeof error === "string") toast(`Optimize failed: ${error}`, "error");
      else if (robust) {
        toast(robust.chosen !== robust.nominal_best
          ? `Chose ${robust.chosen} over the forecast's best ${robust.nominal_best}: fewer people missed in the worst 20% of worlds.`
          : `Kept the forecast plan ${robust.chosen}: no candidate beats it by ≥ 1 person in the worst 20%.`, "plan");
      }
    } catch (error) {
      toast(error instanceof Error ? `Optimize failed: ${error.message}` : "Optimize failed.", "error");
    } finally {
      dispatch({ type: "busy", busy: null });
    }
  }

  /** The stage camera eases close onto a home and opens it; with a vehicle, that vehicle is ringed and named too. */
  function showHousehold(id: number, resource?: string) {
    const household = householdById(emberNow, id);
    if (!household) return;
    dispatch({ type: "view", view: "live" });
    dispatch({ type: "select", selection: { kind: "household", id } });
    setSpotlight(resource ? { household: id, resource } : null);
    setFocus({ lon: household.lon, lat: household.lat, zoom: HOME_ZOOM, key: Date.now(), household: id });
  }

  function resume() {
    setHold(null);
    if (held) setAlerts((list) => list.filter((item) => item.household_id !== held.household_id));
    if (live && backendHold) {
      setHealth((current) => ({ ...current, hold: null }));
      postJson(`${root}/clock`, { t_s: clock.get(), resume: true }, 20000).catch((error: unknown) =>
        toast(`Resume failed: ${error instanceof Error ? error.message : "POST /clock failed"}`, "error"),
      );
    }
    dispatch({ type: "playing", playing: true });
  }

  const status = live ? model.liveStatus : "idle";
  // a home picked on the map or in the ticker: the camera goes there too
  const select = (selection: Selection | null) => {
    if (selection?.kind === "household" && householdById(emberNow, selection.id)) showHousehold(selection.id);
    else dispatch({ type: "select", selection });
  };
  const follow = (selection: Selection | null) => dispatch({ type: "follow", follow: selection });
  const view = model.view;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const next = VIEWS.find((item) => item.key === event.key);
      if (next) dispatch({ type: "view", view: next.id });
      else if (event.key === "s" && alerts[0]) showHousehold(alerts[0].household_id, alerts[0].resource_id);
      else if (event.key === "Escape") dispatch({ type: "select", selection: null });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="app">
      <header className="top">
        <p className="brand">
          <strong>EMBER</strong>
          <span>Allston flood</span>
        </p>
        <nav className="views" role="tablist" aria-label="Views">
          {VIEWS.map((item) => (
            <button key={item.id} role="tab" aria-selected={view === item.id} className={view === item.id ? "on" : ""} onClick={() => dispatch({ type: "view", view: item.id })}>
              <kbd>{item.key}</kbd>
              {item.label}
              {item.id === "photon" && calls.live.length > 0 ? <i className="badge live" title="on call">{calls.live.length}</i> : null}
              {item.id === "daytona" && (model.busy === "stress" || model.busy === "optimize") ? <i className="badge live" title="running" /> : null}
            </button>
          ))}
        </nav>
        <Transport
          clock={clock}
          playing={model.playing}
          disabled={model.busy === "stress" || model.busy === "optimize"}
          held={held ? `Paused · ${shortName(held.resource_name)} at ${who(held)}` : null}
          onPlay={(playing) => (held && playing ? resume() : dispatch({ type: "playing", playing }))}
        />
        <label className="switch">
          <input
            type="checkbox"
            checked={model.replay === "baseline"}
            onChange={(event) => dispatch({ type: "replay", replay: event.target.checked ? "baseline" : "ember" })}
          />
          <i />
          vs baseline
        </label>
        <p className={`status ${status}`} title={model.liveDetail ?? undefined}>
          {live ? (status === "live" ? "Live" : status === "error" ? "Offline" : "Connecting") : "Replay"}
        </p>
        <button className="link" onClick={() => setSources(true)}>
          Real vs synthetic
        </button>
        <details className="settings" ref={settings}>
          <summary aria-label="Settings">⚙</summary>
          <div className="popover">
            <p>Data</p>
            <div className="segmented">
              <button className={live ? "" : "on"} onClick={() => dispatch({ type: "mode", mode: "fixture" })}>
                Fixtures
              </button>
              <button className={live ? "on" : ""} onClick={() => dispatch({ type: "mode", mode: "live" })}>
                Live
              </button>
            </div>
            {live ? (
              <input
                aria-label="Backend URL"
                defaultValue={model.apiBase}
                key={model.apiBase}
                onBlur={(event) => {
                  const next = event.target.value.trim();
                  if (next && next !== model.apiBase) dispatch({ type: "api", apiBase: next });
                }}
              />
            ) : null}
            {live && model.liveDetail ? <small>{model.liveDetail}</small> : null}
            <p>Speed</p>
            <div className="segmented">
              {SPEEDS.map((speed) => (
                <button key={speed} className={model.speed === speed ? "on" : ""} onClick={() => dispatch({ type: "speed", speed })}>
                  {speed}×
                </button>
              ))}
            </div>
            <p>View</p>
            <div className="segmented">
              <button className={model.flat ? "" : "on"} onClick={() => dispatch({ type: "flat", flat: false })}>
                Stage
              </button>
              <button className={model.flat ? "on" : ""} onClick={() => dispatch({ type: "flat", flat: true })}>
                Flat map
              </button>
            </div>
          </div>
        </details>
      </header>
      <main className={`workspace view-${view}`}>
        <section className="stage">
          <MapView
            clock={clock}
            snapshot={model.snapshot}
            previous={model.previous}
            playback={playback}
            judge={model.judge}
            walkers={walkers}
            background={background}
            backgroundById={backgroundById}
            players={players}
            flat={model.flat}
            selection={model.selection}
            follow={model.follow}
            focus={focus}
            spotlight={spotlight && model.selection?.kind === "household" && model.selection.id === spotlight.household ? spotlight.resource : null}
            onFocus={setFocus}
            onFollow={follow}
            onSelect={select}
          />
          {view === "live" ? (
            <>
              <ScoreCard plan={plan} projected={nominal.ember} baseline={nominal.baseline} state={emberNow} />
              <Ticker state={display} plans={plans} playback={playback} t={t} onSelect={select} />
              <JoinBadge voiceNumber={live ? health.voice_number ?? null : null} players={playerCount} max={maxPlayers} onOpen={() => dispatch({ type: "view", view: "photon" })} />
              {model.replay === "baseline" ? (
                <p className="replay-chip">{baselinePb ? "Baseline: incident by incident, same reports" : "Baseline replay unavailable"}</p>
              ) : live && !emberPb ? (
                <p className="replay-chip muted">No live replay yet · vehicles step between snapshots</p>
              ) : null}
            </>
          ) : null}
          <Toasts toasts={toasts} />
        </section>
        {view === "photon" ? (
          <PhotonView
            apiBase={live ? root : null}
            phones={phones}
            calls={calls}
            state={emberNow}
            plans={plans}
            t={t}
            max={maxPlayers}
            voiceNumber={health.voice_number ?? null}
            reader={live ? health.reader ?? null : null}
            onShow={(id) => showHousehold(id)}
          />
        ) : view === "impact" ? (
          <ImpactView plan={plan} plans={plans} projected={nominal.ember} baseline={nominal.baseline} state={emberNow} onSources={() => setSources(true)} />
        ) : view === "daytona" ? (
          <DaytonaView t={t} plans={plans} robust={model.robust} scatter={model.scatter} scatterTotal={model.scatterTotal} busy={model.busy} onOptimize={(seeds) => void optimize(seeds)} />
        ) : null}
        {model.selection ? (
          <Drawer
            selection={model.selection}
            state={display}
            t={t}
            closures={closures}
            judge={model.judge}
            busy={model.busy}
            playback={playback}
            walkers={walkers}
            follow={model.follow}
            onCloseRoad={(edgeId) => void closeRoad(edgeId)}
            onUndoClosure={(edgeId) => dispatch({ type: "undo", edgeId })}
            onFollow={follow}
            onSelect={(selection) => dispatch({ type: "select", selection })}
          />
        ) : null}
        <ArrivalAlerts
          alerts={alerts}
          hold={held}
          who={who}
          onShow={(arrival) => showHousehold(arrival.household_id, arrival.resource_id)}
          onDismiss={(arrival) => setAlerts((list) => list.filter((item) => item.household_id !== arrival.household_id))}
          onResume={resume}
        />
      </main>
      {sources ? <Sources synthetic={model.snapshot.synthetic ?? scenario.synthetic ?? []} onClose={() => setSources(false)} /> : null}
    </div>
  );
}

/** Play, scrub and the clock: follows every frame, so the scrubber never lags the stage. */
function Transport(props: { clock: Clock; playing: boolean; disabled?: boolean; held: string | null; onPlay: (playing: boolean) => void }) {
  const t = useClock(props.clock);
  return (
    <div className="transport">
      <button className="play" disabled={props.disabled} aria-label={props.playing ? "Pause" : "Play"} onClick={() => props.onPlay(!props.playing)}>
        {props.playing ? "❚❚" : "▶"}
      </button>
      <input
        type="range"
        aria-label="Simulation time"
        min={0}
        max={scenario.t_end_s}
        step={scenario.tick_s ?? 60}
        value={t}
        disabled={props.disabled}
        onChange={(event) => props.clock.set(Number(event.target.value))}
      />
      <p className={props.held ? "time held" : "time"}>
        {formatSim(t)}
        <small>{props.held ?? (props.disabled ? "Paused for stress test" : clockLabel(t))}</small>
      </p>
    </div>
  );
}

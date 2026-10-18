/** What floats over the stage and the workspace: the score card, the decisions ticker, arrival alerts, toasts, and the sources drawer. */

import { useCallback, useState } from "react";
import { scenario } from "../fixtures";
import { formatNumber, formatSim, keptBeforeTradeoff, planTiming, shortName, tradedFacility } from "../format";
import { facilityById, peopleCount, resourceById } from "../model";
import type { Playback } from "../playback";
import type { Arrival, PlanMetrics, PlanSnapshot, Selection, StateSnapshot } from "../types";
import { feedItems, type FeedItem } from "./Panels";
import { Icon } from "./Icon";

const WAITING = new Set(["needs", "unknown", "assigned", "confirmed"]);

/** People still waiting for help at this moment. */
function waitingPeople(state: StateSnapshot): number {
  return state.households.filter((household) => WAITING.has(household.status)).reduce((sum, household) => sum + peopleCount(household, 1), 0);
}

function Score(props: { label: string; value?: number; baseline?: number; unit?: string; better: "higher" | "lower"; sub?: string }) {
  const { value, baseline } = props;
  const delta = value != null && baseline != null ? value - baseline : null;
  const good = delta != null && (props.better === "higher" ? delta > 0 : delta < 0);
  return (
    <div className="score">
      <span>{props.label}</span>
      <strong>
        {formatNumber(value)}
        {props.unit && value != null ? <small> {props.unit}</small> : null}
      </strong>
      {delta == null ? null : (
        <em className={delta === 0 ? "" : good ? "good" : "bad"}>
          {delta === 0 ? "= baseline" : `${delta > 0 ? "+" : "−"}${formatNumber(Math.abs(delta))} vs baseline`}
        </em>
      )}
      {props.sub ? <i>{props.sub}</i> : null}
    </div>
  );
}

export function ScoreCard(props: { plan: PlanSnapshot | null; projected?: PlanMetrics; baseline?: PlanMetrics; state: StateSnapshot }) {
  const { plan, projected, baseline, state } = props;
  const minutes = (s?: number) => (s == null ? undefined : Math.round(s / 60));
  // the plan ranks people, then the hospital, then sewage: once it trades the overflow away it says so in
  // `unresolved`, and the tile shows what EMBER kept out of the river before that call
  const traded = tradedFacility(plan);
  const kept = keptBeforeTradeoff(plan);
  const moved = traded ? plan?.assignments.find((item) => item.task === "protect" && item.status !== "cancelled") : undefined;
  const tradeOff = moved && "facility_id" in moved.target
    ? `${shortName(resourceById(state, moved.resource_id)?.name ?? moved.resource_id)} → ${shortName(facilityById(state, moved.target.facility_id)?.name ?? moved.target.facility_id)} · ${formatNumber(projected?.overflow_m3)} m³ accepted`
    : undefined;
  return (
    <section className="scorecard" aria-label="Outcome of the current plan">
      <header key={plan?.version}>
        <strong>plan v{plan?.version ?? "—"}</strong>
        {plan ? <span>{planTiming(plan)}</span> : null}
      </header>
      <Score
        label="Reached before water"
        value={projected?.people_reached_before_deadline}
        baseline={baseline?.people_reached_before_deadline}
        better="higher"
        sub={state.metrics.people_reached_before_deadline != null ? `${state.metrics.people_reached_before_deadline} so far` : undefined}
      />
      <Score label="Still at home now" value={waitingPeople(state)} better="lower" />
      <Score label="Hospital outage" value={minutes(projected?.hospital_outage_s)} baseline={minutes(baseline?.hospital_outage_s)} unit="min" better="lower" />
      {kept != null ? (
        <Score label="Kept out of the Charles" value={kept} unit="m³" better="higher" sub={traded ? ["before the hospital call", tradeOff].filter(Boolean).join(" · ") : undefined} />
      ) : (
        <Score label="Sewage overflow" value={projected?.overflow_m3} baseline={baseline?.overflow_m3} unit="m³" better="lower" sub={tradeOff} />
      )}
    </section>
  );
}

const TICKER_ICON: Record<FeedItem["kind"], string> = { in: "phone", fact: "read", plan: "route", out: "send" };
const TICKER_ROWS = 5;

/** The newest decisions, one line each: heard → fact → plan change → who was told. A row zooms to who it is about. */
export function Ticker(props: { state: StateSnapshot; plans: PlanSnapshot[]; playback: Playback | null; t: number; onSelect: (selection: Selection) => void }) {
  const items = feedItems(props.state, props.plans, props.playback, props.t).slice(0, TICKER_ROWS);
  return (
    <section className="ticker" aria-label="Decisions">
      <h3>Decisions</h3>
      {items.length === 0 ? <p className="hint">Waiting for the first call</p> : null}
      <ol>
        {items.map((item) => (
          <li key={item.key} className={item.kind}>
            <button
              disabled={!item.target}
              onClick={() => item.target && props.onSelect("household_id" in item.target ? { kind: "household", id: item.target.household_id } : { kind: "facility", id: item.target.facility_id })}
            >
              <Icon name={TICKER_ICON[item.kind]} />
              <b>{item.kind === "plan" ? item.title.split(" ")[0] : item.title.replace(/^EMBER /, "")}</b>
              <span>{item.kind === "in" ? `“${item.text}”` : item.text}</span>
              <time>{formatSim(item.t_s)}</time>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** "Accessible Van 3 reached Player 2": Show zooms the stage onto them; the held one resumes the clock. */
export function ArrivalAlerts(props: {
  alerts: Arrival[];
  hold: Arrival | null;
  who: (arrival: Arrival) => string;
  onShow: (arrival: Arrival) => void;
  onDismiss: (arrival: Arrival) => void;
  onResume: () => void;
}) {
  const held = props.hold;
  const list = held && !props.alerts.some((item) => item.household_id === held.household_id) ? [held, ...props.alerts] : props.alerts;
  if (list.length === 0) return null;
  return (
    <ol className="arrivals" aria-live="assertive">
      {list.slice(0, 3).map((arrival) => {
        const holding = held?.household_id === arrival.household_id;
        return (
          <li key={arrival.household_id} className={holding ? "held" : ""}>
            <Icon name="van" size={26} />
            <p>
              <b>{shortName(arrival.resource_name)}</b> reached <b>{props.who(arrival)}</b>
              <span>{formatSim(arrival.t_s)}{arrival.call ? " · calling…" : ""}{holding ? " · clock paused" : ""}</span>
            </p>
            <button className="primary" onClick={() => props.onShow(arrival)}>Show</button>
            {holding ? <button className="ghost" onClick={props.onResume}>Resume ▶</button> : null}
            <button className="close" aria-label="Dismiss" onClick={() => props.onDismiss(arrival)}>×</button>
          </li>
        );
      })}
    </ol>
  );
}

type Toast = { id: number; text: string; tone: "plan" | "info" | "error" };

let nextToast = 0;

export function useToasts(): [Toast[], (text: string, tone?: Toast["tone"]) => void] {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = (nextToast += 1);
    setToasts((list) => [...list.slice(-2), { id, text, tone }]);
    window.setTimeout(() => setToasts((list) => list.filter((toast) => toast.id !== id)), tone === "plan" ? 9000 : 6000);
  }, []);
  return [toasts, push];
}

export function Toasts(props: { toasts: Toast[] }) {
  return (
    <ol className="toasts" aria-live="polite">
      {props.toasts.map((toast) => (
        <li key={toast.id} className={toast.tone}>
          {toast.text}
        </li>
      ))}
    </ol>
  );
}

export function Sources(props: { synthetic: string[]; onClose: () => void }) {
  return (
    <div className="sources" role="dialog" aria-label="Sources and what is synthetic" onClick={props.onClose}>
      <article onClick={(event) => event.stopPropagation()}>
        <header>
          <h2>Sources &amp; what is synthetic</h2>
          <button className="close" onClick={props.onClose} aria-label="Close">×</button>
        </header>
        <h3>Real data</h3>
        <ul>
          <li>Streets, bridges, the Treehouse, Cottage Farm, Mount Auburn Hospital: OpenStreetMap contributors (via OSMnx).</li>
          <li>Building footprints, heights and trees: City of Boston and City of Cambridge open data (PDDL).</li>
          <li>Cottage Farm CSO (MWR201) released 21.33 million gallons ≈ 80,700 m³ of combined sewage into the Charles on 2024-01-10: MWRA, 2024 Annual CSO Discharge Report, Table 2-2.</li>
          <li>Allston and Brighton are among the Charles River neighbourhoods exposed if the river dam is overtopped: Climate Ready Boston (2016).</li>
        </ul>
        <h3>Synthetic (labelled)</h3>
        <ul>
          {props.synthetic.map((line) => (
            <li key={line}>{line}</li>
          ))}
          <li>household names and members are generated from ids</li>
          <li>players get a real town building in the forecast flood zone, chosen by us; their needs are what they say on the call or text</li>
          <li>neighbours on foot, people gathering at doors and passers-by are illustrative (not simulated, not in any metric)</li>
          <li>everyday street traffic and the traffic-light timing are illustrative; the signal locations are OpenStreetMap's, and the evacuation traffic the vans feel is the engine's staged-evacuation run</li>
          <li>vehicles, pickups, deadlines, facility states and overflow come from the engine's simulation of {scenario.scenario_id}</li>
        </ul>
      </article>
    </div>
  );
}

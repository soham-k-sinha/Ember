/** What floats over the stage: the score card, the latest change, toasts, the join card, and the sources drawer. */

import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import qrcode from "qrcode-generator";
import { scenario } from "../fixtures";
import { postJson } from "../live";
import { formatNumber, maskHandle, planCause, planDiff, planTiming, shortName, statusLabel } from "../format";
import { facilityById, peopleCount, resourceById } from "../model";
import type { Calls, Phone, PlanMetrics, PlanSnapshot, StateSnapshot } from "../types";

const WAITING = new Set(["needs", "unknown", "assigned", "confirmed"]);
const FACTS = new Set(["need", "closure_report", "facility_status"]);

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
          {delta === 0 ? "same as baseline" : `${delta > 0 ? "+" : "−"}${formatNumber(Math.abs(delta))} vs baseline`}
        </em>
      )}
      {props.sub ? <i>{props.sub}</i> : null}
    </div>
  );
}

export function ScoreCard(props: {
  plan: PlanSnapshot | null;
  projected?: PlanMetrics;
  baseline?: PlanMetrics;
  state: StateSnapshot;
  onSources: () => void;
}) {
  const { plan, projected, baseline, state } = props;
  const minutes = (s?: number) => (s == null ? undefined : Math.round(s / 60));
  // the plan ranks people, then the hospital, then sewage: once it trades the overflow away it says so in
  // `unresolved`, and the tile keeps what EMBER kept out of the river before that call (read only while every
  // fact is planned for, so a baseline that already saw the next report is never compared with the old plan)
  const cost = plan?.unresolved.find((item) => "facility_id" in item.target);
  const settled = !cost && !state.reports.some((report) => FACTS.has(report.kind) && !report.resolved);
  const kept = useRef<number>();
  if (settled && projected?.overflow_m3 != null && baseline?.overflow_m3 != null) kept.current = baseline.overflow_m3 - projected.overflow_m3;
  const moved = cost ? plan?.assignments.find((item) => item.task === "protect" && item.status !== "cancelled") : undefined;
  const tradeOff = moved && "facility_id" in moved.target
    ? `${shortName(resourceById(state, moved.resource_id)?.name ?? moved.resource_id)} moved to ${shortName(facilityById(state, moved.target.facility_id)?.name ?? moved.target.facility_id)}: people first; ${formatNumber(projected?.overflow_m3)} m³ accepted, stated`
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
      <Score label="People still at home now" value={waitingPeople(state)} better="lower" />
      <Score label="Hospital outage" value={minutes(projected?.hospital_outage_s)} baseline={minutes(baseline?.hospital_outage_s)} unit="min" better="lower" />
      {kept.current != null ? (
        <Score
          label="Kept out of the Charles"
          value={kept.current}
          unit="m³"
          better="higher"
          sub={tradeOff ?? `sewage overflow ${formatNumber(projected?.overflow_m3)} m³ · baseline ${formatNumber(baseline?.overflow_m3)} m³`}
        />
      ) : (
        <Score label="Sewage overflow" value={projected?.overflow_m3} baseline={baseline?.overflow_m3} unit="m³" better="lower" sub={tradeOff} />
      )}
      <p>Projected to the end of the flood · baseline: incident by incident</p>
      <button className="chip" onClick={props.onSources}>Real streets · synthetic households, flood timing &amp; fleet</button>
    </section>
  );
}

/** The newest change, pinned over the map: what came in, what the plan did, and how fast. */
export function Latest(props: { plan?: PlanSnapshot; state: StateSnapshot }) {
  const { plan, state } = props;
  if (!plan) return null;
  return (
    <p className="latest" key={plan.version}>
      {plan.version > 1 ? (
        <>
          <b>{planCause(plan, state)}</b> → {planDiff(plan, state) || "no assignment changed"} <span>· v{plan.version} {planTiming(plan)}</span>
        </>
      ) : (
        <>
          <b>Plan v1 from the forecast</b> <span>· every text from here on becomes a new plan</span>
        </>
      )}
    </p>
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

function QrCode(props: { text: string }) {
  const { size, path } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(props.text);
    qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let row = 0; row < n; row++) for (let col = 0; col < n; col++) if (qr.isDark(row, col)) d += `M${col + 2} ${row + 2}h1v1h-1z`;
    return { size: n + 4, path: d };
  }, [props.text]);
  return (
    <svg className="qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="QR code: text JOIN EMBER to the drill line" shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#0b0e14" />
    </svg>
  );
}

type Joined = { player: number; assigned_number: string };

/** Multiplayer (D89): a shared iMessage line only hears phones registered with it, so a player enters their number
 * here first (POST /join), then texts JOIN EMBER to the line it returns; that first text places them. */
export function JoinCard(props: { apiBase: string | null; phones: Phone[]; calls: Calls; state: StateSnapshot; max: number }) {
  const [open, setOpen] = useState(true);
  const [handle, setHandle] = useState("");
  const [joined, setJoined] = useState<Joined | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const players = props.phones.filter((phone) => phone.player != null).sort((a, b) => a.player! - b.player!);
  const onCall = new Set(props.calls.live.map((call) => call.handle));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!props.apiBase || !handle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setJoined((await postJson(`${props.apiBase}/join`, { handle: handle.trim() }, 15000)) as Joined);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Join failed";
      setError(text.startsWith("409") && text.includes("full") ? "The drill is full." : text.startsWith("422") ? "Enter a mobile number, e.g. +1 617 555 0123." : text);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className={open ? "join open" : "join"}>
      <button className="join-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <strong>Join the flood drill</strong>
        <span>{players.length}/{props.max}</span>
      </button>
      {open ? (
        <div className="join-body">
          {joined ? (
            <div className="join-qr">
              <QrCode text={`sms:${joined.assigned_number}?&body=JOIN%20EMBER`} />
              <p>
                Player {joined.player}: text <b>JOIN EMBER</b> to {joined.assigned_number}. You get a real home in the flood zone, and the plan has to save you.
                <button className="join-again" onClick={() => { setJoined(null); setHandle(""); }}>Another phone</button>
              </p>
            </div>
          ) : props.apiBase ? (
            <form className="join-form" onSubmit={submit}>
              <input type="tel" inputMode="tel" autoComplete="tel" placeholder="Your mobile, e.g. +1 617 555 0123" value={handle} onChange={(event) => setHandle(event.target.value)} aria-label="Your mobile number" />
              <button type="submit" disabled={busy || !handle.trim()}>{busy ? "…" : "Join"}</button>
              {error ? <p className="join-error">{error}</p> : null}
            </form>
          ) : (
            <p className="muted">Switch to Live to join the drill from your phone.</p>
          )}
          {players.length > 0 ? (
            <ol className="roster">
              {players.map((phone) => {
                const household = props.state.households.find((item) => item.household_id === phone.household_id);
                return (
                  <li key={phone.handle}>
                    <b>Player {phone.player}</b>
                    <span>{maskHandle(phone.handle)}</span>
                    {household ? <span className={`pill ${household.status}`}>{statusLabel(household.status)}</span> : <span className="muted">waiting for text</span>}
                    {onCall.has(phone.handle) ? <span className="pill call">on call</span> : null}
                  </li>
                );
              })}
            </ol>
          ) : null}
        </div>
      ) : null}
    </section>
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
          <li>drill players get a real town building in the forecast flood zone, chosen by us; their needs are what they text</li>
          <li>neighbours on foot, people gathering at doors and passers-by are illustrative (not simulated, not in any metric)</li>
          <li>vehicles, pickups, deadlines, facility states and overflow come from the engine's simulation of {scenario.scenario_id}</li>
        </ul>
      </article>
    </div>
  );
}

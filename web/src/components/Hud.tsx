/** What floats over the stage: the score card, toasts, the join card, and the sources drawer. */

import { useCallback, useMemo, useState } from "react";
import qrcode from "qrcode-generator";
import { scenario } from "../fixtures";
import { formatNumber, maskHandle, replanSeconds, statusLabel } from "../format";
import { peopleCount } from "../model";
import type { Calls, Phone, PlanMetrics, PlanSnapshot, StateSnapshot } from "../types";

const WAITING = new Set(["needs", "unknown", "assigned", "confirmed"]);

/** People still waiting for help at this moment. */
export function waitingPeople(state: StateSnapshot): number {
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
  soFar: PlanMetrics;
  waiting: number;
  waitingBaseline: number | null;
}) {
  const { projected, baseline, soFar } = props;
  const seconds = props.plan ? replanSeconds(props.plan) : null;
  const minutes = (s?: number) => (s == null ? undefined : Math.round(s / 60));
  return (
    <section className="scorecard" aria-label="Outcome of the current plan">
      <header key={props.plan?.version}>
        <strong>plan v{props.plan?.version ?? "—"}</strong>
        {seconds != null ? <span>replanned in {seconds.toFixed(1)} s</span> : null}
      </header>
      <Score
        label="Reached before water"
        value={projected?.people_reached_before_deadline}
        baseline={baseline?.people_reached_before_deadline}
        better="higher"
        sub={soFar.people_reached_before_deadline != null ? `${soFar.people_reached_before_deadline} so far` : undefined}
      />
      <Score label="Still waiting" value={props.waiting} baseline={props.waitingBaseline ?? undefined} better="lower" sub="people, right now" />
      <Score label="Hospital outage" value={minutes(projected?.hospital_outage_s)} baseline={minutes(baseline?.hospital_outage_s)} unit="min" better="lower" />
      <Score
        label="Sewage overflow"
        value={projected?.overflow_m3}
        baseline={baseline?.overflow_m3}
        unit="m³"
        better="lower"
        sub={soFar.overflow_m3 != null ? `${formatNumber(soFar.overflow_m3)} m³ so far` : undefined}
      />
      <p>Projected to the end of the flood · baseline: incident by incident</p>
    </section>
  );
}

export type Toast = { id: number; text: string; tone: "plan" | "info" | "error" };

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

export function JoinCard(props: { number: string | null; phones: Phone[]; calls: Calls; state: StateSnapshot; max: number }) {
  const [open, setOpen] = useState(true);
  const players = props.phones.filter((phone) => phone.player != null).sort((a, b) => a.player! - b.player!);
  const onCall = new Set(props.calls.live.map((call) => call.handle));
  return (
    <section className={open ? "join open" : "join"}>
      <button className="join-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <strong>Scan to join the flood drill</strong>
        <span>{players.length}/{props.max}</span>
      </button>
      {open ? (
        <div className="join-body">
          {props.number ? (
            <div className="join-qr">
              <QrCode text={`sms:${props.number}&body=JOIN%20EMBER`} />
              <p>
                Or text <b>JOIN EMBER</b> to {props.number}. You get a real home in the flood zone, and the plan has to save you.
              </p>
            </div>
          ) : (
            <p className="muted">Text JOIN EMBER to the drill line to become a household in this flood.</p>
          )}
          {players.length > 0 ? (
            <ol className="roster">
              {players.map((phone) => {
                const household = props.state.households.find((item) => item.household_id === phone.household_id);
                return (
                  <li key={phone.handle}>
                    <b>Player {phone.player}</b>
                    <span>{maskHandle(phone.handle)}</span>
                    {household ? <span className={`pill ${household.status}`}>{statusLabel(household.status)}</span> : <span className="muted">placing…</span>}
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
        <h3>Synthetic (labelled, rule 10)</h3>
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

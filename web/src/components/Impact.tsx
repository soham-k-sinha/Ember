/** Impact view: what the plan changes for people, the hospital and the river, against the incident-by-incident baseline. */

import { formatNumber, formatSim, keptBeforeTradeoff, planDiff, planTiming, tradedFacility } from "../format";
import type { PlanMetrics, PlanSnapshot, StateSnapshot } from "../types";
import { Icon } from "./Icon";

/** Cottage Farm CSO (MWR201), 2024-01-10: 21.33 million gallons (MWRA 2024 Annual CSO Discharge Report, Table 2-2). */
const COTTAGE_FARM_2024_M3 = 80_700;

export function ImpactView(props: {
  plan: PlanSnapshot | null;
  plans: PlanSnapshot[];
  projected?: PlanMetrics;
  baseline?: PlanMetrics;
  state: StateSnapshot;
  onSources: () => void;
}) {
  const { plan, projected, baseline } = props;
  const minutes = (s?: number) => (s == null ? undefined : Math.round(s / 60));
  const kept = keptBeforeTradeoff(plan);
  const traded = tradedFacility(plan);
  return (
    <section className="view" aria-label="Impact">
      <header className="view-head">
        <h2>Impact <span>vs incident-by-incident baseline</span></h2>
        <button className="chip" onClick={props.onSources}>Real vs synthetic</button>
      </header>
      <div className="impact-tiles">
        <Tile icon="people" label="reached before the water" value={projected?.people_reached_before_deadline} baseline={baseline?.people_reached_before_deadline} better="higher" />
        <Tile icon="hospital" label="hospital outage" unit="min" value={minutes(projected?.hospital_outage_s)} baseline={minutes(baseline?.hospital_outage_s)} better="lower" />
        {kept != null ? (
          <Tile icon="water" label="sewage kept out of the Charles" unit="m³" value={kept} sub={traded ? `before the hospital call · then ${formatNumber(projected?.overflow_m3)} m³ accepted, stated` : undefined} />
        ) : (
          <Tile icon="water" label="sewage into the Charles" unit="m³" value={projected?.overflow_m3} baseline={baseline?.overflow_m3} better="lower" />
        )}
      </div>
      <RiverScale ember={projected?.overflow_m3} baseline={baseline?.overflow_m3} kept={kept} />
      <PlanTrack plans={props.plans} state={props.state} />
    </section>
  );
}

function Tile(props: { icon: string; label: string; value?: number; baseline?: number; unit?: string; better?: "higher" | "lower"; sub?: string }) {
  const { value, baseline } = props;
  const delta = value != null && baseline != null ? value - baseline : null;
  const good = delta != null && (props.better === "higher" ? delta > 0 : delta < 0);
  return (
    <div className="tile">
      <span className="tile-label"><Icon name={props.icon} /> {props.label}</span>
      <strong>
        {formatNumber(value)}
        {props.unit && value != null ? <small> {props.unit}</small> : null}
      </strong>
      {delta != null ? (
        <em className={delta === 0 ? "" : good ? "good" : "bad"}>
          {delta === 0 ? "same as baseline" : `${delta > 0 ? "+" : "−"}${formatNumber(Math.abs(delta))}`}
          {delta !== 0 ? <span> vs {formatNumber(baseline)}{props.unit ? ` ${props.unit}` : ""}</span> : null}
        </em>
      ) : null}
      {props.sub ? <i>{props.sub}</i> : null}
    </div>
  );
}

/** The simulated overflow against the one real storm everyone can picture. */
function RiverScale(props: { ember?: number; baseline?: number; kept?: number }) {
  const rows: Array<{ label: string; value?: number; tone: string; tag: string }> = [
    { label: "Cottage Farm, 10 Jan 2024", value: COTTAGE_FARM_2024_M3, tone: "real", tag: "real" },
    { label: "Baseline", value: props.baseline, tone: "baseline", tag: "simulated" },
    { label: "EMBER", value: props.ember, tone: "ember", tag: "simulated" },
  ];
  return (
    <section className="scale" aria-label="Sewage into the Charles, to scale">
      <h3>Sewage into the Charles · to scale</h3>
      <ul>
        {rows.map((row) => (
          <li key={row.label} className={row.tone}>
            <span>{row.label} <small>{row.tag}</small></span>
            <i style={{ width: `${Math.max(0.6, Math.min(100, ((row.value ?? 0) / COTTAGE_FARM_2024_M3) * 100))}%` }} />
            <b>{formatNumber(row.value)} m³</b>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The last plan versions in order: a step per version with its clock time, its change on hover, the newest named. */
const TRACK_MAX = 10;

function PlanTrack(props: { plans: PlanSnapshot[]; state: StateSnapshot }) {
  const shown = props.plans.slice(-TRACK_MAX);
  const newest = shown[shown.length - 1];
  return (
    <section className="track" aria-label="Plan versions">
      <h3>Plan versions · {props.plans.length}</h3>
      <ol className="track-line">
        {shown.map((plan) => (
          <li
            key={plan.version}
            className={plan === newest ? "newest" : ""}
            title={`${plan.trigger ?? ""}${plan.version > 1 ? ` → ${planDiff(plan, props.state)}` : ""}`}
          >
            <b>v{plan.version}</b>
            <span>{formatSim(plan.created_at_t_s)}</span>
          </li>
        ))}
      </ol>
      {newest ? (
        <p className="track-last">
          <b>v{newest.version}</b> {newest.version > 1 ? planDiff(newest, props.state) || newest.trigger : "from the forecast"} <span>{planTiming(newest)}</span>
        </p>
      ) : null}
    </section>
  );
}

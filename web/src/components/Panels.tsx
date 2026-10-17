import { scenario } from "../fixtures";
import {
  formatMinutes,
  formatNeeds,
  formatNumber,
  formatSim,
  statusLabel,
  targetLabel,
  threadKey,
  threadLabel,
} from "../format";
import {
  assignmentById,
  assignmentForTarget,
  closureFor,
  edgeRecord,
  facilityById,
  householdById,
  resourceById,
} from "../model";
import { town } from "../fixtures";
import type {
  Closure,
  Comparison,
  JudgeClosure,
  PlanMetrics,
  PlanSnapshot,
  ScatterPoint,
  Selection,
  StateSnapshot,
  Wastewater,
} from "../types";

const METRICS: Array<{ key: keyof PlanMetrics; label: string; digits: number; unit: string }> = [
  { key: "people_reached_before_deadline", label: "People reached before deadline", digits: 0, unit: "" },
  { key: "people_unreached", label: "People unreached", digits: 0, unit: "" },
  { key: "unresolved_needs", label: "Unresolved needs", digits: 0, unit: "" },
  { key: "hospital_outage_s", label: "Hospital outage", digits: 0, unit: "s" },
  { key: "service_outage_s_total", label: "Service outage", digits: 0, unit: "s" },
  { key: "overflow_m3", label: "Untreated overflow", digits: 1, unit: "m³" },
  { key: "fuel_l", label: "Fuel", digits: 1, unit: "L" },
  { key: "vehicle_km", label: "Vehicle distance", digits: 2, unit: "km" },
  { key: "infeasible_assignments", label: "Infeasible assignments", digits: 0, unit: "" },
  { key: "reserve_remaining", label: "Reserve remaining", digits: 0, unit: "" },
];

export type PanelId = "ledger" | "inspector" | "conversations" | "needs" | "compare" | "scatter" | "plans";

const TABS: Array<{ id: PanelId; label: string }> = [
  { id: "ledger", label: "Ledger" },
  { id: "inspector", label: "Inspector" },
  { id: "conversations", label: "Conversations" },
  { id: "needs", label: "Needs" },
  { id: "compare", label: "Compare" },
  { id: "scatter", label: "Scatter" },
  { id: "plans", label: "Plans" },
];

export function Panels(props: {
  tab: PanelId;
  onTab: (tab: PanelId) => void;
  state: StateSnapshot;
  t: number;
  closures: Closure[];
  selection: Selection | null;
  comparison: Comparison | null;
  scatter: ScatterPoint[];
  plans: PlanSnapshot[];
  judge: JudgeClosure[];
  notice: string | null;
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
  onReplan: () => void;
  onCompare: () => void;
}) {
  return (
    <aside className="side">
      <div className="tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={props.tab === tab.id}
            className={props.tab === tab.id ? "tab on" : "tab"}
            onClick={() => props.onTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {props.notice ? <p className="notice">{props.notice}</p> : null}
      <div className="panel" role="tabpanel">
        {props.tab === "ledger" ? <Ledger {...props} /> : null}
        {props.tab === "inspector" ? <Inspector {...props} /> : null}
        {props.tab === "conversations" ? <Conversations {...props} /> : null}
        {props.tab === "needs" ? <Needs {...props} /> : null}
        {props.tab === "compare" ? <Compare {...props} /> : null}
        {props.tab === "scatter" ? <Scatter {...props} /> : null}
        {props.tab === "plans" ? <Plans {...props} /> : null}
      </div>
    </aside>
  );
}

function Ledger(props: { state: StateSnapshot }) {
  const resources = props.state.resources;
  if (resources.length === 0) {
    return <p className="empty">No resources in this state snapshot.</p>;
  }
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Kind</th>
          <th>Status</th>
          <th>Assignment</th>
          <th>ETA</th>
          <th>Fuel</th>
        </tr>
      </thead>
      <tbody>
        {resources.map((resource) => {
          const assignment = assignmentById(props.state, resource.assignment_id);
          return (
            <tr key={resource.id}>
              <td>
                <strong>{resource.name}</strong>
                <span>{resource.kind.replaceAll("_", " ")}</span>
              </td>
              <td><span className={`pill ${resource.status}`}>{statusLabel(resource.status)}</span></td>
              <td>{assignment ? targetLabel(assignment.target) : "—"}</td>
              <td>{formatMinutes(resource.eta_s)}</td>
              <td>{formatNumber(resource.fuel_l, 1)} L</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Inspector(props: {
  state: StateSnapshot;
  closures: Closure[];
  selection: Selection | null;
  judge: JudgeClosure[];
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
}) {
  const selection = props.selection;
  if (!selection) {
    return (
      <p className="empty">
        Click a household, facility, resource, or road. The inspector shows status, needs,
        dependencies, and the assignment rationale verbatim.
      </p>
    );
  }
  if (selection.kind === "household") return <HouseholdInspector state={props.state} id={selection.id} />;
  if (selection.kind === "facility") return <FacilityInspector state={props.state} id={selection.id} />;
  if (selection.kind === "resource") return <ResourceInspector state={props.state} id={selection.id} />;
  return (
    <EdgeInspector
      edgeId={selection.id}
      closures={props.closures}
      judge={props.judge}
      busy={props.busy}
      onCloseRoad={props.onCloseRoad}
      onUndoClosure={props.onUndoClosure}
    />
  );
}

function HouseholdInspector(props: { state: StateSnapshot; id: number }) {
  const household = householdById(props.state, props.id);
  const townHousehold = town.households.find((item) => item.id === props.id);
  if (!household) {
    return (
      <article>
        <h2>Household #{props.id}</h2>
        <p className="empty">
          This dot is background housing from the town fixture
          {townHousehold ? ` (zone ${townHousehold.zone}, ${townHousehold.size} people)` : ""}.
          It is not in the assisted set, so it has no status, need, or rationale.
        </p>
      </article>
    );
  }
  const assignment = assignmentById(props.state, household.assignment_id)
    ?? assignmentForTarget(props.state, { household_id: household.household_id });
  const unresolved = props.state.plan?.unresolved.find(
    (item) => "household_id" in item.target && item.target.household_id === household.household_id,
  );
  const messages = props.state.messages.filter(
    (message) => "household_id" in message.thread && message.thread.household_id === household.household_id,
  );
  return (
    <article>
      <h2>{household.label ?? `Household #${household.household_id}`}</h2>
      <p className="meta">
        {household.judge ? "Judge · " : ""}
        {statusLabel(household.status)}
        {household.needs_source ? ` · needs from ${household.needs_source}` : ""}
      </p>
      <dl>
        <dt>Needs</dt>
        <dd>{formatNeeds(household.needs)}</dd>
        <dt>Deadline</dt>
        <dd>{formatMinutes(household.deadline_s)}</dd>
        <dt>Blocking constraint</dt>
        <dd>{unresolved?.blocked_by ?? "None recorded on this plan."}</dd>
      </dl>
      <h3>Rationale</h3>
      {assignment ? <blockquote>{assignment.rationale}</blockquote> : <p className="empty">No assignment rationale for this household.</p>}
      <ThreadList title="Message thread" messages={messages} />
    </article>
  );
}

function FacilityInspector(props: { state: StateSnapshot; id: string }) {
  const facility = facilityById(props.state, props.id);
  if (!facility) return <p className="empty">That facility is not in the state snapshot.</p>;
  const assignment = assignmentForTarget(props.state, { facility_id: facility.id });
  const messages = props.state.messages.filter(
    (message) => "facility_id" in message.thread && message.thread.facility_id === facility.id,
  );
  return (
    <article>
      <h2>{facility.name}</h2>
      <p className="meta">
        {facility.type.replaceAll("_", " ")} · <span className={`pill ${facility.state}`}>{facility.state}</span>
        {facility.critical ? " · critical" : ""}
        {facility.synthetic ? " · synthetic placement" : ""}
      </p>
      <dl>
        <dt>Depends on</dt>
        <dd>{facility.depends_on.length > 0 ? facility.depends_on.join(", ") : "nothing"}</dd>
        <dt>Consequence</dt>
        <dd>{facility.consequence ?? "—"}</dd>
        <dt>Backup left</dt>
        <dd>{formatMinutes(facility.endurance_left_s)}</dd>
        <dt>Powered by</dt>
        <dd>{facility.powered_by ?? "—"}</dd>
        <dt>Threatened</dt>
        <dd>{formatMinutes(facility.threatened_at_s)}</dd>
        {facility.people_on_site != null ? (
          <>
            <dt>People on site</dt>
            <dd>{facility.people_on_site}{facility.capacity_people ? ` / ${facility.capacity_people}` : ""}</dd>
          </>
        ) : null}
      </dl>
      {facility.wastewater ? <WastewaterBlock water={facility.wastewater} /> : null}
      <h3>Rationale</h3>
      {assignment ? <blockquote>{assignment.rationale}</blockquote> : <p className="empty">No assignment targets this facility.</p>}
      <ThreadList title="Operator thread" messages={messages} />
    </article>
  );
}

function WastewaterBlock(props: { water: Wastewater }) {
  const water = props.water;
  return (
    <section>
      <h3>Wastewater</h3>
      <dl>
        <dt>Storage</dt>
        <dd>{formatNumber(water.storage_m3, 0)} / {formatNumber(water.storage_max_m3, 0)} m³</dd>
        <dt>Inflow now</dt>
        <dd>{formatNumber(water.inflow_m3ph, 0)} m³/h</dd>
        <dt>Pumped now</dt>
        <dd>{formatNumber(water.pumped_m3ph, 0)} m³/h</dd>
        <dt>Overflow</dt>
        <dd>{formatNumber(water.overflow_m3, 1)} m³</dd>
      </dl>
      <Spark series={water.series} />
    </section>
  );
}

function Spark(props: { series: Wastewater["series"] }) {
  const series = props.series;
  if (!series || series.overflow_m3.length < 2) return null;
  const values = series.overflow_m3;
  const max = Math.max(...values, 1);
  const width = 260;
  const height = 46;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - (value / max) * (height - 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <figure className="spark">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Cumulative overflow">
        <path d={path} />
      </svg>
      <figcaption>Cumulative overflow, from the state fixture.</figcaption>
    </figure>
  );
}

function ResourceInspector(props: { state: StateSnapshot; id: string }) {
  const resource = resourceById(props.state, props.id);
  if (!resource) return <p className="empty">That resource is not in the state snapshot.</p>;
  const assignment = assignmentById(props.state, resource.assignment_id);
  return (
    <article>
      <h2>{resource.name}</h2>
      <p className="meta">{resource.kind.replaceAll("_", " ")} · {statusLabel(resource.status)}</p>
      <dl>
        <dt>Assignment</dt>
        <dd>{assignment ? `${assignment.task} → ${targetLabel(assignment.target)}` : "none"}</dd>
        <dt>ETA</dt>
        <dd>{formatMinutes(resource.eta_s)}</dd>
        <dt>Fuel</dt>
        <dd>{formatNumber(resource.fuel_l, 1)} L{resource.km_driven != null ? ` · ${formatNumber(resource.km_driven, 2)} km` : ""}</dd>
        <dt>On board</dt>
        <dd>{resource.people_on_board ?? 0}{resource.capacity_people ? ` / ${resource.capacity_people}` : ""}</dd>
        {resource.kw ? (
          <>
            <dt>Generator</dt>
            <dd>{resource.kw} kW · {resource.connector ?? "no connector"}</dd>
          </>
        ) : null}
      </dl>
      <h3>Rationale</h3>
      {assignment ? <blockquote>{assignment.rationale}</blockquote> : <p className="empty">No rationale while this resource is unassigned.</p>}
    </article>
  );
}

function EdgeInspector(props: {
  edgeId: number;
  closures: Closure[];
  judge: JudgeClosure[];
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
}) {
  const edge = edgeRecord(props.edgeId);
  const closure = closureFor(props.closures, props.edgeId);
  const local = props.judge.some((item) => item.edge_id === props.edgeId);
  if (!edge) return <p className="empty">Edge {props.edgeId} is not in the town fixture.</p>;
  return (
    <article>
      <h2>{edge.name ?? "Unnamed road"}</h2>
      <p className="meta">{edge.highway} · edge {edge.id} · {formatNumber(edge.length_m, 0)} m</p>
      <dl>
        <dt>Closure</dt>
        <dd>
          {closure
            ? `${closure.source} from ${formatSim(closure.closed_from_t_s)}`
            : "open at this clock time"}
        </dd>
      </dl>
      {closure && !local ? (
        <p className="empty">This edge is already closed by the published {closure.source}.</p>
      ) : null}
      {!closure ? (
        <button className="primary" disabled={props.busy != null} onClick={() => props.onCloseRoad(edge.id)}>
          Close this road
        </button>
      ) : null}
      {local ? (
        <button className="ghost" onClick={() => props.onUndoClosure(edge.id)}>
          Undo local closure
        </button>
      ) : null}
    </article>
  );
}

function ThreadList(props: { title: string; messages: StateSnapshot["messages"] }) {
  return (
    <section>
      <h3>{props.title}</h3>
      {props.messages.length === 0 ? (
        <p className="empty">No messages in this thread.</p>
      ) : (
        <ol className="thread">
          {props.messages.map((message) => (
            <li key={message.id} className={message.direction}>
              <span>{message.direction === "out" ? "EMBER" : "Them"} · {formatSim(message.t_s)}</span>
              <p>{message.text}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Conversations(props: { state: StateSnapshot; t: number }) {
  const messages = props.state.messages.filter((message) => message.t_s <= props.t);
  const groups = new Map<string, { label: string; messages: typeof messages }>();
  for (const message of messages) {
    const key = threadKey(message.thread);
    const group = groups.get(key) ?? { label: threadLabel(message.thread), messages: [] };
    group.messages.push(message);
    groups.set(key, group);
  }
  const requests = props.state.plan?.info_requests ?? [];
  if (groups.size === 0 && requests.length === 0) {
    return <p className="empty">No resident or operator messages at this clock time.</p>;
  }
  return (
    <div className="stack">
      {[...groups.values()].map((group) => (
        <section key={group.label}>
          <h2>{group.label}</h2>
          <ol className="thread">
            {group.messages.map((message) => (
              <li key={message.id} className={message.direction}>
                <span>{message.direction === "out" ? "Out" : "In"} · plan v{message.plan_version ?? "—"} · {formatSim(message.t_s)}</span>
                <p>{message.text}</p>
              </li>
            ))}
          </ol>
        </section>
      ))}
      {requests.length > 0 ? (
        <section>
          <h2>Questions the plan still needs</h2>
          <ul className="needs">
            {requests.map((request) => (
              <li key={request.id}>
                <strong>{threadLabel(request.to)}</strong>
                <p>{request.question}</p>
                <p className="meta">{request.why}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Needs(props: { state: StateSnapshot }) {
  const unresolved = props.state.plan?.unresolved ?? [];
  if (unresolved.length === 0) {
    return <p className="empty">This plan has no unresolved needs.</p>;
  }
  return (
    <ul className="needs">
      {unresolved.map((item, index) => (
        <li key={`${targetLabel(item.target)}-${index}`}>
          <strong>{targetLabel(item.target)}</strong>
          <p>{item.need}</p>
          <p>Blocked by {item.blocked_by}</p>
          {item.would_unblock ? <p className="meta">Would unblock: {item.would_unblock}</p> : null}
        </li>
      ))}
    </ul>
  );
}

function Compare(props: {
  state: StateSnapshot;
  comparison: Comparison | null;
  busy: string | null;
  onCompare: () => void;
}) {
  const comparison = props.comparison;
  return (
    <div className="stack">
      <p className="meta">Spread, not confidence bounds.</p>
      <button className="primary" disabled={props.busy != null} onClick={props.onCompare}>
        {props.busy === "compare" ? "Running comparison…" : "Run comparison"}
      </button>
      {comparison ? (
        <table className="grid">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Baseline (A)</th>
              <th>EMBER (B)</th>
              <th>B − A</th>
            </tr>
          </thead>
          <tbody>
            {METRICS.map((metric) => {
              const a = comparison.baseline[metric.key];
              const b = comparison.ember[metric.key];
              const delta = typeof a === "number" && typeof b === "number" ? b - a : null;
              return (
                <tr key={metric.key}>
                  <td>{metric.label}</td>
                  <td>{typeof a === "number" ? `${formatNumber(a, metric.digits)} ${metric.unit}` : "—"}</td>
                  <td>{typeof b === "number" ? `${formatNumber(b, metric.digits)} ${metric.unit}` : "—"}</td>
                  <td>{delta == null ? "—" : formatNumber(delta, metric.digits)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="empty">
          No comparison fixture is published, and the backend has not returned one. A is baseline
          and B is EMBER once both sides arrive. The numbers below are this snapshot&apos;s plan only.
        </p>
      )}
      {comparison?.note ? <p className="meta">{comparison.note}</p> : null}
      <PlanMetricsBlock title="This snapshot" metrics={props.state.metrics} />
    </div>
  );
}

function PlanMetricsBlock(props: { title: string; metrics: PlanMetrics }) {
  return (
    <section>
      <h2>{props.title}</h2>
      <dl>
        {METRICS.map((metric) => {
          const value = props.metrics[metric.key];
          return (
            <span key={metric.key} className="metric-row">
              <dt>{metric.label}</dt>
              <dd>{typeof value === "number" ? `${formatNumber(value, metric.digits)} ${metric.unit}` : "—"}</dd>
            </span>
          );
        })}
      </dl>
      <p className="meta">{props.metrics.projected ? "Projected for the rest of the horizon." : "Outcome so far, not a projection."}</p>
    </section>
  );
}

function Scatter(props: { scatter: ScatterPoint[]; state: StateSnapshot }) {
  const points = props.scatter;
  const chosenId = props.state.plan ? `v${props.state.plan.version}` : null;
  if (points.length === 0) {
    return (
      <p className="empty">
        Robustness runs show up here as they arrive on <code>scatter_point</code>. Nothing has
        been streamed yet. The chosen plan is drawn as a ring.
      </p>
    );
  }
  const maxX = Math.max(...points.map((point) => point.overflowM3), 1);
  const maxY = Math.max(...points.map((point) => point.peopleUnreached), 1);
  const width = 280;
  const height = 180;
  const pad = 16;
  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Robustness scatter">
        {points.map((point) => {
          const x = pad + (point.overflowM3 / maxX) * (width - pad * 2);
          const y = height - pad - (point.peopleUnreached / maxY) * (height - pad * 2);
          const chosen = point.chosen || point.planId === chosenId;
          return (
            <circle
              key={point.id}
              cx={x}
              cy={y}
              r={chosen ? 6 : 3.5}
              className={chosen ? "chosen" : ""}
            />
          );
        })}
      </svg>
      <figcaption>People unreached (vertical) against overflow m³ (horizontal). Spread, not confidence bounds.</figcaption>
    </figure>
  );
}

function Plans(props: { plans: PlanSnapshot[]; onReplan: () => void; busy: string | null }) {
  const plans = [...props.plans].sort((a, b) => a.version - b.version);
  return (
    <div className="stack">
      <button className="primary" disabled={props.busy != null} onClick={props.onReplan}>
        {props.busy === "replan" ? "Replanning…" : "Replan"}
      </button>
      {plans.length === 0 ? <p className="empty">No plan versions yet.</p> : null}
      <ol className="versions">
        {plans.map((plan, index) => (
          <li key={plan.version}>
            <h2>
              {index === 0 && plan.parent_version
                ? `v${plan.parent_version} → v${plan.version}`
                : `v${plan.version}`}
            </h2>
            <p className="meta">
              {plan.planner ?? "planner"} · {formatSim(plan.created_at_t_s)}
              {plan.parent_version ? ` · parent v${plan.parent_version}` : ""}
            </p>
            {plan.trigger ? <p>{plan.trigger}</p> : null}
            {(plan.changes ?? []).length > 0 ? (
              <ul>
                {(plan.changes ?? []).map((change) => (
                  <li key={`${plan.version}-${change.assignment_id}-${change.change}`}>
                    {change.change} {change.assignment_id}
                    {change.note ? ` — ${change.note}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">No diff was published against the parent version.</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function snapshotNote(state: StateSnapshot): string {
  const source = state.source === "engine-example"
    ? "Engine example"
    : state.source === "simulator"
      ? "Simulator"
      : state.source === "backend"
        ? "Backend"
        : "Snapshot";
  return `${source} at ${formatSim(state.t_s)} · ${scenario.name}`;
}

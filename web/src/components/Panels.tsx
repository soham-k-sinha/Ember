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
import { robustOf } from "../live";
import { householdColor, peopleCount } from "../layers";
import { householdName, members, type WalkerPlan } from "../people";
import { householdTimeline, resourceTimeline, type Playback, type TimelineItem } from "../playback";
import type {
  Closure,
  Comparison,
  JudgeClosure,
  PlanMetrics,
  PlanSnapshot,
  RobustSummary,
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
  scatterTotal: number | null;
  plans: PlanSnapshot[];
  judge: JudgeClosure[];
  notice: string | null;
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
  onReplan: () => void;
  onCompare: () => void;
  onOptimize: () => void;
  playback: Playback | null;
  walkers: WalkerPlan | null;
  follow: Selection | null;
  onFollow: (selection: Selection | null) => void;
  onSelect: (selection: Selection | null) => void;
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

function Ledger(props: { state: StateSnapshot; onSelect: (selection: Selection | null) => void; onFollow: (selection: Selection | null) => void }) {
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
          <th>On board</th>
        </tr>
      </thead>
      <tbody>
        {resources.map((resource) => {
          const assignment = assignmentById(props.state, resource.assignment_id);
          return (
            <tr key={resource.id} className="clickable" onClick={() => props.onSelect({ kind: "resource", id: resource.id })}>
              <td>
                <strong>{resource.name}</strong>
                <span>{resource.kind.replaceAll("_", " ")}</span>
              </td>
              <td><span className={`pill ${resource.status}`}>{statusLabel(resource.status)}</span></td>
              <td>{assignment ? targetLabel(assignment.target) : "—"}</td>
              <td>{formatMinutes(resource.eta_s ?? assignment?.eta_s)}</td>
              <td>
                {resource.people_on_board ? `${resource.people_on_board} aboard` : "—"}
                <button
                  className="mini"
                  title="Follow on the map"
                  onClick={(event) => {
                    event.stopPropagation();
                    props.onFollow({ kind: "resource", id: resource.id });
                  }}
                >
                  Follow
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Inspector(props: {
  state: StateSnapshot;
  t: number;
  closures: Closure[];
  selection: Selection | null;
  judge: JudgeClosure[];
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
  playback: Playback | null;
  walkers: WalkerPlan | null;
  follow: Selection | null;
  onFollow: (selection: Selection | null) => void;
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
  const following = props.follow != null && props.follow.kind === selection.kind && props.follow.id === selection.id;
  const followButton = (
    <button className={following ? "ghost on" : "ghost"} onClick={() => props.onFollow(following ? null : selection)}>
      {following ? "Following · stop" : "Follow on map"}
    </button>
  );
  if (selection.kind === "household") {
    return <HouseholdInspector state={props.state} id={selection.id} t={props.t} playback={props.playback} follow={followButton} />;
  }
  if (selection.kind === "facility") return <FacilityInspector state={props.state} id={selection.id} />;
  if (selection.kind === "resource") {
    return <ResourceInspector state={props.state} id={selection.id} t={props.t} playback={props.playback} follow={followButton} />;
  }
  if (selection.kind === "walker") return <WalkerInspector id={selection.id} walkers={props.walkers} t={props.t} />;
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

function Countdown(props: { deadline: number | null; t: number }) {
  if (props.deadline == null) return <span className="countdown calm">Water does not reach them in this scenario</span>;
  const left = props.deadline - props.t;
  if (left <= 0) return <span className="countdown past">Water reached their street {formatSim(-left)} ago</span>;
  const tone = left < 30 * 60 ? "urgent" : left < 60 * 60 ? "soon" : "calm";
  return <span className={`countdown ${tone}`}>{formatSim(left)} until water reaches them</span>;
}

function Timeline(props: { items: TimelineItem[]; empty: string }) {
  if (props.items.length === 0) return <p className="empty">{props.empty}</p>;
  return (
    <ol className="timeline">
      {props.items.map((item, index) => (
        <li key={`${item.t_s}-${index}`} className={item.tone ?? ""}>
          <span>{formatSim(item.t_s)}</span>
          <p>{item.text}</p>
        </li>
      ))}
    </ol>
  );
}

function HouseholdInspector(props: { state: StateSnapshot; id: number; t: number; playback: Playback | null; follow: JSX.Element }) {
  const household = householdById(props.state, props.id);
  const townHousehold = town.households.find((item) => item.id === props.id);
  if (!household) {
    return (
      <article>
        <p className="kicker-small">Home · synthetic</p>
        <h2>{householdName(props.id)}</h2>
        <p className="empty">
          A home in the district{townHousehold ? ` (${townHousehold.size} people, zone ${townHousehold.zone})` : ""}. It is not in the
          assisted set, so the plan has no task for it. Some neighbours like this one leave on foot as the water rises (illustrative).
        </p>
      </article>
    );
  }
  const assignment = assignmentById(props.state, household.assignment_id)
    ?? assignmentForTarget(props.state, { household_id: household.household_id });
  const resource = assignment ? resourceById(props.state, assignment.resource_id) : undefined;
  const unresolved = props.state.plan?.unresolved.find(
    (item) => "household_id" in item.target && item.target.household_id === household.household_id,
  );
  const messages = props.state.messages.filter(
    (message) => "household_id" in message.thread && message.thread.household_id === household.household_id,
  );
  const needs = household.needs;
  const people = peopleCount(household, 2);
  const crew = members(
    household.household_id,
    people,
    needs !== "unknown" && Boolean(needs.mobility || needs.accessible_vehicle),
    needs !== "unknown" && Boolean(needs.medical),
  );
  const color = householdColor(household, "status", props.t);
  const outcome = props.playback?.outcomes.find((item) => item.assignment_id === assignment?.id);
  const timeline = props.playback ? householdTimeline(props.playback, household.household_id, props.t) : [];
  const fromMessages: TimelineItem[] = messages
    .filter((message) => message.t_s <= props.t)
    .map((message) => ({ t_s: message.t_s, text: `${message.direction === "out" ? "EMBER texted" : "They texted"}: “${message.text}”`, tone: "info" as const }));
  const items = [...timeline, ...fromMessages].sort((a, b) => a.t_s - b.t_s);
  return (
    <article className="profile">
      <header className="profile-head">
        <i className="avatar" style={{ background: `rgb(${color.join(",")})` }} />
        <div>
          <p className="kicker-small">{household.judge ? "Judge's household" : "Assisted household"} · #{household.household_id}</p>
          <h2>{household.label && !/^household/i.test(household.label) ? household.label : householdName(household.household_id)}</h2>
          <p className="meta">
            <span className={`pill ${household.status}`}>{statusLabel(household.status)}</span>
            {household.needs_source ? ` · needs from ${household.needs_source === "report" ? "their report" : "the scenario"}` : ""}
          </p>
        </div>
      </header>
      {props.follow}
      <Countdown deadline={household.deadline_s} t={props.t} />
      <section className="card">
        <dl>
          <dt>Needs</dt>
          <dd>{formatNeeds(household.needs)}</dd>
          <dt>Help</dt>
          <dd>
            {resource
              ? `${resource.name}${outcome?.arrive_t != null ? (outcome.arrive_t > props.t ? ` · arrives in ${formatSim(outcome.arrive_t - props.t)}` : " · arrived") : resource.eta_s != null ? ` · ETA ${formatMinutes(resource.eta_s)}` : ""}`
              : "No vehicle assigned"}
          </dd>
          {outcome?.pickup_t != null ? (
            <>
              <dt>Pickup</dt>
              <dd>{formatSim(outcome.pickup_t)}{outcome.met_deadline === false ? " · after the deadline" : outcome.met_deadline ? " · before the water" : ""}</dd>
            </>
          ) : null}
          <dt>Blocked by</dt>
          <dd>{unresolved?.blocked_by ?? "nothing on this plan"}</dd>
        </dl>
      </section>
      <section>
        <h3>Latest decision</h3>
        {assignment ? <blockquote>{assignment.rationale}</blockquote> : <p className="empty">The plan has no task for this household yet.</p>}
      </section>
      <section>
        <h3>Timeline</h3>
        <Timeline items={items} empty="Nothing has happened to this household yet at this clock time." />
      </section>
      <section>
        <h3>Who lives here · {crew.length} {crew.length === 1 ? "person" : "people"}</h3>
        <ul className="members">
          {crew.map((member) => (
            <li key={member.name}>
              <strong>{member.name}</strong>
              <span>{member.role}</span>
            </li>
          ))}
        </ul>
        <p className="meta">Names and members are generated from the household id (synthetic). Head count and mobility come from the plan's needs.</p>
      </section>
      <ThreadList title="Message thread" messages={messages} />
    </article>
  );
}

function WalkerInspector(props: { id: number; walkers: WalkerPlan | null; t: number }) {
  const group = props.walkers?.walkers.filter((walker) => walker.household === props.id) ?? [];
  const first = group[0];
  return (
    <article>
      <p className="kicker-small">Neighbour on foot · illustrative</p>
      <h2>{householdName(props.id)}</h2>
      {first ? (
        <dl>
          <dt>Group</dt>
          <dd>{group.length} {group.length === 1 ? "person" : "people"}</dd>
          <dt>Left home</dt>
          <dd>{formatSim(first.start)}</dd>
          <dt>Heading to</dt>
          <dd>{first.turnedBack ? "the edge of the water, then back home (took the direct route and found it flooded)" : first.dest === "shelter" ? "the Treehouse shelter" : "out of the district"}</dd>
          <dt>{first.end > props.t ? "Arrives" : "Arrived"}</dt>
          <dd>{formatSim(first.end)}</dd>
        </dl>
      ) : null}
      <p className="empty">
        People who can leave on their own are drawn so the scene reads like a neighbourhood. They are routed on the real streets around
        roads that will be under water by the time they reach them, but they are not part of the simulation or any metric.
      </p>
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
      <figcaption>Cumulative overflow on this snapshot.</figcaption>
    </figure>
  );
}

function ResourceInspector(props: { state: StateSnapshot; id: string; t: number; playback: Playback | null; follow: JSX.Element }) {
  const resource = resourceById(props.state, props.id);
  if (!resource) return <p className="empty">That resource is not in the state snapshot.</p>;
  const assignment = assignmentById(props.state, resource.assignment_id);
  const timeline = props.playback ? resourceTimeline(props.playback, resource.id, props.t) : [];
  return (
    <article className="profile">
      <header className="profile-head">
        <i className={`avatar vehicle ${resource.kind}`} />
        <div>
          <p className="kicker-small">{resource.kind.replaceAll("_", " ")}{resource.accessible ? " · accessible" : ""}</p>
          <h2>{resource.name}</h2>
          <p className="meta"><span className={`pill ${resource.status}`}>{statusLabel(resource.status)}</span></p>
        </div>
      </header>
      {props.follow}
      <section className="card">
        <dl>
          <dt>Task</dt>
          <dd>{assignment ? `${assignment.task} → ${targetLabel(assignment.target)}` : "none"}</dd>
          <dt>ETA</dt>
          <dd>{resource.eta_s != null ? (resource.eta_s > props.t ? `in ${formatSim(resource.eta_s - props.t)}` : formatMinutes(resource.eta_s)) : "—"}</dd>
          <dt>On board</dt>
          <dd>{resource.people_on_board ?? 0}{resource.capacity_people ? ` / ${resource.capacity_people}` : ""}</dd>
          <dt>Fuel</dt>
          <dd>{formatNumber(resource.fuel_l, 1)} L{resource.km_driven != null ? ` · ${formatNumber(resource.km_driven, 2)} km` : ""}</dd>
          {resource.kw ? (
            <>
              <dt>Generator</dt>
              <dd>{resource.kw} kW · {resource.connector ?? "no connector"}</dd>
            </>
          ) : null}
        </dl>
      </section>
      <section>
        <h3>Latest decision</h3>
        {assignment ? <blockquote>{assignment.rationale}</blockquote> : <p className="empty">No rationale while this resource is unassigned.</p>}
      </section>
      <section>
        <h3>Timeline</h3>
        <Timeline items={timeline} empty={props.playback ? "Nothing yet at this clock time." : "The timeline needs a replay (fixtures, or GET /playback in live mode)."} />
      </section>
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
  if (!props.state.plan) {
    return <p className="empty">No plan is loaded, so there is no unresolved-need list yet.</p>;
  }
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

function metricNumber(metrics: PlanMetrics, key: string): number | null {
  const value = metrics[key as keyof PlanMetrics];
  return typeof value === "number" ? value : null;
}

function digitsFor(value: number): number {
  return Number.isInteger(value) ? 0 : 1;
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
      <p className="meta">
        B − A is EMBER minus baseline
        {comparison ? ` · ${comparison.scenario_id}` : ""}.
        {" "}The seed range is spread, not a confidence bound.
      </p>
      {comparison && comparison.scenario_id !== scenario.scenario_id ? (
        <p className="meta">
          This table is the published {comparison.scenario_id} comparison. The map is {scenario.scenario_id} until Live returns GET /comparison.
        </p>
      ) : null}
      <button className="primary" disabled={props.busy != null} onClick={props.onCompare}>
        {props.busy === "compare" ? "Running comparison…" : "Run comparison"}
      </button>
      {comparison ? (
        <>
          <ul className="needs">
            {comparison.headline.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
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
              {comparison.metrics.map((metric) => {
                const baseline = metricNumber(comparison.nominal.baseline, metric.metric);
                const ember = metricNumber(comparison.nominal.ember, metric.metric);
                const delta = baseline != null && ember != null ? ember - baseline : metric.diff_mean;
                const digits = digitsFor(delta ?? ember ?? baseline ?? 0);
                return (
                  <tr key={metric.metric}>
                    <td>
                      {metric.label}
                      <span>
                        spread {formatNumber(metric.diff_min, digitsFor(metric.diff_min))} to {formatNumber(metric.diff_max, digitsFor(metric.diff_max))} {metric.unit}, not a confidence bound
                      </span>
                    </td>
                    <td>{baseline == null ? "—" : `${formatNumber(baseline, digits)} ${metric.unit}`}</td>
                    <td>{ember == null ? "—" : `${formatNumber(ember, digits)} ${metric.unit}`}</td>
                    <td>{delta == null ? "—" : `${formatNumber(delta, digits)} ${metric.unit}`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {comparison.notes.map((note) => (
            <p key={note} className="meta">{note}</p>
          ))}
        </>
      ) : (
        <p className="empty">No comparison is loaded. Nominal columns come from comparison.fixture.json.</p>
      )}
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

function Scatter(props: {
  scatter: ScatterPoint[];
  scatterTotal: number | null;
  state: StateSnapshot;
  busy: string | null;
  onOptimize: () => void;
}) {
  const points = props.scatter;
  const batch = points[0]?.batchId;
  const robust = robustOf(props.state.plan);
  const result = robust && (batch == null || robust.batch_id === batch) ? robust : null;
  return (
    <div className="stack">
      <button className="primary" disabled={props.busy != null} onClick={props.onOptimize}>
        {props.busy === "optimize"
          ? `Optimizing… ${points.length}${props.scatterTotal ? ` / ${props.scatterTotal}` : ""} runs`
          : "Optimize (robust replan)"}
      </button>
      <p className="meta">
        Top plan candidates and the baseline, each run in 20 perturbed worlds (travel times, flood timing, backup
        endurance, a vehicle failing) on Daytona sandboxes or the local pool. EMBER keeps the candidate with the best
        worst 20% of runs: people unreached, then overflow.
      </p>
      {points.length === 0 ? (
        <p className="empty">No runs yet. Optimize fills this chart live, one dot per run.</p>
      ) : (
        <ScatterChart points={points} total={props.scatterTotal} chosen={result?.chosen ?? null} />
      )}
      {result?.ranking ? <Ranking robust={result} /> : null}
    </div>
  );
}

function candidateClass(candidate: string, chosen: string | null): string {
  if (candidate === "baseline") return "baseline";
  if (candidate === chosen || candidate === "ember") return "chosen";
  return "candidate";
}

function ScatterChart(props: { points: ScatterPoint[]; total: number | null; chosen: string | null }) {
  const points = props.points;
  const maxX = Math.max(...points.map((point) => point.peopleUnreached), 1);
  const maxY = Math.max(...points.map((point) => point.overflowM3), 1);
  const width = 300;
  const height = 200;
  const left = 34;
  const bottom = 26;
  const pad = 10;
  const x = (v: number) => left + (v / maxX) * (width - left - pad);
  const y = (v: number) => height - bottom - (v / maxY) * (height - bottom - pad);
  // draw the chosen plan last so it sits on top
  const order = [...points].sort(
    (a, b) => Number(candidateClass(a.candidate, props.chosen) === "chosen") - Number(candidateClass(b.candidate, props.chosen) === "chosen"),
  );
  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Robustness scatter">
        <line className="axis" x1={left} y1={height - bottom} x2={width - pad} y2={height - bottom} />
        <line className="axis" x1={left} y1={pad} x2={left} y2={height - bottom} />
        <text className="tick" x={left} y={height - bottom + 12}>0</text>
        <text className="tick end" x={width - pad} y={height - bottom + 12}>{Math.round(maxX)}</text>
        <text className="tick end" x={left - 4} y={pad + 4}>{Math.round(maxY).toLocaleString("en-US")}</text>
        <text className="label" x={(left + width) / 2} y={height - 4}>people unreached →</text>
        <text className="label" transform={`translate(10 ${(height - bottom) / 2}) rotate(-90)`}>overflow m³ →</text>
        {order.map((point) => {
          const kind = candidateClass(point.candidate, props.chosen);
          return (
            <circle key={point.runId} cx={x(point.peopleUnreached)} cy={y(point.overflowM3)} r={kind === "chosen" ? 4.5 : 3.5} className={kind}>
              <title>{point.candidate} · seed {point.seed} · {point.peopleUnreached} unreached · {Math.round(point.overflowM3).toLocaleString("en-US")} m³</title>
            </circle>
          );
        })}
      </svg>
      <figcaption>
        <span className="key"><i className="dot chosen" /> {props.chosen ? `chosen (${props.chosen})` : "chosen (when done)"}</span>
        <span className="key"><i className="dot candidate" /> other candidates</span>
        <span className="key"><i className="dot baseline" /> baseline</span>
        <span>{points.length}{props.total ? ` / ${props.total}` : ""} runs in {points[0]?.batchId}. Spread, not confidence bounds.</span>
      </figcaption>
    </figure>
  );
}

function Ranking(props: { robust: RobustSummary }) {
  const r = props.robust;
  return (
    <section>
      <h3>Ranking · {r.jobs} runs on {r.pool}{r.fanout_wall_s != null ? ` in ${r.fanout_wall_s.toFixed(1)} s` : ""}</h3>
      <table className="grid">
        <thead>
          <tr><th>Plan</th><th>Worst 20%</th><th>Mean</th><th>Max</th><th>Overflow</th></tr>
        </thead>
        <tbody>
          {(r.ranking ?? []).map((row) => (
            <tr key={row.candidate} className={row.candidate === r.chosen ? "picked" : ""}>
              <td>
                {row.candidate}
                {row.candidate === r.chosen ? <span>chosen</span> : null}
                {row.candidate === r.nominal_best && row.candidate !== r.chosen ? <span>best on the forecast</span> : null}
              </td>
              <td>{row.worst20_people_unreached.toFixed(1)}</td>
              <td>{row.mean_people_unreached.toFixed(1)}</td>
              <td>{row.max_people_unreached}</td>
              <td>{Math.round(row.mean_overflow_m3).toLocaleString("en-US")} m³</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="meta">People unreached per run. Rule: {r.rule}.</p>
    </section>
  );
}

function Plans(props: {
  plans: PlanSnapshot[];
  comparison: Comparison | null;
  onReplan: () => void;
  busy: string | null;
}) {
  const fromCompare = props.comparison?.plans.ember.versions ?? [];
  const snapshots = new Map(props.plans.map((plan) => [plan.version, plan]));
  const rows = fromCompare.length > 0
    ? fromCompare.map((version) => ({
        version: version.version,
        t_s: version.t_s,
        trigger: version.trigger,
        changeCount: version.changes,
        wall_s: version.wall_s,
        changes: snapshots.get(version.version)?.changes ?? [],
        reserved: snapshots.get(version.version)?.reserved,
      }))
    : [...snapshots.values()].sort((a, b) => a.version - b.version).map((plan) => ({
        version: plan.version,
        t_s: plan.created_at_t_s,
        trigger: plan.trigger ?? "",
        changeCount: plan.changes?.length,
        wall_s: undefined as number | undefined,
        changes: plan.changes ?? [],
        reserved: plan.reserved,
      }));
  const known = new Set(rows.map((row) => row.version));
  for (const plan of snapshots.values()) {
    if (known.has(plan.version)) continue;
    rows.push({
      version: plan.version,
      t_s: plan.created_at_t_s,
      trigger: plan.trigger ?? "",
      changeCount: plan.changes?.length,
      wall_s: undefined,
      changes: plan.changes ?? [],
      reserved: plan.reserved,
    });
  }
  rows.sort((a, b) => a.version - b.version);

  return (
    <div className="stack">
      {props.comparison && props.comparison.scenario_id !== scenario.scenario_id ? (
        <p className="meta">
          Versions are from the {props.comparison.scenario_id} comparison record, not the map scenario.
        </p>
      ) : null}
      <button className="primary" disabled={props.busy != null} onClick={props.onReplan}>
        {props.busy === "replan" ? "Replanning…" : "Replan"}
      </button>
      {rows.length === 0 ? <p className="empty">No plan versions yet.</p> : null}
      <ol className="versions">
        {rows.map((row, index) => (
          <li key={row.version}>
            <h2>{index === 0 ? `v${row.version}` : `v${rows[index - 1].version} → v${row.version}`}</h2>
            <p className="meta">
              {formatSim(row.t_s)}
              {row.changeCount != null ? ` · ${row.changeCount} changes` : ""}
              {row.wall_s != null ? ` · ${row.wall_s.toFixed(2)} s` : ""}
            </p>
            {row.trigger ? <p>{row.trigger}</p> : null}
            {row.reserved && row.reserved.length > 0 ? <p className="meta">Reserved: {row.reserved.join(", ")}</p> : null}
            {row.changes.length > 0 ? (
              <ul>
                {row.changes.map((change) => (
                  <li key={`${row.version}-${change.assignment_id}-${change.change}`}>
                    {change.change} {change.assignment_id}
                    {change.note ? ` — ${change.note}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">No assignment diff was published for this version.</p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export function snapshotNote(state: StateSnapshot): string {
  const source = state.source === "scenario"
    ? "Scenario picture"
    : state.source === "engine-example"
      ? "Engine example"
      : state.source === "simulator"
        ? "Simulator"
        : state.source === "backend"
          ? "Backend"
          : "Snapshot";
  const name = state.scenario_id === scenario.scenario_id ? scenario.name : state.scenario_id;
  return `${source} at ${formatSim(state.t_s)} · ${name}`;
}

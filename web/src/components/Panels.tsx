import {
  formatMinutes,
  formatNeeds,
  formatNumber,
  formatSim,
  keptBeforeTradeoff,
  planDiff,
  planTiming,
  replanSeconds,
  reporterJob,
  statusLabel,
  targetLabel,
  tradedFacility,
} from "../format";
import {
  assignmentById,
  assignmentForTarget,
  closureFor,
  edgeRecord,
  facilityById,
  householdById,
  householdColor,
  peopleCount,
  resourceById,
  targetName,
} from "../model";
import { town } from "../fixtures";
import { robustOf } from "../live";
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
  Target,
  Wastewater,
} from "../types";

export type PanelId = "feed" | "plan" | "proof";

const TABS: Array<{ id: PanelId; label: string }> = [
  { id: "feed", label: "Feed" },
  { id: "plan", label: "Plan" },
  { id: "proof", label: "Proof" },
];

export function Panels(props: {
  tab: PanelId;
  onTab: (tab: PanelId) => void;
  state: StateSnapshot;
  t: number;
  closures: Closure[];
  selection: Selection | null;
  comparison: Comparison | null;
  nominal: { ember?: PlanMetrics; baseline?: PlanMetrics };
  scatter: ScatterPoint[];
  scatterTotal: number | null;
  robust: RobustSummary | null;
  plans: PlanSnapshot[];
  judge: JudgeClosure[];
  busy: string | null;
  onCloseRoad: (edgeId: number) => void;
  onUndoClosure: (edgeId: number) => void;
  onReplan: () => void;
  onCompare: () => void;
  onOptimize: (seeds?: number) => void;
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
      <div className="panel" role="tabpanel">
        {props.tab === "feed" ? <Feed {...props} /> : null}
        {props.tab === "plan" ? <PlanTab {...props} /> : null}
        {props.tab === "proof" ? <Proof {...props} /> : null}
      </div>
      {props.selection ? (
        <div className="drawer">
          <button className="close" onClick={() => props.onSelect(null)} aria-label="Close">×</button>
          <Inspector {...props} selection={props.selection} />
        </div>
      ) : null}
    </aside>
  );
}

type FeedItem = { key: string; t_s: number; kind: "in" | "fact" | "plan" | "out"; title: string; text: string; quote?: string; target?: Target };

/** The story in order: a text comes in → it becomes a fact → the plan changes → EMBER texts back. */
const ORDER: Record<FeedItem["kind"], number> = { in: 0, fact: 1, plan: 2, out: 3 };
const KIND_LABEL: Record<FeedItem["kind"], string> = { in: "Text in", fact: "Fact", plan: "New plan", out: "Text out" };

function feedItems(state: StateSnapshot, plans: PlanSnapshot[], playback: Playback | null, t: number): FeedItem[] {
  const items: FeedItem[] = [];
  for (const message of state.messages) {
    if (message.t_s > t) continue;
    const who = targetName(state, message.thread);
    items.push({ key: message.id, t_s: message.t_s, kind: message.direction, title: message.direction === "in" ? who : `EMBER → ${who}`, text: message.text, target: message.thread });
  }
  const seen = new Set<string>();
  const texted = new Set(state.messages.map((message) => message.report_id));
  for (const report of state.reports) {
    if (report.observed_at_t_s > t) continue;
    seen.add(report.id);
    const target: Target | undefined = report.household_id != null ? { household_id: report.household_id } : report.facility_id ? { facility_id: report.facility_id } : undefined;
    const needs = report.kind === "need" ? report.payload : undefined;
    items.push({ key: report.id, t_s: report.observed_at_t_s, kind: "fact", title: target ? targetName(state, target) : "Report", text: `${statusLabel(report.kind)}${needs ? ` · ${formatNeeds(needs)}` : ""}`, quote: texted.has(report.id) ? undefined : report.text, target });
  }
  for (const [index, report] of (playback?.reports ?? []).entries()) {
    const key = report.id ?? `pb-${index}`;
    if ((report.t_s ?? 0) > t || seen.has(key)) continue;
    const target: Target | undefined = report.household_id != null ? { household_id: report.household_id } : report.facility_id ? { facility_id: report.facility_id } : undefined;
    items.push({
      key,
      t_s: report.t_s ?? 0,
      kind: "fact",
      title: target ? targetName(state, target) : "Report",
      text: `${statusLabel(report.kind ?? "report")}${report.needs ? ` · ${formatNeeds(report.needs)}` : ""}`,
      quote: report.note ?? report.text,
      target,
    });
  }
  for (const plan of plans) {
    if (plan.created_at_t_s > t) continue;
    items.push({
      key: `plan-${plan.version}`,
      t_s: plan.created_at_t_s,
      kind: "plan",
      title: `v${plan.version} ${planTiming(plan)}`,
      // the reporter's own outcome leads when there is one; their fact is the row just below
      text: [reporterJob(plan, state) ? "" : plan.trigger, plan.version > 1 ? planDiff(plan, state) : ""].filter(Boolean).join(" → "),
    });
  }
  // newest first; at the same moment, later in the story first, then later arrivals first
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => b.item.t_s - a.item.t_s || ORDER[b.item.kind] - ORDER[a.item.kind] || b.index - a.index)
    .map(({ item }) => item);
}

function Feed(props: { state: StateSnapshot; plans: PlanSnapshot[]; playback: Playback | null; t: number; onSelect: (selection: Selection | null) => void }) {
  const items = feedItems(props.state, props.plans, props.playback, props.t);
  const unresolved = props.state.plan?.unresolved ?? [];
  const questions = props.state.plan?.info_requests ?? [];
  const open = unresolved.length + questions.length;
  return (
    <div className="stack">
      {open > 0 ? (
        <details className="open-needs">
          <summary>{open} open {open === 1 ? "need" : "needs"} the plan cannot meet yet</summary>
          <ul>
            {questions.map((request) => (
              <li key={request.id}>
                <strong>{targetName(props.state, request.to)}</strong> {request.question}
                <span>{request.why}</span>
              </li>
            ))}
            {unresolved.map((item, index) => (
              <li key={`${targetLabel(item.target)}-${index}`}>
                <strong>{targetName(props.state, item.target)}</strong> {item.need}
                <span>Blocked by {item.blocked_by}{item.would_unblock ? ` · would unblock: ${item.would_unblock}` : ""}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {items.length === 0 ? (
        <p className="empty">Nothing yet. When someone texts the EMBER line, their words, the fact EMBER takes from them and the new plan appear here.</p>
      ) : (
        <ol className="feed">
          {items.map((item) => (
            <li key={item.key} className={item.kind}>
              <button
                disabled={!item.target}
                onClick={() => item.target && props.onSelect("household_id" in item.target ? { kind: "household", id: item.target.household_id } : { kind: "facility", id: item.target.facility_id })}
              >
                <span>
                  {KIND_LABEL[item.kind]} · {item.title}
                  <time>{formatSim(item.t_s)}</time>
                </span>
                {item.quote ? <q>{item.quote}</q> : null}
                <p>{item.text}</p>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function PlanTab(props: { state: StateSnapshot; plans: PlanSnapshot[]; busy: string | null; onReplan: () => void; onSelect: (selection: Selection | null) => void; onFollow: (selection: Selection | null) => void }) {
  return (
    <div className="stack">
      <button className="primary" disabled={props.busy != null} onClick={props.onReplan}>
        {props.busy === "replan" ? "Replanning…" : "Replan now"}
      </button>
      <ol className="versions">
        {[...props.plans].reverse().map((plan) => {
          const seconds = replanSeconds(plan);
          const diff = plan.version > 1 ? planDiff(plan, props.state) : "";
          return (
            <li key={plan.version}>
              <header>
                <strong>v{plan.version}</strong>
                <span>{formatSim(plan.created_at_t_s)}</span>
                {seconds != null ? <span className="pill">{seconds.toFixed(2)} s</span> : null}
              </header>
              {plan.trigger ? <p>{plan.trigger}</p> : null}
              {diff ? <p className="meta">{diff}</p> : null}
            </li>
          );
        })}
      </ol>
      <h3>Vehicles</h3>
      <Ledger state={props.state} onSelect={props.onSelect} onFollow={props.onFollow} />
    </div>
  );
}

function Ledger(props: { state: StateSnapshot; onSelect: (selection: Selection | null) => void; onFollow: (selection: Selection | null) => void }) {
  return (
    <table className="grid">
      <thead>
        <tr>
          <th>Vehicle</th>
          <th>Status</th>
          <th>Job</th>
          <th>ETA</th>
        </tr>
      </thead>
      <tbody>
        {props.state.resources.map((resource) => {
          const assignment = assignmentById(props.state, resource.assignment_id);
          return (
            <tr key={resource.id} className="clickable" onClick={() => props.onSelect({ kind: "resource", id: resource.id })}>
              <td>
                <strong>{resource.name}</strong>
                <span>{resource.people_on_board ? `${resource.people_on_board} aboard` : resource.kind.replaceAll("_", " ")}</span>
              </td>
              <td><span className={`pill ${resource.status}`}>{statusLabel(resource.status)}</span></td>
              <td>{assignment ? targetName(props.state, assignment.target) : "—"}</td>
              <td>
                {formatMinutes(resource.eta_s ?? assignment?.eta_s)}
                <button
                  className="mini"
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
  selection: Selection;
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
  const color = householdColor(household);
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


const PROOF_METRICS: Array<{ metric: "people_reached_before_deadline" | "people_unreached" | "hospital_outage_s" | "overflow_m3" | "vehicle_km"; label: string; unit: string }> = [
  { metric: "people_reached_before_deadline", label: "Reached before the water", unit: "people" },
  { metric: "people_unreached", label: "Not reached in time", unit: "people" },
  { metric: "hospital_outage_s", label: "Hospital outage", unit: "min" },
  { metric: "overflow_m3", label: "Sewage overflow to the Charles", unit: "m³" },
  { metric: "vehicle_km", label: "Vehicle-km driven", unit: "km" },
];

function Proof(props: {
  t: number;
  plans: PlanSnapshot[];
  robust: RobustSummary | null;
  comparison: Comparison | null;
  nominal: { ember?: PlanMetrics; baseline?: PlanMetrics };
  scatter: ScatterPoint[];
  scatterTotal: number | null;
  busy: string | null;
  onCompare: () => void;
  onOptimize: (seeds?: number) => void;
}) {
  const comparison = props.comparison;
  const rows = PROOF_METRICS.map(({ metric, label, unit }) => {
    const row = comparison?.metrics.find((item) => item.metric === metric);
    const scale = metric === "hospital_outage_s" ? 1 / 60 : 1;
    return row
      ? { metric, label, unit, baseline: row.baseline_mean * scale, ember: row.ember_mean * scale, spread: `EMBER − baseline: ${formatNumber(row.diff_min * scale)} to ${formatNumber(row.diff_max * scale)}` }
      : { metric, label, unit, baseline: (props.nominal.baseline?.[metric] ?? 0) * scale, ember: (props.nominal.ember?.[metric] ?? 0) * scale, spread: "" };
  });
  const plan = props.plans[props.plans.length - 1];
  const kept = tradedFacility(plan) ? keptBeforeTradeoff(plan) : undefined;
  const points = props.scatter;
  const robust = props.robust;
  const result = robust && (points.length === 0 || robust.batch_id === points[0].batchId) ? robust : null;
  // at t = 0 nothing has happened yet: the stress test picks the plan to stage before the season
  const optimizeLabel = props.t === 0 ? "Pre-season stress test" : "Optimize";
  return (
    <div className="stack">
      <section>
        <header className="section-head">
          <h3>EMBER vs baseline</h3>
          <button className="ghost" disabled={props.busy != null} onClick={props.onCompare}>
            {props.busy === "compare" ? "Running…" : "Run comparison"}
          </button>
        </header>
        <table className="grid">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Baseline</th>
              <th>EMBER</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric}>
                <td>
                  {row.label}
                  {row.spread ? <span>{row.spread}</span> : null}
                  {row.metric === "overflow_m3" && kept != null ? <span>{formatNumber(kept)} m³ kept out before the hospital call</span> : null}
                </td>
                <td>{formatNumber(row.baseline, 0)} {row.unit}</td>
                <td><strong>{formatNumber(row.ember, 0)}</strong> {row.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="meta">
          {comparison
            ? `Mean of ${comparison.seeds?.length ?? "?"} perturbed worlds; the spread is a range, not a confidence bound.`
            : "The forecast world only. Run the comparison (Live) for perturbed worlds."}
        </p>
      </section>
      <section>
        <header className="section-head">
          <h3>Stress test{result ? ` · ${result.pool === "daytona" ? `Daytona · ${result.workers ?? "?"} sandboxes` : "this laptop"}` : ""}</h3>
        </header>
        <div className="actions">
          <button className="primary" disabled={props.busy != null} onClick={() => props.onOptimize()}>
            {props.busy === "optimize" ? "Running…" : optimizeLabel}
          </button>
          <button className="ghost" disabled={props.busy != null} onClick={() => props.onOptimize(2000)}>
            {props.busy === "stress" ? "Running…" : "Stress test 10,000 worlds"}
          </button>
        </div>
        {props.busy === "optimize" || props.busy === "stress" ? (
          <p className="throughput">{formatNumber(points.length)}{props.scatterTotal ? ` / ${formatNumber(props.scatterTotal)}` : ""} worlds back</p>
        ) : result ? (
          <Throughput robust={result} />
        ) : (
          <p className="throughput">
            Press {optimizeLabel} to stress-test this plan on 250 worlds (5 plans × 50), or on 10,000: the top candidate plans and the baseline, with travel times, flood timing, backup endurance and a vehicle failing perturbed.
          </p>
        )}
        {points.length > 0 ? <ScatterChart points={points} chosen={result?.chosen ?? null} /> : null}
        {result?.ranking ? <Verdict robust={result} preSeason={(props.plans.find((item) => robustOf(item)?.batch_id === result.batch_id)?.created_at_t_s ?? props.t) === 0} /> : null}
      </section>
    </div>
  );
}

/** Fan-out wall time of the same worlds on 8 local processes, measured once (D86); shown next to a Daytona run. */
const LAPTOP_S: Record<number, number> = { 250: 2.3, 1000: 4.5, 5000: 13.7, 10000: 24.3 };

function Throughput(props: { robust: RobustSummary }) {
  const r = props.robust;
  const laptop = r.laptop_s ?? LAPTOP_S[r.jobs];
  return (
    <p className="throughput tile">
      <strong>{formatNumber(r.jobs)} worlds</strong>
      <span>
        {r.pool === "daytona" ? `Daytona ${r.workers ?? "?"} sandboxes` : `this laptop, ${r.workers ?? "?"} workers`} <b>{formatNumber(r.fanout_wall_s, 1)} s</b>
        {r.startup_s ? ` (+${formatNumber(r.startup_s, 1)} s startup)` : ""}
      </span>
      {r.pool === "daytona" && laptop != null ? <span>laptop <b>~{formatNumber(laptop)} s</b> measured</span> : null}
    </p>
  );
}

function Verdict(props: { robust: RobustSummary; preSeason: boolean }) {
  const r = props.robust;
  const worst = (candidate: string) => r.ranking?.find((row) => row.candidate === candidate)?.worst20_people_unreached;
  const top = r.ranking?.find((row) => row.candidate !== "baseline")?.candidate;
  const pre = props.preSeason && r.nominal_best !== r.chosen;
  const rows: Array<{ label: string; value?: number; tone: string }> = [
    { label: `${pre ? "Robust pick" : "Chosen"} · ${r.chosen}`, value: worst(r.chosen), tone: "chosen" },
    ...(r.nominal_best !== r.chosen ? [{ label: `${pre ? "Forecast plan" : "Best on the forecast"} · ${r.nominal_best}`, value: worst(r.nominal_best), tone: "candidate" }] : []),
    // D86: the most robust candidate may win by less than 1 person; then the forecast plan is kept and both are shown
    ...(top && top !== r.chosen && top !== r.nominal_best ? [{ label: `Most robust · ${top}`, value: worst(top), tone: "candidate" }] : []),
    { label: "Baseline", value: worst("baseline"), tone: "baseline" },
  ];
  return (
    <>
      <ul className="verdict">
        {rows.map((row) => (
          <li key={row.label} className={row.tone}>
            <span>{row.label}</span>
            <strong>{formatNumber(row.value, 1)}</strong>
          </li>
        ))}
      </ul>
      <p className="meta">People not reached in the worst 20% of {r.seeds} worlds. {pre ? `Pre-season, before any report: staging the robust pick leaves ${formatNumber((worst(r.nominal_best) ?? 0) - (worst(r.chosen) ?? 0), 1)} fewer people unreached in the worst 20% than the forecast plan.` : r.nominal_best !== r.chosen ? "EMBER keeps the plan that holds up when things go wrong, not the one that looks best on the forecast." : "Kept the forecast plan: no candidate beats it by ≥ 1 person in the worst 20%."}</p>
    </>
  );
}

const CLASSES = ["candidate", "baseline", "chosen"] as const;

/** One path per class, not one element per run, and one dot per pixel: 10,000 runs land on a few hundred pixels, so
 * they stay cheap to redraw as they stream in while the caption counts every run. */
function ScatterChart(props: { points: ScatterPoint[]; chosen: string | null }) {
  const width = 320;
  const height = 190;
  const left = 34;
  const bottom = 26;
  const pad = 10;
  let maxX = 1;
  let maxY = 1;
  for (const point of props.points) {
    maxX = Math.max(maxX, point.peopleUnreached);
    maxY = Math.max(maxY, point.overflowM3);
  }
  const paths: Record<(typeof CLASSES)[number], string> = { candidate: "", baseline: "", chosen: "" };
  const drawn = new Set<string>();
  for (const point of props.points) {
    const kind = point.candidate === "baseline" ? "baseline" : point.candidate === props.chosen || point.candidate === "ember" ? "chosen" : "candidate";
    const r = kind === "chosen" ? 3.5 : 2.8;
    const cx = Math.round(left + (point.peopleUnreached / maxX) * (width - left - pad));
    const cy = Math.round(height - bottom - (point.overflowM3 / maxY) * (height - bottom - pad));
    const key = `${kind} ${cx} ${cy}`;
    if (drawn.has(key)) continue;
    drawn.add(key);
    paths[kind] += `M${(cx - r).toFixed(1)} ${cy.toFixed(1)}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
  }
  return (
    <figure className="scatter">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Robustness scatter: one dot per simulated world">
        <line className="axis" x1={left} y1={height - bottom} x2={width - pad} y2={height - bottom} />
        <line className="axis" x1={left} y1={pad} x2={left} y2={height - bottom} />
        <text className="tick" x={left} y={height - bottom + 12}>0</text>
        <text className="tick end" x={width - pad} y={height - bottom + 12}>{Math.round(maxX)}</text>
        <text className="tick end" x={left - 4} y={pad + 4}>{maxY.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 })}</text>
        <text className="label" x={(left + width) / 2} y={height - 4}>people not reached →</text>
        <text className="label" transform={`translate(10 ${(height - bottom) / 2}) rotate(-90)`}>overflow m³ →</text>
        {CLASSES.map((kind) => (
          <path key={kind} className={kind} d={paths[kind]} />
        ))}
      </svg>
      <figcaption>
        <span className="key"><i className="dot chosen" /> {props.chosen ? `chosen (${props.chosen})` : "chosen"}</span>
        <span className="key"><i className="dot candidate" /> other candidates</span>
        <span className="key"><i className="dot baseline" /> baseline</span>
        <span>{formatNumber(props.points.length)} worlds</span>
      </figcaption>
    </figure>
  );
}

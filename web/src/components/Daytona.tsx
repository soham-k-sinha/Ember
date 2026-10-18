/** Daytona view: the stress test as a path (this laptop → the sandboxes → every world → the verdict), with its numbers. */

import { formatNumber } from "../format";
import { robustOf } from "../live";
import type { PlanSnapshot, RobustSummary, ScatterPoint } from "../types";
import { Icon } from "./Icon";

/** Fan-out wall time of the same worlds on 8 local processes, measured once (D86); shown next to a Daytona run. */
const LAPTOP_S: Record<number, number> = { 250: 2.3, 1000: 4.5, 5000: 13.7, 10000: 24.3 };

/** Cells drawn before the first run has reported its pool size. */
const DEFAULT_CELLS = 90;

export function DaytonaView(props: {
  t: number;
  plans: PlanSnapshot[];
  robust: RobustSummary | null;
  scatter: ScatterPoint[];
  scatterTotal: number | null;
  busy: string | null;
  onOptimize: (seeds?: number) => void;
}) {
  const points = props.scatter;
  const running = props.busy === "optimize" || props.busy === "stress";
  const result = props.robust && (points.length === 0 || props.robust.batch_id === points[0].batchId) ? props.robust : null;
  const daytona = !result || result.pool === "daytona";
  const total = running ? props.scatterTotal : result?.jobs ?? props.scatterTotal;
  const laptop = result ? result.laptop_s ?? LAPTOP_S[result.jobs] : undefined;
  // the pool keeps its size between batches: a running batch shows the last one's
  const workers = result?.workers ?? props.robust?.workers;
  // at t = 0 nothing has happened yet: the stress test picks the plan to stage before the season
  const optimizeLabel = props.t === 0 ? "Pre-season stress test" : "Optimize";
  const preSeason = result != null && (props.plans.find((item) => robustOf(item)?.batch_id === result.batch_id)?.created_at_t_s ?? props.t) === 0;
  return (
    <section className="view" aria-label="Daytona stress test">
      <header className="view-head">
        <h2>Daytona <span>stress test</span></h2>
        <div className="actions">
          <button className="primary" disabled={props.busy != null} onClick={() => props.onOptimize()}>
            {props.busy === "optimize" ? "Running…" : optimizeLabel}
          </button>
          <button className="ghost" disabled={props.busy != null} onClick={() => props.onOptimize(2000)}>
            {props.busy === "stress" ? "Running…" : "Large stress test"}
          </button>
        </div>
      </header>
      <div className="bignums">
        <Big label="worlds" value={running ? `${formatNumber(points.length)}` : formatNumber(total)} sub={running && total ? `of ${formatNumber(total)}` : undefined} />
        <Big label={daytona ? "Daytona sandboxes" : "laptop workers"} value={formatNumber(workers)} tone={daytona ? "accent" : "bad"} />
        <Big label="fan-out" value={result?.fanout_wall_s != null ? `${formatNumber(result.fanout_wall_s, 1)} s` : "—"} sub={result?.startup_s ? `+${formatNumber(result.startup_s, 1)} s startup` : undefined} />
        <Big label="same worlds, laptop" value={daytona && laptop != null ? `~${formatNumber(laptop)} s` : "—"} sub={daytona && laptop != null ? "measured (D86)" : undefined} />
      </div>
      {!daytona ? <p className="warn" title={result?.fallback_reason}>Ran on this laptop: Daytona unavailable</p> : null}
      <div className="flow three">
        <Stage icon="laptop" title="This laptop" value={total ? formatNumber(total) : "—"} caption="worlds sent" />
        <Wire on={running} />
        <SandboxGrid cells={workers ?? DEFAULT_CELLS} known={workers != null} points={points} total={total} running={running} done={!running && result != null} daytona={daytona} />
        <Wire on={running} />
        <div className="stage-node">
          <h4><Icon name="check" /> Verdict</h4>
          {result?.ranking ? <Verdict robust={result} preSeason={preSeason} /> : <p className="hint">Worst 20% of worlds decides</p>}
        </div>
      </div>
      <div className="stage-node">
        <h4><Icon name="dots" /> Every world · {formatNumber(points.length)}</h4>
        {points.length > 0 ? <ScatterChart points={points} chosen={result?.chosen ?? null} /> : <p className="hint">Each dot: one simulated night</p>}
      </div>
    </section>
  );
}

function Big(props: { label: string; value: string; sub?: string; tone?: "accent" | "bad" }) {
  return (
    <div className={`big ${props.tone ?? ""}`}>
      <strong>{props.value}</strong>
      <span>{props.label}</span>
      {props.sub ? <i>{props.sub}</i> : null}
    </div>
  );
}

function Stage(props: { icon: string; title: string; value: string; caption: string }) {
  return (
    <div className="stage-node">
      <h4><Icon name={props.icon} /> {props.title}</h4>
      <strong className="node-num">{props.value}</strong>
      <span className="hint">{props.caption}</span>
    </div>
  );
}

/** A connector between two stages; a dot runs along it while work is in flight. */
export function Wire(props: { on: boolean; pulse?: string | number }) {
  return (
    <i className={props.on ? "wire on" : "wire"} aria-hidden>
      {props.pulse != null ? <b key={props.pulse} /> : null}
    </i>
  );
}

/** One cell per sandbox, filling as worlds come back: the k-th result back lights cell k mod the pool size; a finished
 * batch (also one from before this page loaded, whose runs were not streamed here) is all lit. */
function SandboxGrid(props: { cells: number; known: boolean; points: ScatterPoint[]; total: number | null; running: boolean; done: boolean; daytona: boolean }) {
  const share = Math.max(1, (props.total ?? props.points.length) / props.cells);
  const done = new Array<number>(props.cells).fill(props.done ? share : 0);
  if (!props.done) props.points.forEach((_, index) => (done[index % props.cells] += 1));
  return (
    <div className="stage-node grid-node">
      <h4><Icon name="cloud" /> {props.daytona ? "Daytona sandboxes" : "Laptop workers"}{props.known ? ` · ${props.cells}` : ""}</h4>
      <div className={props.running ? "cells running" : "cells"} style={{ gridTemplateColumns: `repeat(${Math.ceil(Math.sqrt(props.cells * 2.5))}, 1fr)` }}>
        {done.map((n, index) => (
          <i key={index} style={{ opacity: n === 0 ? undefined : 0.35 + 0.65 * Math.min(1, n / share) }} className={n > 0 ? "lit" : ""} />
        ))}
      </div>
    </div>
  );
}

function Verdict(props: { robust: RobustSummary; preSeason: boolean }) {
  const r = props.robust;
  const worst = (candidate: string) => r.ranking?.find((row) => row.candidate === candidate)?.worst20_people_unreached;
  const top = r.ranking?.find((row) => row.candidate !== "baseline")?.candidate;
  const pre = props.preSeason && r.nominal_best !== r.chosen;
  const rows: Array<{ label: string; value?: number; tone: string }> = [
    { label: `${pre ? "Robust pick" : "Chosen"} · ${r.chosen}`, value: worst(r.chosen), tone: "chosen" },
    ...(r.nominal_best !== r.chosen ? [{ label: `Forecast · ${r.nominal_best}`, value: worst(r.nominal_best), tone: "candidate" }] : []),
    // D86: the most robust candidate may win by less than 1 person; then the forecast plan is kept and both are shown
    ...(top && top !== r.chosen && top !== r.nominal_best ? [{ label: `Most robust · ${top}`, value: worst(top), tone: "candidate" }] : []),
    { label: "Baseline", value: worst("baseline"), tone: "baseline" },
  ];
  return (
    <>
      <ul className="verdict">
        {rows.map((row) => (
          <li key={row.label} className={row.tone}>
            <strong>{formatNumber(row.value, 1)}</strong>
            <span>{row.label}</span>
          </li>
        ))}
      </ul>
      <p className="hint">people missed · worst 20% of {formatNumber(r.seeds)} worlds</p>
    </>
  );
}

const CLASSES = ["candidate", "baseline", "chosen"] as const;

/** One path per class, not one element per run, and one dot per pixel: 10,000 runs land on a few hundred pixels, so
 * they stay cheap to redraw as they stream in while the caption counts every run. */
function ScatterChart(props: { points: ScatterPoint[]; chosen: string | null }) {
  const width = 560;
  const height = 200;
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
        <text className="label" x={(left + width) / 2} y={height - 4}>people missed →</text>
        <text className="label" transform={`translate(10 ${(height - bottom) / 2}) rotate(-90)`}>overflow m³ →</text>
        {CLASSES.map((kind) => (
          <path key={kind} className={kind} d={paths[kind]} />
        ))}
      </svg>
      <figcaption>
        <span className="key"><i className="dot chosen" /> {props.chosen ?? "chosen"}</span>
        <span className="key"><i className="dot candidate" /> others</span>
        <span className="key"><i className="dot baseline" /> baseline</span>
      </figcaption>
    </figure>
  );
}

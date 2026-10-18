/** Photon · multiplayer view: how a caller's words become a new plan, as a live path, with the join card and every player. */

import { useEffect, useMemo, useState, type FormEvent } from "react";
import qrcode from "qrcode-generator";
import { postJson } from "../live";
import { formatNeeds, maskHandle, phoneLabel, planDiff, replanSeconds, shortName, statusLabel } from "../format";
import { assignmentById, assignmentForTarget, resourceById, streetAt, targetName } from "../model";
import type { Calls, Phone, PlanSnapshot, StateSnapshot } from "../types";
import { Wire } from "./Daytona";
import { Icon } from "./Icon";

function QrCode(props: { text: string; label: string }) {
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
    <svg className="qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={props.label} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#0b0e14" />
    </svg>
  );
}

type Joined = { handle: string; player: number; assigned_number: string };

/** Call the EMBER number from any phone (D100/D108); or, by iMessage (D89), enter a number first (POST /join), then text
 * JOIN EMBER to the line it returns; that first text places them. */
function Join(props: { apiBase: string | null; phones: Phone[]; state: StateSnapshot; voiceNumber: string | null }) {
  const [handle, setHandle] = useState("");
  const [joined, setJoined] = useState<Joined | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const reset = () => {
    setJoined(null);
    setHandle("");
  };
  // their first text placed them: say where they live for 5 s, then the card is ready for the next phone
  const placed = joined ? props.phones.find((phone) => phone.handle === joined.handle)?.household_id ?? null : null;
  const home = props.state.households.find((item) => item.household_id === placed);
  const street = home ? streetAt(home.node) : undefined;
  useEffect(() => {
    if (placed == null) return;
    const timer = window.setTimeout(reset, 5000);
    return () => window.clearTimeout(timer);
  }, [placed]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!props.apiBase || !handle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setJoined((await postJson(`${props.apiBase}/join`, { handle: handle.trim() }, 15000)) as Joined);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Join failed";
      setError(text.startsWith("409") && text.includes("full") ? "The simulation is full." : text.startsWith("422") ? "Enter a mobile number, e.g. +1 617 555 0123." : text);
    } finally {
      setBusy(false);
    }
  };
  if (!props.apiBase) return <div className="join"><p className="hint">Live mode only</p></div>;
  if (joined && placed != null) {
    return <div className="join"><p className="join-done">Player {joined.player} · #{placed}{street ? ` · ${street}` : ""}</p></div>;
  }
  if (joined) {
    return (
      <div className="join">
        <QrCode text={`sms:${joined.assigned_number}?&body=JOIN%20EMBER`} label="QR code: text JOIN EMBER to the EMBER line" />
        <p className="join-call">Text <b>JOIN EMBER</b><span>to {joined.assigned_number}</span></p>
        <button className="join-again" onClick={reset}>Another phone</button>
      </div>
    );
  }
  return (
    <div className="join">
      {props.voiceNumber ? (
        <>
          <QrCode text={`tel:${props.voiceNumber}`} label={`QR code: call ${phoneLabel(props.voiceNumber)}`} />
          <p className="join-call"><span>Call</span><b>{phoneLabel(props.voiceNumber)}</b><span>any phone</span></p>
        </>
      ) : null}
      <details className="join-imessage" open={!props.voiceNumber}>
        <summary>iMessage instead</summary>
        <form className="join-form" onSubmit={submit}>
          <input type="tel" inputMode="tel" autoComplete="tel" placeholder="+1 617 555 0123" value={handle} onChange={(event) => setHandle(event.target.value)} aria-label="Your mobile number" />
          <button type="submit" disabled={busy || !handle.trim()}>{busy ? "…" : "Join"}</button>
          {error ? <p className="join-error">{error}</p> : null}
        </form>
      </details>
    </div>
  );
}

/** A compact join badge over the Live stage: the number, its QR and the head count; opens the Photon view. */
export function JoinBadge(props: { voiceNumber: string | null; players: number; max: number; onOpen: () => void }) {
  if (!props.voiceNumber) return null;
  return (
    <button className="join-badge" onClick={props.onOpen} aria-label="Join: open the Photon view">
      <QrCode text={`tel:${props.voiceNumber}`} label={`QR code: call ${phoneLabel(props.voiceNumber)}`} />
      <span>
        <small>Call to join</small>
        <b>{phoneLabel(props.voiceNumber)}</b>
        <small>{props.players}/{props.max} players</small>
      </span>
    </button>
  );
}

const PHONE_ROWS = 5;

const clip = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

export function PhotonView(props: {
  apiBase: string | null;
  phones: Phone[];
  calls: Calls;
  state: StateSnapshot;
  plans: PlanSnapshot[];
  t: number;
  max: number;
  voiceNumber: string | null;
  reader: string | null;
  onShow: (householdId: number) => void;
}) {
  const { state } = props;
  const players = props.phones.filter((phone) => phone.player != null).sort((a, b) => a.player! - b.player!);
  const onCall = new Map(props.calls.live.map((call) => [call.handle, call]));
  const messages = state.messages.filter((message) => message.t_s <= props.t);
  const inbound = messages.filter((message) => message.direction === "in");
  const outbound = messages.filter((message) => message.direction === "out");
  const lastIn = inbound[inbound.length - 1];
  // each player's last words: what they said on the call, else their last text
  const lastWords = new Map<number, string>();
  for (const message of inbound) if ("household_id" in message.thread) lastWords.set(message.thread.household_id, message.text);
  const lastOut = outbound[outbound.length - 1];
  const reports = state.reports.filter((report) => report.observed_at_t_s <= props.t);
  const lastFact = reports[reports.length - 1];
  const plan = props.plans[props.plans.length - 1];
  const seconds = plan ? replanSeconds(plan) : null;
  const factText = lastFact ? `${statusLabel(lastFact.kind)}${lastFact.kind === "need" && lastFact.payload ? ` · ${formatNeeds(lastFact.payload)}` : ""}` : "—";
  return (
    <section className="view" aria-label="Photon multiplayer">
      <header className="view-head">
        <h2>Photon <span>· multiplayer</span></h2>
        <p className="view-count"><b>{players.length}</b>/{props.max} players · <b>{props.calls.live.length}</b> on call</p>
      </header>
      <div className="photon-top">
        <Join apiBase={props.apiBase} phones={props.phones} state={state} voiceNumber={props.voiceNumber} />
        <div className="flow five">
          <div className="stage-node">
            <h4><Icon name="phone" /> Phones</h4>
            <ol className="phones">
              {players.length === 0 ? <li className="hint">waiting for callers</li> : null}
              {players.slice(0, PHONE_ROWS).map((phone) => {
                const call = onCall.get(phone.handle);
                const words = call?.heard ?? lastWords.get(phone.household_id ?? -1);
                return (
                  <li key={phone.handle} className={call ? "on-call" : ""}>
                    <i>{phone.player}</i>
                    {words ? <q>{words}</q> : <span className="hint">{maskHandle(phone.handle)}</span>}
                  </li>
                );
              })}
              {players.length > PHONE_ROWS ? <li className="hint">+{players.length - PHONE_ROWS} more</li> : null}
            </ol>
          </div>
          <Wire on={props.calls.live.length > 0} pulse={lastIn?.id} />
          <div className="stage-node">
            <h4><Icon name="signal" /> Photon</h4>
            <strong className="node-num">{props.calls.live.length}</strong>
            <span className="hint">calls live · {inbound.length} in</span>
          </div>
          <Wire on={false} pulse={lastIn?.id} />
          <div className="stage-node">
            <h4><Icon name="read" /> AI reads</h4>
            <strong className="node-text">{props.reader ?? "keyword parser"}</strong>
            <span className="hint" key={lastFact?.id}>{clip(factText, 44)}</span>
          </div>
          <Wire on={false} pulse={lastFact?.id} />
          <div className="stage-node flash" key={plan?.version}>
            <h4><Icon name="route" /> Planner</h4>
            <strong className="node-num">v{plan?.version ?? "—"}</strong>
            <span className="hint">{seconds != null ? `replanned in ${seconds.toFixed(1)} s` : "deterministic"}</span>
            {plan && plan.version > 1 ? <span className="node-diff">{clip(planDiff(plan, state), 60)}</span> : null}
          </div>
          <Wire on={false} pulse={lastOut?.id} />
          <div className="stage-node">
            <h4><Icon name="send" /> Told</h4>
            <strong className="node-num">{outbound.length}</strong>
            <span className="hint">{lastOut ? `→ ${targetName(state, lastOut.thread)}` : "calls · texts out"}</span>
          </div>
        </div>
      </div>
      {players.length > 0 ? (
        <ol className="players">
          {players.map((phone) => (
            <PlayerCard key={phone.handle} phone={phone} call={onCall.get(phone.handle)} state={state} t={props.t} onShow={props.onShow} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function PlayerCard(props: { phone: Phone; call?: Calls["live"][number]; state: StateSnapshot; t: number; onShow: (householdId: number) => void }) {
  const { phone, call, state } = props;
  const household = state.households.find((item) => item.household_id === phone.household_id);
  const assignment = household ? assignmentById(state, household.assignment_id) ?? assignmentForTarget(state, { household_id: household.household_id }) : undefined;
  const resource = assignment ? resourceById(state, assignment.resource_id) : undefined;
  const eta = assignment && assignment.eta_s > props.t ? Math.round((assignment.eta_s - props.t) / 60) : null;
  return (
    <li className={call ? "on-call" : ""}>
      <header>
        <b>P{phone.player}</b>
        <span className="mono">{maskHandle(phone.handle)}</span>
        {household ? <span className={`pill ${household.status}`}>{statusLabel(household.status)}</span> : <span className="pill">joining</span>}
        {call ? <span className="pill call">on call</span> : null}
      </header>
      <p className="player-van">
        <Icon name="van" /> {resource ? shortName(resource.name) : "—"}
        {eta != null ? <b>{eta} min</b> : null}
      </p>
      {call?.heard ? <q className="heard">{clip(call.heard, 80)}</q> : null}
      {call?.said ? <q className="said">{clip(call.said, 80)}</q> : null}
      {household ? <button className="mini" onClick={() => props.onShow(household.household_id)}>Show</button> : null}
    </li>
  );
}

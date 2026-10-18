import { lazy, Suspense, useMemo, useState } from "react";
import { useClock, type Clock } from "../clock";
import { town } from "../fixtures";
import { closedEdges } from "../model";
import type { BgHousehold, WalkerPlan } from "../people";
import { stateFromPlayback, type Playback } from "../playback";
import { IsoView, type PlayerPin } from "../iso/IsoView";
import type { JudgeClosure, LngLat, Selection, StateSnapshot } from "../types";

const FlatMap = lazy(() => import("./FlatMap"));

type MapViewProps = {
  clock: Clock;
  snapshot: StateSnapshot;
  previous: StateSnapshot | null;
  playback: Playback | null;
  judge: JudgeClosure[];
  walkers: WalkerPlan | null;
  background: BgHousehold[];
  backgroundById: Map<number, BgHousehold>;
  players: Map<number, PlayerPin>;
  flat: boolean;
  selection: Selection | null;
  follow: Selection | null;
  onFollow: (selection: Selection | null) => void;
  onSelect: (selection: Selection | null) => void;
};

/** The stage: the only part of the page that re-renders on every clock tick. */
export function MapView(props: MapViewProps) {
  const t = useClock(props.clock);
  const state = useMemo(
    () => (props.playback ? stateFromPlayback(props.playback, props.snapshot, t) : props.snapshot),
    [props.playback, props.snapshot, t],
  );
  const closures = useMemo(() => closedEdges(state, t, props.judge), [state, t, props.judge]);
  const [focus, setFocus] = useState<{ lon: number; lat: number; zoom: number; key: number } | null>(null);

  const judge = props.snapshot.households.find((household) => household.judge);
  const presets: Array<{ label: string; at: LngLat | null; zoom: number }> = [
    { label: "District", at: [town.venue.lon - 0.004, town.venue.lat - 0.002], zoom: 14.3 },
    { label: "Treehouse", at: [town.venue.lon, town.venue.lat], zoom: 17.3 },
    { label: "Judge", at: judge ? [judge.lon, judge.lat] : null, zoom: 17.6 },
  ];

  return (
    <div className="map-wrap">
      {props.flat ? (
        <Suspense fallback={null}>
          <FlatMap
            state={state}
            previous={props.playback ? null : props.previous}
            t={t}
            closures={closures}
            playback={props.playback}
            walkers={props.walkers}
            background={props.background}
            backgroundById={props.backgroundById}
            selection={props.selection}
            follow={props.follow}
            focus={focus}
            onFollow={props.onFollow}
            onSelect={props.onSelect}
          />
        </Suspense>
      ) : (
        <IsoView
          state={state}
          t={t}
          closures={closures}
          playback={props.playback}
          walkers={props.walkers}
          players={props.players}
          selection={props.selection}
          follow={props.follow}
          onSelect={props.onSelect}
          onFollow={props.onFollow}
          focus={focus}
        />
      )}

      <div className="map-tools">
        {presets.map((preset) =>
          preset.at ? (
            <button
              key={preset.label}
              className="chip"
              onClick={() => {
                props.onFollow(null);
                setFocus({ lon: preset.at![0], lat: preset.at![1], zoom: preset.zoom, key: Date.now() });
              }}
            >
              {preset.label}
            </button>
          ) : null,
        )}
        {props.follow ? (
          <button className="chip on" onClick={() => props.onFollow(null)}>
            Following · stop
          </button>
        ) : null}
      </div>

      <footer className="legend">
        <ul>
          <li><i className="k-flood" /> Flood water</li>
          <li><i className="k-closed" /> Road closed</li>
          <li><i className="k-ahead" /> Vehicle heading to</li>
          <li><i className="k-waiting" /> Waiting for help</li>
        </ul>
        <p>
          Buildings: City of Boston, City of Cambridge (PDDL) · © OpenStreetMap contributors
          {props.playback?.traffic ? "" : " · background cars from the fixture replay (synthetic)"}
        </p>
      </footer>
    </div>
  );
}

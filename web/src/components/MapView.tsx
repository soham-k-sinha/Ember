import { useEffect, useMemo, useRef, useState } from "react";
import { Map as MapGL, useControl, type MapRef } from "react-map-gl/maplibre";
import maplibregl from "maplibre-gl";
import { MapLibreOverlay, type MapLibreOverlayProps } from "@deck.gl/maplibre";
import type { PickingInfo } from "@deck.gl/core";
import "maplibre-gl/dist/maplibre-gl.css";
import { scenario, town } from "../fixtures";
import { buildLayers, NEEDS_COLOR, STATUS_COLOR, type LegendMode } from "../layers";
import { countWalking, type BgHousehold, type WalkerPlan } from "../people";
import type { Playback } from "../playback";
import type { Closure, HouseholdStatus, LngLat, Selection, StateSnapshot } from "../types";

const DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

type Camera = { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number };

const TILTED = { pitch: 55, bearing: -20 };

/** Dev-only timing: window.__perf[name] = [calls, total ms]. */
export function perf<T>(name: string, run: () => T): T {
  if (!import.meta.env.DEV) return run();
  const t0 = performance.now();
  const out = run();
  const w = window as unknown as { __perf?: Record<string, [number, number]> };
  const slot = (w.__perf ??= {})[name] ?? [0, 0];
  w.__perf[name] = [slot[0] + 1, slot[1] + performance.now() - t0];
  return out;
}

function DeckOverlay(props: MapLibreOverlayProps) {
  const overlay = useControl<MapLibreOverlay>(() => new MapLibreOverlay({ ...props, interleaved: true }));
  overlay.setProps(props);
  return null;
}

function selectionFrom(info: PickingInfo): Selection | null {
  const layerId = info.layer?.id;
  const object = info.object as Record<string, unknown> | null;
  if (!layerId || !object) return null;
  if ((layerId === "roads" || layerId === "roads-closed") && typeof object.id === "number") return { kind: "edge", id: object.id };
  if (layerId === "assisted" && typeof object.household_id === "number") return { kind: "household", id: object.household_id };
  if (layerId === "households-bg" && typeof object.id === "number") return { kind: "household", id: object.id };
  if (layerId === "facilities" && typeof object.id === "string") return { kind: "facility", id: object.id };
  if (layerId === "resources") {
    const resource = (object as { resource?: { id?: string } }).resource;
    if (resource?.id) return { kind: "resource", id: resource.id };
  }
  if (layerId === "figures") return ((object as { pick?: Selection }).pick ?? null);
  return null;
}

function tooltip(info: PickingInfo): string | null {
  const layerId = info.layer?.id;
  const object = info.object as Record<string, unknown> | null;
  if (!layerId || !object) return null;
  if (layerId === "figures") {
    const pick = (object as { pick?: Selection; key?: string }).pick;
    const key = String((object as { key?: string }).key ?? "");
    if (pick?.kind === "walker") return "Neighbour leaving on foot (illustrative)";
    if (key.startsWith("s-")) return "At the Treehouse shelter";
    if (key.startsWith("g-")) return "Getting ready to leave (illustrative)";
    if (key.startsWith("c-")) return "Crew at work";
    if (pick?.kind === "household") return "Waiting for help";
  }
  if (layerId === "resources") {
    const resource = (object as { resource?: { name?: string; status?: string; people_on_board?: number } }).resource;
    if (resource) return `${resource.name} · ${String(resource.status ?? "").replaceAll("_", " ")}${resource.people_on_board ? ` · ${resource.people_on_board} aboard` : ""}`;
  }
  if (layerId === "assisted") return String(object.label ?? `Household #${String(object.household_id)}`);
  if (layerId === "facilities") return String(object.name ?? "");
  if (layerId === "households-bg") return "Home (synthetic household; not in the assisted set)";
  if (layerId === "roads" || layerId === "roads-closed") return String(object.name ?? "Road");
  return null;
}

function firstSymbolLayer(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.type === "symbol")?.id;
}

function addBuildings(map: maplibregl.Map) {
  if (map.getLayer("ember-buildings") || !map.getSource("carto")) return;
  for (const id of ["building", "building-top"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
  map.addLayer(
    {
      id: "ember-buildings",
      type: "fill-extrusion",
      source: "carto",
      "source-layer": "building",
      minzoom: 13.5,
      filter: ["!=", ["get", "hide_3d"], true],
      paint: {
        "fill-extrusion-color": ["interpolate", ["linear"], ["coalesce", ["get", "render_height"], 8], 0, "#262d3a", 30, "#323b4c", 80, "#3e4a60"],
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 13.5, 0, 14.5, ["coalesce", ["get", "render_height"], 8]],
        "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
        "fill-extrusion-opacity": 0.93,
        "fill-extrusion-vertical-gradient": true,
      },
    },
    firstSymbolLayer(map),
  );
  map.setLight({ anchor: "viewport", color: "#dfe8ff", intensity: 0.32, position: [1.4, 210, 35] });
}

/** Dusk → night over the scenario: darken the ground and the buildings (deck layers keep their colours). */
function applyNight(map: maplibregl.Map, f: number, dark: boolean) {
  if (!dark || !map.isStyleLoaded()) return;
  const mix = (a: number[], b: number[]) => `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * f)).join(",")})`;
  if (map.getLayer("background")) map.setPaintProperty("background", "background-color", mix([24, 28, 36], [8, 10, 16]));
  if (map.getLayer("ember-buildings")) {
    map.setPaintProperty("ember-buildings", "fill-extrusion-color", [
      "interpolate", ["linear"], ["coalesce", ["get", "render_height"], 8],
      0, mix([42, 50, 64], [22, 26, 36]),
      80, mix([70, 82, 104], [40, 47, 62]),
    ]);
  }
  map.setLight({ anchor: "viewport", color: "#dfe8ff", intensity: 0.4 - 0.18 * f, position: [1.4, 210, 35 + 20 * f] });
}

export type MapViewProps = {
  state: StateSnapshot;
  previous: StateSnapshot | null;
  t: number;
  closures: Closure[];
  playback: Playback | null;
  walkers: WalkerPlan | null;
  background: BgHousehold[];
  backgroundById: Map<number, BgHousehold>;
  showHouseholds: boolean;
  showTrips: boolean;
  showWalkers: boolean;
  legend: LegendMode;
  onLegend: (mode: LegendMode) => void;
  selection: Selection | null;
  follow: Selection | null;
  onFollow: (selection: Selection | null) => void;
  onSelect: (selection: Selection | null) => void;
};

function positionOf(state: StateSnapshot, selection: Selection | null): LngLat | null {
  if (!selection) return null;
  if (selection.kind === "resource") {
    const resource = state.resources.find((item) => item.id === selection.id);
    return resource ? [resource.lon, resource.lat] : null;
  }
  if (selection.kind === "household") {
    const household = state.households.find((item) => item.household_id === selection.id);
    return household ? [household.lon, household.lat] : null;
  }
  if (selection.kind === "facility") {
    const facility = state.facilities.find((item) => item.id === selection.id);
    return facility ? [facility.lon, facility.lat] : null;
  }
  return null;
}

export function MapView(props: MapViewProps) {
  const mapRef = useRef<MapRef | null>(null);
  const [camera, setCamera] = useState<Camera>({ longitude: town.venue.lon, latitude: town.venue.lat, zoom: 14.6, ...TILTED });
  const [dark, setDark] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const tilted = camera.pitch > 5;

  // follow: keep the camera on the followed vehicle / household as the clock runs
  const followAt = positionOf(props.state, props.follow);
  useEffect(() => {
    if (!followAt) return;
    setCamera((current) => ({ ...current, longitude: followAt[0], latitude: followAt[1] }));
  }, [followAt?.[0], followAt?.[1]]);

  // night falls with the clock
  const night = Math.min(1, Math.max(0, props.t / scenario.t_end_s));
  const nightStep = Math.round(night * 20);
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (map && loaded) applyNight(map, nightStep / 20, dark);
  }, [nightStep, loaded, dark]);

  const map = mapRef.current?.getMap();
  const b = loaded && map ? map.getBounds() : null;
  const bounds: [number, number, number, number] | null = b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null;
  const view = { zoom: camera.zoom, bounds, pitch: camera.pitch };

  const layers = useMemo(
    () => perf("layers", () =>
      buildLayers({
        state: props.state,
        previous: props.previous,
        t: props.t,
        closures: props.closures,
        view,
        legend: props.legend,
        playback: props.playback,
        walkers: props.walkers,
        background: props.background,
        backgroundById: props.backgroundById,
        showHouseholds: props.showHouseholds,
        showTrips: props.showTrips,
        showWalkers: props.showWalkers,
        selection: props.selection,
        follow: props.follow,
      })),
    // bounds/zoom bucketed so panning doesn't rebuild every layer every pixel
    [props.state, props.previous, props.t, props.closures, props.legend, props.playback, props.walkers, props.background,
      props.showHouseholds, props.showTrips, props.showWalkers, props.selection, props.follow,
      Math.round(camera.zoom * 4), bounds && Math.round(bounds[0] * 2000), bounds && Math.round(bounds[1] * 2000)],
  );

  const judge = props.state.households.find((household) => household.judge);
  const facility = (type: string) => props.state.facilities.find((item) => item.type === type || item.id === type);
  const presets: Array<{ label: string; at: LngLat | null; zoom: number; pitch?: number; bearing?: number }> = [
    { label: "District", at: [town.venue.lon - 0.004, town.venue.lat - 0.002], zoom: 14.3, pitch: 48, bearing: -15 },
    { label: "Treehouse", at: [town.venue.lon, town.venue.lat], zoom: 17.3 },
    { label: "Judge's corner", at: judge ? [judge.lon, judge.lat] : null, zoom: 17.6 },
    { label: "Shelter", at: facility("shelter") ? [facility("shelter")!.lon, facility("shelter")!.lat] : null, zoom: 17.4 },
    { label: "Pump station", at: facility("cottage-farm") ? [facility("cottage-farm")!.lon, facility("cottage-farm")!.lat] : null, zoom: 17.2 },
  ];

  function fly(at: LngLat, zoom: number, pitch = TILTED.pitch, bearing = TILTED.bearing) {
    props.onFollow(null);
    mapRef.current?.flyTo({ center: at, zoom, pitch: tilted ? pitch : 0, bearing: tilted ? bearing : 0, duration: 1600, essential: true });
  }

  const crowdCounts = props.walkers && props.showWalkers ? countWalking(props.walkers, props.t) : null;

  return (
    <div className="map-wrap">
      <MapGL
        ref={mapRef}
        mapLib={maplibregl}
        mapStyle={dark ? DARK : LIGHT}
        {...camera}
        maxPitch={70}
        onMove={(event) => setCamera(event.viewState)}
        onDragStart={() => props.follow && props.onFollow(null)}
        onLoad={(event) => {
          if (import.meta.env.DEV) (window as unknown as { __emberMap?: maplibregl.Map }).__emberMap = event.target;
          addBuildings(event.target);
          setLoaded(true);
        }}
        onStyleData={(event) => {
          const target = event.target as maplibregl.Map;
          if (import.meta.env.DEV) (window as unknown as { __emberMap?: maplibregl.Map }).__emberMap = target;
          if (target.isStyleLoaded()) {
            addBuildings(target);
            setLoaded(true);
          }
        }}
        onIdle={() => setLoaded(true)}
        attributionControl={{ compact: true }}
      >
        <DeckOverlay
          layers={layers}
          onClick={(info) => props.onSelect(selectionFrom(info))}
          getTooltip={(info) => {
            const text = tooltip(info);
            return text ? { text, className: "deck-tip" } : null;
          }}
          getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
        />
      </MapGL>

      <div className="map-tools">
        <div className="segmented small" role="group" aria-label="Camera">
          <button
            className={tilted ? "on" : ""}
            onClick={() => mapRef.current?.easeTo({ ...TILTED, duration: 700 })}
          >
            Tilted
          </button>
          <button className={!tilted ? "on" : ""} onClick={() => mapRef.current?.easeTo({ pitch: 0, bearing: 0, duration: 700 })}>
            Flat
          </button>
        </div>
        <div className="presets">
          {presets.filter((preset) => preset.at).map((preset) => (
            <button key={preset.label} onClick={() => fly(preset.at!, preset.zoom, preset.pitch, preset.bearing)}>
              {preset.label}
            </button>
          ))}
        </div>
        <button className="chip" onClick={() => setDark(!dark)} title="Basemap">
          {dark ? "Night map" : "Day map"}
        </button>
        {props.follow ? (
          <button className="chip following" onClick={() => props.onFollow(null)}>
            Following · stop
          </button>
        ) : null}
      </div>

      <Legend
        mode={props.legend}
        onMode={props.onLegend}
        crowd={crowdCounts}
        street={camera.zoom >= 15.2}
        playback={props.playback != null}
      />
    </div>
  );
}

const STATUS_LABEL: Record<HouseholdStatus, string> = {
  unknown: "Needs unknown",
  needs: "Needs help",
  assigned: "Help assigned",
  confirmed: "Confirmed",
  picked_up: "Picked up",
  safe: "Safe",
  unreached: "Not reached",
};

function css(c: number[]): string {
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function Legend(props: {
  mode: LegendMode;
  onMode: (mode: LegendMode) => void;
  crowd: ReturnType<typeof countWalking> | null;
  street: boolean;
  playback: boolean;
}) {
  const items: Array<{ color: number[]; label: string }> =
    props.mode === "status"
      ? (Object.keys(STATUS_COLOR) as HouseholdStatus[]).map((status) => ({ color: STATUS_COLOR[status], label: STATUS_LABEL[status] }))
      : props.mode === "needs"
        ? [
            { color: NEEDS_COLOR.mobility, label: "Wheelchair / accessible van" },
            { color: NEEDS_COLOR.medical, label: "Medical" },
            { color: NEEDS_COLOR.standard, label: "Needs a ride" },
            { color: NEEDS_COLOR.unknown, label: "Unknown (ask)" },
          ]
        : [
            { color: [110, 220, 130], label: "> 90 min before water" },
            { color: [240, 210, 80], label: "60–90 min" },
            { color: [250, 150, 60], label: "30–60 min" },
            { color: [240, 80, 70], label: "< 30 min" },
            { color: [120, 120, 130], label: "Water reached them" },
          ];
  return (
    <aside className="legend-card">
      <div className="legend-tabs" role="tablist">
        {(["status", "needs", "deadline"] as LegendMode[]).map((mode) => (
          <button key={mode} role="tab" aria-selected={props.mode === mode} className={props.mode === mode ? "on" : ""} onClick={() => props.onMode(mode)}>
            {mode === "status" ? "Status" : mode === "needs" ? "Needs" : "Deadline"}
          </button>
        ))}
      </div>
      <ul>
        {items.map((item) => (
          <li key={item.label}>
            <i style={{ background: css(item.color) }} /> {item.label}
          </li>
        ))}
      </ul>
      <ul className="legend-keys">
        <li><i className="k-flood" /> Flood water</li>
        <li><i className="k-closed" /> Road closed</li>
        <li><i className="k-trail" /> Vehicle trail · <i className="k-ahead" /> heading to</li>
        {props.street ? <li><i className="k-crew" /> Crew at work</li> : null}
      </ul>
      {props.crowd ? (
        <p className="legend-crowd">
          <strong>{props.crowd.walking}</strong> walking · <strong>{props.crowd.sheltered}</strong> reached the shelter · <strong>{props.crowd.left}</strong> left the area
          {props.crowd.turnedBack > 0 ? <> · <strong>{props.crowd.turnedBack}</strong> turned back at water</> : null}
          <span>Neighbours on foot are illustrative, not simulated.</span>
        </p>
      ) : null}
      {!props.playback ? <p className="legend-crowd"><span>No replay loaded: vehicles move between snapshots.</span></p> : null}
    </aside>
  );
}

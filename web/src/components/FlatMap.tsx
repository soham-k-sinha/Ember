/** The flat MapLibre + deck.gl fallback (lazy-loaded: none of it ships with the stage). */

import { useEffect, useMemo, useRef, useState } from "react";
import { Map as MapGL, useControl, type MapRef } from "react-map-gl/maplibre";
import maplibregl from "maplibre-gl";
import { MapLibreOverlay, type MapLibreOverlayProps } from "@deck.gl/maplibre";
import type { PickingInfo } from "@deck.gl/core";
import "maplibre-gl/dist/maplibre-gl.css";
import { scenario, town } from "../fixtures";
import { buildLayers } from "../layers";
import type { BgHousehold, WalkerPlan } from "../people";
import type { Playback } from "../playback";
import type { Closure, LngLat, Selection, StateSnapshot } from "../types";

const DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

type Camera = { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number };

const TILTED = { pitch: 55, bearing: -20 };

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
function applyNight(map: maplibregl.Map, f: number) {
  if (!map.isStyleLoaded()) return;
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

type FlatMapProps = {
  state: StateSnapshot;
  previous: StateSnapshot | null;
  t: number;
  closures: Closure[];
  playback: Playback | null;
  walkers: WalkerPlan | null;
  background: BgHousehold[];
  backgroundById: Map<number, BgHousehold>;
  selection: Selection | null;
  follow: Selection | null;
  focus: { lon: number; lat: number; zoom: number; key: number } | null;
  onFollow: (selection: Selection | null) => void;
  onSelect: (selection: Selection | null) => void;
};

export default function FlatMap(props: FlatMapProps) {
  const mapRef = useRef<MapRef | null>(null);
  const [camera, setCamera] = useState<Camera>({ longitude: town.venue.lon, latitude: town.venue.lat, zoom: 14.6, ...TILTED });
  const [loaded, setLoaded] = useState(false);
  const tilted = camera.pitch > 5;

  // follow: keep the camera on the followed vehicle / household as the clock runs
  const followAt = positionOf(props.state, props.follow);
  useEffect(() => {
    if (!followAt) return;
    setCamera((current) => ({ ...current, longitude: followAt[0], latitude: followAt[1] }));
  }, [followAt?.[0], followAt?.[1]]);

  useEffect(() => {
    if (props.focus) mapRef.current?.flyTo({ center: [props.focus.lon, props.focus.lat], zoom: props.focus.zoom, duration: 1800, essential: true });
  }, [props.focus]);

  // night falls with the clock
  const nightStep = Math.round(Math.min(1, Math.max(0, props.t / scenario.t_end_s)) * 20);
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (map && loaded) applyNight(map, nightStep / 20);
  }, [nightStep, loaded]);

  const map = mapRef.current?.getMap();
  const mb = loaded && map ? map.getBounds() : null;
  const bounds: [number, number, number, number] | null = mb ? [mb.getWest(), mb.getSouth(), mb.getEast(), mb.getNorth()] : null;

  const layers = useMemo(
    () =>
      buildLayers({
        state: props.state,
        previous: props.previous,
        t: props.t,
        closures: props.closures,
        view: { zoom: camera.zoom, bounds, pitch: camera.pitch },
        playback: props.playback,
        walkers: props.walkers,
        background: props.background,
        backgroundById: props.backgroundById,
        selection: props.selection,
        follow: props.follow,
      }),
    // bounds/zoom bucketed so panning doesn't rebuild every layer every pixel
    [props.state, props.previous, props.t, props.closures, props.playback, props.walkers, props.background,
      props.selection, props.follow, Math.round(camera.zoom * 4), bounds && Math.round(bounds[0] * 2000), bounds && Math.round(bounds[1] * 2000)],
  );

  const tilt = (target: { pitch: number; bearing: number }) => mapRef.current?.flyTo({ ...target, duration: 700, essential: true });

  return (
    <>
      <MapGL
        ref={mapRef}
        mapLib={maplibregl}
        mapStyle={DARK}
        {...camera}
        maxPitch={70}
        onMove={(event) => setCamera(event.viewState)}
        onDragStart={() => props.follow && props.onFollow(null)}
        onLoad={(event) => {
          addBuildings(event.target);
          setLoaded(true);
        }}
        onStyleData={(event) => {
          const target = event.target as maplibregl.Map;
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
          onClick={(info: PickingInfo) => props.onSelect(selectionFrom(info))}
          getTooltip={(info: PickingInfo) => {
            const text = tooltip(info);
            return text ? { text, className: "deck-tip" } : null;
          }}
          getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
        />
      </MapGL>
      <div className="segmented small tilt" role="group" aria-label="Camera">
        <button className={tilted ? "on" : ""} onClick={() => tilt(TILTED)}>
          Tilted
        </button>
        <button className={!tilted ? "on" : ""} onClick={() => tilt({ pitch: 0, bearing: 0 })}>
          Flat
        </button>
      </div>
    </>
  );
}

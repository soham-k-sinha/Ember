import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { Map } from "react-map-gl/maplibre";
import maplibregl from "maplibre-gl";
import type { PickingInfo } from "@deck.gl/core";
import "maplibre-gl/dist/maplibre-gl.css";
import { town } from "../fixtures";
import { buildLayers } from "../layers";
import type { Closure, Selection, StateSnapshot } from "../types";

const CARTO = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const viewState = {
  longitude: town.venue.lon,
  latitude: town.venue.lat,
  zoom: 13.5,
  pitch: 0,
  bearing: 0,
};

function selectionFrom(info: PickingInfo): Selection | null {
  const layerId = info.layer?.id;
  const object = info.object as { id?: number | string; household_id?: number } | null;
  if (!layerId || !object) return null;
  if ((layerId === "roads" || layerId === "roads-closed") && typeof object.id === "number") {
    return { kind: "edge", id: object.id };
  }
  if (layerId === "assisted" && typeof object.household_id === "number") {
    return { kind: "household", id: object.household_id };
  }
  if (layerId === "households-bg" && typeof object.id === "number") {
    return { kind: "household", id: object.id };
  }
  if (layerId === "facilities" && typeof object.id === "string") {
    return { kind: "facility", id: object.id };
  }
  if (layerId === "resources" && typeof object.id === "string") {
    return { kind: "resource", id: object.id };
  }
  return null;
}

export function MapView(props: {
  state: StateSnapshot;
  previous: StateSnapshot | null;
  t: number;
  closures: Closure[];
  showHouseholds: boolean;
  showTrips: boolean;
  onSelect: (selection: Selection | null) => void;
}) {
  const layers = useMemo(
    () =>
      buildLayers({
        state: props.state,
        previous: props.previous,
        t: props.t,
        closures: props.closures,
        showHouseholds: props.showHouseholds,
        showTrips: props.showTrips,
      }),
    [props.state, props.previous, props.t, props.closures, props.showHouseholds, props.showTrips],
  );

  return (
    <div className="map-wrap">
      <DeckGL
        initialViewState={viewState}
        controller={{ dragRotate: false, touchRotate: false }}
        layers={layers}
        getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
        onClick={(info) => props.onSelect(selectionFrom(info))}
      >
        <Map mapLib={maplibregl} mapStyle={CARTO} />
      </DeckGL>
      <ul className="legend">
        <li><i className="swatch road" /> open road</li>
        <li><i className="swatch closed" /> closed</li>
        <li><i className="swatch flood" /> flood</li>
        <li><span className="star">★</span> venue</li>
        <li><i className="swatch hh" /> assisted household</li>
        <li><i className="swatch judge" /> judge</li>
      </ul>
    </div>
  );
}

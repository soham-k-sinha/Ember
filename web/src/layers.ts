import { ArcLayer, GeoJsonLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import type { Layer } from "@deck.gl/core";
import type { FeatureCollection } from "geojson";
import { scenario, town, trajectories } from "./fixtures";
import { assignmentsOf, assistedIds, floodGeometry, positionForTarget } from "./model";
import type {
  Closure,
  HouseholdStatus,
  LngLat,
  StateFacility,
  StateHousehold,
  StateResource,
  StateSnapshot,
} from "./types";

const STATUS_COLOR: Record<HouseholdStatus, [number, number, number]> = {
  unknown: [161, 98, 7],
  needs: [194, 65, 45],
  assigned: [30, 77, 123],
  confirmed: [15, 118, 110],
  picked_up: [3, 105, 161],
  safe: [47, 107, 79],
  unreached: [159, 18, 57],
};

const FACILITY_COLOR = {
  ok: [47, 107, 79],
  backup: [161, 98, 7],
  down: [159, 18, 57],
} as const;

function roadWidth(highway: string): number {
  if (highway === "motorway" || highway === "trunk" || highway === "primary") return 4;
  if (highway === "secondary") return 3;
  if (highway === "tertiary") return 2;
  return 1.5;
}

function resourcePosition(
  resource: StateResource,
  state: StateSnapshot,
  previous: StateSnapshot | null,
  t: number,
): LngLat {
  if (!previous || previous.t_s === state.t_s) return [resource.lon, resource.lat];
  const prior = previous.resources.find((item) => item.id === resource.id);
  if (!prior) return [resource.lon, resource.lat];
  const span = state.t_s - previous.t_s;
  if (span === 0) return [resource.lon, resource.lat];
  const along = Math.min(1, Math.max(0, (t - previous.t_s) / span));
  return [
    prior.lon + (resource.lon - prior.lon) * along,
    prior.lat + (resource.lat - prior.lat) * along,
  ];
}

export function buildLayers(args: {
  state: StateSnapshot;
  previous: StateSnapshot | null;
  t: number;
  closures: Closure[];
  showHouseholds: boolean;
  showTrips: boolean;
}): Layer[] {
  const { state, previous, t, closures, showHouseholds, showTrips } = args;
  const closed = new Set(closures.map((closure) => closure.edge_id));
  const assisted = assistedIds(state);
  const geometry = floodGeometry(state, t);
  const flood: FeatureCollection = {
    type: "FeatureCollection",
    features: geometry
      ? [{ type: "Feature", geometry, properties: { kind: "flood" } }]
      : [],
  };
  const district: FeatureCollection = scenario.district
    ? {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: scenario.district.geometry,
            properties: { name: scenario.district.name },
          },
        ],
      }
    : { type: "FeatureCollection", features: [] };

  const openRoads = town.edges.filter((edge) => !closed.has(edge.id));
  const closedRoads = town.edges.filter((edge) => closed.has(edge.id));
  const background = town.households.filter((household) => !assisted.has(household.id));
  const assignments = assignmentsOf(state.plan).flatMap((assignment) => {
    const resource = state.resources.find((item) => item.id === assignment.resource_id);
    const target = positionForTarget(state, assignment.target);
    if (!resource || !target) return [];
    return [{ assignment, source: resourcePosition(resource, state, previous, t), target }];
  });

  const layers: Layer[] = [
    new GeoJsonLayer({
      id: "district",
      data: district,
      filled: false,
      stroked: true,
      getLineColor: [90, 98, 104, 160],
      lineWidthMinPixels: 1,
      pickable: false,
    }),
    new GeoJsonLayer({
      id: "flood",
      data: flood,
      filled: true,
      stroked: true,
      getFillColor: [37, 99, 168, 78],
      getLineColor: [23, 67, 120, 200],
      lineWidthMinPixels: 1,
      pickable: false,
    }),
    new PathLayer({
      id: "roads",
      data: openRoads,
      getPath: (edge) => edge.geom,
      getColor: [96, 104, 112, 210],
      getWidth: (edge) => roadWidth(edge.highway),
      widthUnits: "pixels",
      widthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
    }),
    new PathLayer({
      id: "roads-closed",
      data: closedRoads,
      getPath: (edge) => edge.geom,
      getColor: [198, 58, 42, 235],
      getWidth: (edge) => roadWidth(edge.highway) + 1,
      widthUnits: "pixels",
      widthMinPixels: 2,
      pickable: true,
      autoHighlight: true,
    }),
  ];

  if (showTrips) {
    layers.push(
      new TripsLayer({
        id: "trips",
        data: trajectories.trips,
        getPath: (trip) => trip.path,
        getTimestamps: (trip) => trip.t,
        getColor: [55, 65, 74, 120],
        widthMinPixels: 2,
        currentTime: t,
        trailLength: 180,
        capRounded: true,
        jointRounded: true,
        pickable: false,
      }),
    );
  }

  if (showHouseholds) {
    layers.push(
      new ScatterplotLayer({
        id: "households-bg",
        data: background,
        getPosition: (household) => [household.lon, household.lat],
        getFillColor: [120, 113, 108, 150],
        getRadius: 3,
        radiusUnits: "pixels",
        pickable: true,
      }),
    );
  }

  layers.push(
    new PathLayer({
      id: "routes",
      data: assignments.filter((item) => (item.assignment.route?.length ?? 0) > 1),
      getPath: (item) => item.assignment.route ?? [],
      getColor: [30, 77, 123, 180],
      getWidth: 3,
      widthUnits: "pixels",
      pickable: false,
    }),
    new ArcLayer({
      id: "assignments",
      data: assignments,
      getSourcePosition: (item) => item.source,
      getTargetPosition: (item) => item.target,
      getSourceColor: [30, 77, 123, 200],
      getTargetColor: [180, 83, 9, 200],
      getWidth: 2,
      widthUnits: "pixels",
      greatCircle: false,
      pickable: false,
    }),
    new ScatterplotLayer({
      id: "assisted",
      data: state.households,
      getPosition: (household) => [household.lon, household.lat],
      getFillColor: (household: StateHousehold): [number, number, number, number] => {
        const color = STATUS_COLOR[household.status];
        return [color[0], color[1], color[2], 230];
      },
      getLineColor: (household) => (household.judge ? [180, 83, 9, 255] : [255, 252, 247, 220]),
      getRadius: (household) => (household.judge ? 9 : 6),
      radiusUnits: "pixels",
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: (household) => (household.judge ? 3 : 1),
      pickable: true,
      autoHighlight: true,
    }),
    new ScatterplotLayer({
      id: "facilities",
      data: state.facilities,
      getPosition: (facility) => [facility.lon, facility.lat],
      getFillColor: (facility: StateFacility): [number, number, number, number] => {
        const color = FACILITY_COLOR[facility.state];
        return [color[0], color[1], color[2], 235];
      },
      getLineColor: [255, 252, 247, 255],
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      getRadius: 8,
      radiusUnits: "pixels",
      pickable: true,
      autoHighlight: true,
    }),
    new TextLayer({
      id: "facility-labels",
      data: state.facilities,
      getPosition: (facility) => [facility.lon, facility.lat],
      getText: (facility) => facility.name,
      getSize: 11,
      getColor: [28, 25, 23, 255],
      getPixelOffset: [0, 14],
      getTextAnchor: "middle",
      getAlignmentBaseline: "top",
      fontFamily: "system-ui, sans-serif",
      fontWeight: 600,
      background: true,
      getBackgroundColor: [255, 252, 247, 210],
      backgroundPadding: [3, 1],
      pickable: false,
    }),
    new ScatterplotLayer({
      id: "resources",
      data: state.resources,
      getPosition: (resource) => resourcePosition(resource, state, previous, t),
      getFillColor: [250, 250, 247, 255],
      getLineColor: [28, 25, 23, 255],
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      getRadius: 5,
      radiusUnits: "pixels",
      pickable: true,
      autoHighlight: true,
    }),
    new TextLayer({
      id: "venue-star",
      data: [town.venue],
      getPosition: (venue) => [venue.lon, venue.lat],
      getText: () => "★",
      getSize: 28,
      getColor: [180, 83, 9, 255],
      getTextAnchor: "middle",
      getAlignmentBaseline: "center",
      fontFamily: "Georgia, serif",
      pickable: false,
    }),
    new TextLayer({
      id: "venue-label",
      data: [town.venue],
      getPosition: (venue) => [venue.lon, venue.lat],
      getText: (venue) => venue.name,
      getSize: 12,
      getColor: [28, 25, 23, 255],
      getPixelOffset: [0, 16],
      getTextAnchor: "middle",
      getAlignmentBaseline: "top",
      fontFamily: "system-ui, sans-serif",
      fontWeight: 700,
      background: true,
      getBackgroundColor: [255, 252, 247, 220],
      backgroundPadding: [4, 2],
      pickable: false,
    }),
  );

  return layers;
}

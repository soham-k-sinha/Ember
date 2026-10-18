import { GeoJsonLayer, IconLayer, LineLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import type { Layer } from "@deck.gl/core";
import type { FeatureCollection } from "geojson";
import { scenario, town } from "./fixtures";
import { assistedIds, curb, floodGeometry, householdColor, peopleCount } from "./model";
import { pathAhead, type Playback } from "./playback";
import {
  arrivedAtShelter,
  cluster,
  crowd,
  gathering,
  hash,
  offsetMetres,
  walkersAt,
  type BgHousehold,
  type WalkerPlan,
} from "./people";
import { atlas } from "./sprites";
import type {
  Closure,
  LngLat,
  ResourceStatus,
  Selection,
  StateFacility,
  StateHousehold,
  StateResource,
  StateSnapshot,
} from "./types";

type RGB = [number, number, number];
type RGBA = [number, number, number, number];

const RESOURCE_COLOR: Record<string, RGB> = {
  van: [125, 180, 255],
  accessible_van: [150, 120, 255],
  ambulance: [255, 96, 96],
  truck: [255, 150, 70],
  generator: [255, 210, 60],
  crew: [90, 210, 140],
};

const STATUS_GLOW: Partial<Record<ResourceStatus, RGB>> = {
  en_route: [96, 165, 250],
  working: [255, 190, 70],
  returning: [80, 220, 200],
  stalled: [240, 80, 80],
  out_of_service: [150, 150, 150],
};

const FACILITY_COLOR = {
  ok: [110, 220, 130],
  backup: [245, 182, 66],
  down: [236, 72, 72],
} as const;

// ---------- per-frame caches: deck re-uploads (and re-tessellates) whenever `data` is a new array ----------
const DISTRICT: FeatureCollection = scenario.district
  ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: scenario.district.geometry, properties: {} }] }
  : { type: "FeatureCollection", features: [] };

let floodCache: { geometry: unknown; fc: FeatureCollection } | null = null;
function floodCollection(geometry: ReturnType<typeof floodGeometry>): FeatureCollection {
  if (floodCache && floodCache.geometry === geometry) return floodCache.fc;
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: geometry ? [{ type: "Feature", geometry, properties: { kind: "flood" } }] : [],
  };
  floodCache = { geometry, fc };
  return fc;
}

let roadCache: { key: string; open: typeof town.edges; closed: typeof town.edges } | null = null;
function roadsSplit(closed: Set<number>): { open: typeof town.edges; closed: typeof town.edges } {
  const key = [...closed].sort((a, b) => a - b).join(",");
  if (roadCache && roadCache.key === key) return roadCache;
  roadCache = { key, open: town.edges.filter((edge) => !closed.has(edge.id)), closed: town.edges.filter((edge) => closed.has(edge.id)) };
  return roadCache;
}

let bgCache: { source: BgHousehold[]; key: string; rows: BgHousehold[] } | null = null;
function backgroundRows(source: BgHousehold[], assisted: Set<number>): BgHousehold[] {
  const key = [...assisted].join(",");
  if (bgCache && bgCache.source === source && bgCache.key === key) return bgCache.rows;
  bgCache = { source, key, rows: source.filter((household) => !assisted.has(household.id)) };
  return bgCache.rows;
}

/** One shared instance: a new extension object per render makes deck rebuild the layer (shader recompile) every frame. */
const DASHED = [new PathStyleExtension({ dash: true })];

/** Draw over buildings (interleaved depth would hide people and vans standing beside or inside a footprint). */
const ON_TOP = { depthCompare: "always", depthWriteEnabled: false } as const;

function figureSize(zoom: number): number {
  return Math.max(10, Math.min(34, (zoom - 14.2) * 8));
}

/** Ground metres covered by one screen pixel at this zoom (Web Mercator, Allston latitude). */
function metresPerPixel(zoom: number): number {
  return (156_543.03 * Math.cos((42.36 * Math.PI) / 180)) / 2 ** zoom;
}

type ViewInfo = { zoom: number; bounds: [number, number, number, number] | null; pitch: number };

type LayerArgs = {
  state: StateSnapshot;
  previous: StateSnapshot | null;
  t: number;
  closures: Closure[];
  view: ViewInfo;
  playback: Playback | null;
  walkers: WalkerPlan | null;
  background: BgHousehold[];
  backgroundById: Map<number, BgHousehold>;
  selection: Selection | null;
  follow: Selection | null;
};

function resourcePosition(resource: StateResource, previous: StateSnapshot | null, state: StateSnapshot, t: number): LngLat {
  if (!previous || previous.t_s === state.t_s) return [resource.lon, resource.lat];
  const prior = previous.resources.find((item) => item.id === resource.id);
  if (!prior) return [resource.lon, resource.lat];
  const span = state.t_s - previous.t_s;
  if (span === 0) return [resource.lon, resource.lat];
  const along = Math.min(1, Math.max(0, (t - previous.t_s) / span));
  return [prior.lon + (resource.lon - prior.lon) * along, prior.lat + (resource.lat - prior.lat) * along];
}

type Figure = {
  key: string;
  position: LngLat;
  icon: string;
  color: RGBA;
  size: number;
  pick?: Selection;
};

export function buildLayers(args: LayerArgs): Layer[] {
  const { state, t, closures, view, playback, selection } = args;
  const sprites = atlas();
  const zoom = view.zoom;
  const street = zoom >= 15.2;
  const fsize = figureSize(zoom);
  // figures are sized in pixels; space them in metres so they stand side by side instead of in one blob
  const gap = Math.max(1.2, fsize * metresPerPixel(zoom) * 0.42);
  const pulse = 0.5 + 0.5 * Math.sin(t / 9);
  const closed = new Set(closures.map((closure) => closure.edge_id));
  const assisted = assistedIds(state);
  const flood = floodCollection(floodGeometry(state, t));
  const roads = roadsSplit(closed);

  const resources = state.resources.map((resource) => ({
    resource,
    position: playback ? ([resource.lon, resource.lat] as LngLat) : resourcePosition(resource, args.previous, state, t),
  }));
  const shelter = state.facilities.find((facility) => facility.type === "shelter");

  const layers: Layer[] = [
    new GeoJsonLayer({
      id: "district",
      data: DISTRICT,
      filled: false,
      stroked: true,
      getLineColor: [160, 180, 200, 70],
      lineWidthMinPixels: 1.5,
      extensions: DASHED,
      getDashArray: [6, 4],
      dashJustified: true,
      pickable: false,
    } as never),
    new GeoJsonLayer({
      id: "flood",
      data: flood,
      filled: true,
      stroked: true,
      getFillColor: [111, 214, 236, 92 + Math.round(18 * pulse)],
      getLineColor: [230, 251, 255, 220],
      lineWidthMinPixels: 1.5,
      pickable: false,
      updateTriggers: { getFillColor: [Math.round(pulse * 10)] },
    }),
    new PathLayer({
      id: "roads",
      data: roads.open,
      getPath: (edge) => edge.geom,
      getColor: (edge) => (selection?.kind === "edge" && selection.id === edge.id ? [255, 220, 120, 230] : [120, 140, 160, 40]),
      getWidth: 3,
      widthUnits: "pixels",
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 220, 120, 160],
      updateTriggers: { getColor: [selection?.kind === "edge" ? selection.id : null] },
    }),
    new PathLayer({
      id: "roads-closed",
      data: roads.closed,
      getPath: (edge) => edge.geom,
      getColor: [240, 70, 60, 220],
      getWidth: 3.5,
      widthUnits: "pixels",
      widthMinPixels: 2,
      pickable: true,
      autoHighlight: true,
    }),
  ];

  // lit homes: every household in the district as a warm dot (synthetic placement, town.meta.synthetic)
  layers.push(
    new ScatterplotLayer<BgHousehold>({
      id: "households-bg",
      parameters: ON_TOP,
      data: backgroundRows(args.background, assisted),
      getPosition: (household) => [household.lon, household.lat],
      getFillColor: (household) => {
        const flicker = hash(household.id, 2) < 0.12 ? 60 : 0;
        return [255, 200, 130, (street ? 70 : 110) - flicker];
      },
      getRadius: street ? 2.5 : 1.6,
      radiusUnits: "pixels",
      pickable: true,
      updateTriggers: { getFillColor: [street] },
    }),
  );

  // trails and where each vehicle is heading
  if (playback) {
    layers.push(
      new TripsLayer({
        id: "trails",
        data: playback.tracks,
        getPath: (track) => track.path,
        getTimestamps: (track) => track.t,
        getColor: (track) => {
          const c = RESOURCE_COLOR[track.kind] ?? [200, 200, 200];
          return [c[0], c[1], c[2], 210];
        },
        widthMinPixels: 3.5,
        widthMaxPixels: 7,
        getWidth: 6,
        currentTime: t,
        trailLength: 150,
        fadeTrail: true,
        capRounded: true,
        jointRounded: true,
        pickable: false,
      }),
      new PathLayer({
        id: "ahead",
        data: playback.tracks.map((track) => ({ track, path: pathAhead(track, t) })).filter((item) => item.path.length > 1),
        getPath: (item: { path: LngLat[] }) => item.path,
        getColor: (item: { track: { kind: string } }) => {
          const c = RESOURCE_COLOR[item.track.kind] ?? [200, 200, 200];
          return [c[0], c[1], c[2], 150];
        },
        getWidth: 3,
        widthUnits: "pixels",
        extensions: DASHED,
        getDashArray: [2, 2],
        pickable: false,
      } as never),
    );
  } else {
    const assignments = (state.plan?.assignments ?? []).filter((assignment) => (assignment.route?.length ?? 0) > 1);
    layers.push(
      new PathLayer({
        id: "routes",
        data: assignments,
        getPath: (assignment: { route?: LngLat[] }) => assignment.route ?? [],
        getColor: [125, 180, 255, 150],
        getWidth: 3,
        widthUnits: "pixels",
        extensions: DASHED,
        getDashArray: [2, 2],
        pickable: false,
      } as never),
    );
  }

  // generator → facility power line
  const powered = state.facilities
    .map((facility) => ({ facility, gen: resources.find((item) => item.resource.id === facility.powered_by) }))
    .filter((item) => item.gen);
  layers.push(
    new LineLayer({
      id: "power",
      data: powered,
      getSourcePosition: (item) => item.gen!.position,
      getTargetPosition: (item) => [item.facility.lon, item.facility.lat],
      getColor: [255, 210, 60, 140 + Math.round(100 * pulse)],
      getWidth: 3,
      widthUnits: "pixels",
      updateTriggers: { getColor: [Math.round(pulse * 10)] },
    }),
  );

  // facilities
  layers.push(
    new IconLayer<StateFacility>({
      id: "facility-glow",
        parameters: ON_TOP,
      data: state.facilities,
      iconAtlas: sprites.url,
      iconMapping: sprites.mapping,
      getIcon: () => "glow",
      getPosition: (facility) => [facility.lon, facility.lat],
      getColor: (facility) => {
        const c = FACILITY_COLOR[facility.state];
        return [c[0], c[1], c[2], facility.state === "ok" ? 90 : 120 + Math.round(100 * pulse)];
      },
      getSize: (facility) => (facility.state === "ok" ? 46 : 64),
      sizeUnits: "pixels",
      billboard: true,
      pickable: false,
      updateTriggers: { getColor: [Math.round(pulse * 10)] },
    }),
    new ScatterplotLayer<StateFacility>({
      id: "facilities",
        parameters: ON_TOP,
      data: state.facilities,
      getPosition: (facility) => [facility.lon, facility.lat],
      getFillColor: (facility) => {
        const c = FACILITY_COLOR[facility.state];
        return [c[0], c[1], c[2], 240];
      },
      getLineColor: [15, 20, 28, 255],
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      getRadius: 8,
      radiusUnits: "pixels",
      pickable: true,
      autoHighlight: true,
    }),
  );

  // assisted households: status rings at every zoom
  const judge = state.households.find((household) => household.judge);
  layers.push(
    new ScatterplotLayer<StateHousehold>({
      id: "assisted",
        parameters: ON_TOP,
      data: state.households,
      getPosition: (household) => [household.lon, household.lat],
      getFillColor: (household) => {
        const c = householdColor(household);
        const gone = household.status === "picked_up" || household.status === "safe";
        return [c[0], c[1], c[2], gone ? 60 : street ? 70 : 220];
      },
      getLineColor: (household) => {
        if (household.judge) return [255, 196, 70, 255];
        const c = householdColor(household);
        return [c[0], c[1], c[2], 255];
      },
      getRadius: (household) => {
        const base = household.judge ? 10 : 6.5;
        const urgent = household.status === "needs" || household.status === "unknown";
        return base + (urgent ? 3 * pulse : 0) + (street ? 6 : 0);
      },
      radiusUnits: "pixels",
      stroked: true,
      lineWidthUnits: "pixels",
      getLineWidth: (household) => (household.judge ? 3 : 1.5),
      pickable: true,
      autoHighlight: true,
      updateTriggers: {
        getFillColor: [Math.floor(t / 30), street],
        getLineColor: [Math.floor(t / 30)],
        getRadius: [Math.round(pulse * 10), street],
      },
    }),
  );

  // ---------- people (street zoom) ----------
  const figures: Figure[] = [];
  const dots: Array<{ position: LngLat; color: RGBA }> = [];
  if (street) {
    for (const household of state.households) {
      if (household.status === "picked_up" || household.status === "safe") continue;
      const n = Math.min(6, peopleCount(household));
      const c = householdColor(household);
      const mobility = household.needs !== "unknown" && (household.needs.mobility || household.needs.accessible_vehicle);
      cluster(curb(household.lon, household.lat, household.node), n, household.household_id, gap * 1.3).forEach((position, i) => {
        figures.push({
          key: `hh-${household.household_id}-${i}`,
          position,
          icon: mobility && i === 0 ? "wheel" : i === 0 && (household.status === "needs" || household.status === "unknown") && Math.floor(t / 4 + household.household_id) % 2 ? "wave" : "stand",
          color: [c[0], c[1], c[2], 255],
          size: fsize * (household.judge ? 1.15 : 1),
          pick: { kind: "household", id: household.household_id },
        });
      });
    }
  }
  if (args.walkers) {
    const poses = walkersAt(args.walkers, t, view.bounds);
    for (const pose of poses) {
      const back = pose.walker.turnedBack && pose.walker.times[Math.floor(pose.walker.path.length / 2)] <= t;
      const color: RGBA = back ? [255, 170, 120, 235] : pose.walker.dest === "shelter" ? [196, 225, 255, 235] : [210, 210, 225, 220];
      if (street) {
        figures.push({ key: `w-${pose.walker.id}`, position: pose.position, icon: pose.frame, color, size: fsize * 0.92, pick: { kind: "walker", id: pose.walker.household } });
      } else {
        dots.push({ position: pose.position, color });
      }
    }
    if (street) {
      for (const group of gathering(args.walkers, args.backgroundById, t)) {
        cluster(curb(group.household.lon, group.household.lat, group.household.node), group.size, group.household.id, gap).forEach((position, i) => {
          figures.push({ key: `g-${group.household.id}-${i}`, position, icon: "stand", color: [210, 210, 225, 220], size: fsize * 0.92 });
        });
      }
    }
  }
  // shelter crowd: people the vans dropped off (sim) + walkers who arrived (illustrative)
  if (shelter) {
    const dropped = shelter.people_on_site ?? 0;
    const walked = args.walkers ? arrivedAtShelter(args.walkers, t) : 0;
    const n = Math.min(90, dropped + walked);
    if (street && n > 0) {
      crowd([shelter.lon, shelter.lat], n, gap).forEach((position, i) => {
        figures.push({
          key: `s-${i}`,
          position,
          icon: Math.floor(t / 5 + i) % 7 === 0 ? "wave" : "stand",
          color: i < Math.min(dropped, n) ? [110, 220, 130, 245] : [196, 225, 255, 230],
          size: fsize * 0.9,
          pick: { kind: "facility", id: shelter.id },
        });
      });
    }
  }
  // crews at work beside working vehicles
  for (const { resource, position } of resources) {
    if (!street || resource.status !== "working") continue;
    const crew = resource.kind === "generator" || resource.kind === "crew" || resource.kind === "truck" ? 3 : 1;
    for (let i = 0; i < crew; i++) {
      const a = ((resource.heading_deg ?? 0) + 70 + i * 55) * (Math.PI / 180);
      const p = offsetMetres(position, Math.sin(a) * (6 + i), Math.cos(a) * (6 + i));
      figures.push({
        key: `c-${resource.id}-${i}`,
        position: p,
        icon: Math.floor(t / 3 + i) % 2 ? "worker" : "walk1",
        color: [255, 160, 40, 255],
        size: fsize * 0.95,
        pick: { kind: "resource", id: resource.id },
      });
    }
  }

  if (dots.length > 0) {
    layers.push(
      new ScatterplotLayer({
        id: "walker-dots",
        parameters: ON_TOP,
        data: dots,
        getPosition: (dot) => dot.position,
        getFillColor: (dot) => dot.color,
        getRadius: 1.8,
        radiusUnits: "pixels",
        pickable: false,
      }),
    );
  }
  if (figures.length > 0) {
    layers.push(
      new ScatterplotLayer<Figure>({
        id: "figure-shadows",
        parameters: ON_TOP,
        data: figures,
        getPosition: (figure) => figure.position,
        getFillColor: [0, 0, 0, 90],
        getRadius: (figure) => figure.size * 0.18,
        radiusUnits: "pixels",
        pickable: false,
      }),
      new IconLayer<Figure>({
        id: "figures",
        parameters: ON_TOP,
        data: figures,
        iconAtlas: sprites.url,
        iconMapping: sprites.mapping,
        getIcon: (figure) => figure.icon,
        getPosition: (figure) => figure.position,
        getColor: (figure) => figure.color,
        getSize: (figure) => figure.size,
        sizeUnits: "pixels",
        billboard: true,
        alphaCutoff: 0.2,
        pickable: true,
      }),
    );
  }

  // ---------- vehicles ----------
  layers.push(
    new IconLayer<{ resource: StateResource; position: LngLat }>({
      id: "vehicle-glow",
        parameters: ON_TOP,
      data: resources.filter((item) => STATUS_GLOW[item.resource.status]),
      iconAtlas: sprites.url,
      iconMapping: sprites.mapping,
      getIcon: () => "glow",
      getPosition: (item) => item.position,
      getColor: (item) => {
        const c = STATUS_GLOW[item.resource.status] ?? [200, 200, 200];
        const beat = item.resource.status === "en_route" ? Math.round(110 * pulse) : 40;
        return [c[0], c[1], c[2], 90 + beat];
      },
      getSize: street ? 76 : 52,
      sizeUnits: "pixels",
      billboard: true,
      pickable: false,
      updateTriggers: { getColor: [Math.round(pulse * 10)] },
    }),
    new IconLayer<{ resource: StateResource; position: LngLat }>({
      id: "resources",
        parameters: ON_TOP,
      data: resources,
      iconAtlas: sprites.url,
      iconMapping: sprites.mapping,
      getIcon: (item) => (sprites.mapping[item.resource.kind] ? item.resource.kind : "van"),
      getPosition: (item) => item.position,
      getAngle: (item) => -(item.resource.heading_deg ?? 0),
      getSize: 13,
      sizeUnits: "meters",
      sizeMinPixels: street ? 26 : 20,
      sizeMaxPixels: 96,
      billboard: false,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 90],
    }),
  );

  // ---------- labels ----------
  const tags: Array<{ position: LngLat; text: string; tone: "vehicle" | "pick" | "judge" }> = [];
  const pickSet = [selection, args.follow].filter(Boolean) as Selection[];
  for (const { resource, position } of resources) {
    const picked = pickSet.some((item) => item.kind === "resource" && item.id === resource.id);
    if (!(street || picked)) continue;
    const aboard = resource.people_on_board ? ` · ${resource.people_on_board} aboard` : "";
    tags.push({ position, text: `${resource.name}${aboard}`, tone: picked ? "pick" : "vehicle" });
  }
  if (judge && judge.status !== "picked_up" && judge.status !== "safe") tags.push({ position: [judge.lon, judge.lat], text: "Judge's household", tone: "judge" });
  for (const item of pickSet) {
    if (item.kind === "household") {
      const household = state.households.find((h) => h.household_id === item.id);
      if (household && !household.judge) tags.push({ position: [household.lon, household.lat], text: household.label ?? `Household #${household.household_id}`, tone: "pick" });
    }
  }
  layers.push(
    new TextLayer({
      id: "facility-labels",
        parameters: ON_TOP,
      data: state.facilities,
      getPosition: (facility) => [facility.lon, facility.lat],
      getText: (facility) => facility.name,
      getSize: 12,
      getColor: [235, 240, 245, 255],
      getPixelOffset: [0, 16],
      getTextAnchor: "middle",
      getAlignmentBaseline: "top",
      fontFamily: "Inter, system-ui, sans-serif",
      fontWeight: 600,
      background: true,
      getBackgroundColor: [14, 18, 26, 210],
      backgroundPadding: [5, 2],
      characterSet: "auto",
      pickable: false,
    }),
    new TextLayer({
      id: "tags",
        parameters: ON_TOP,
      data: tags,
      getPosition: (tag) => tag.position,
      getText: (tag) => (tag.tone === "pick" ? `${tag.text} ▾` : tag.text),
      getSize: (tag) => (tag.tone === "vehicle" ? 11 : 13),
      getColor: (tag) => (tag.tone === "judge" ? [255, 214, 120, 255] : [245, 248, 252, 255]),
      getPixelOffset: (tag) => [0, tag.tone === "vehicle" ? -22 : -(fsize + 18)],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      fontFamily: "Inter, system-ui, sans-serif",
      fontWeight: 650,
      background: true,
      getBackgroundColor: (tag) => (tag.tone === "pick" ? [24, 30, 42, 240] : tag.tone === "judge" ? [70, 46, 10, 230] : [14, 18, 26, 190]),
      getBorderColor: (tag) => (tag.tone === "pick" ? [245, 248, 252, 200] : [0, 0, 0, 0]),
      getBorderWidth: (tag) => (tag.tone === "pick" ? 1 : 0),
      backgroundPadding: [6, 3],
      characterSet: "auto",
      pickable: false,
      updateTriggers: { getPixelOffset: [fsize] },
    }),
    new TextLayer({
      id: "venue",
        parameters: ON_TOP,
      data: [town.venue],
      getPosition: (venue) => [venue.lon, venue.lat],
      getText: (venue) => `★ ${venue.name}`,
      getSize: 13,
      getColor: [255, 214, 120, 255],
      getPixelOffset: [0, -14],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      fontFamily: "Inter, system-ui, sans-serif",
      fontWeight: 700,
      background: true,
      getBackgroundColor: [40, 28, 8, 220],
      backgroundPadding: [6, 3],
      characterSet: "auto",
      pickable: false,
    }),
  );

  return layers;
}

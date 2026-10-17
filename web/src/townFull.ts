import townGzUrl from "../../engine/data/town.json.gz?url";
import type { BgHousehold } from "./people";

/** The full shared town (D29): every household, not the 1-in-12 fixture sample. Loaded once, async. */
export type FullTown = { households: BgHousehold[]; exits: number[] };

let pending: Promise<FullTown | null> | null = null;

export function loadFullTown(): Promise<FullTown | null> {
  if (!pending) pending = fetchTown().catch(() => null);
  return pending;
}

async function fetchTown(): Promise<FullTown | null> {
  const response = await fetch(townGzUrl);
  if (!response.ok) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  let text: string;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b && "DecompressionStream" in window) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes); // the server already decoded it
  }
  const town = JSON.parse(text) as { households?: BgHousehold[]; exits?: number[] };
  if (!Array.isArray(town.households)) return null;
  return {
    households: town.households.map((h) => ({ id: h.id, lon: h.lon, lat: h.lat, node: h.node, size: h.size, vehicles: h.vehicles, flags: h.flags })),
    exits: town.exits ?? [],
  };
}

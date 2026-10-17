/**
 * The stage's real-world data (engine `ember diorama` → public/diorama/<name>.json, D71): city
 * building footprints and heights, roof type, LiDAR tree crowns, land use, the Charles, paths.
 */

export type DioBuilding = {
  ring: [number, number][];
  h: number;
  eave?: number;
  roof: "flat" | "pitched" | "hybrid";
  tone?: number;
  use: string;
  name?: string;
  src: string;
};

export type Diorama = {
  version: string;
  bbox: [number, number, number, number];
  origin: [number, number];
  attribution: string;
  buildings: DioBuilding[];
  trees: [number, number, number, number, number][];
  land: { ring: [number, number][]; k: string; sub?: string }[];
  water: { ring: [number, number][]; holes: [number, number][][] }[];
  roads: { path: [number, number][]; k: string }[];
};

const pending = new Map<string, Promise<Diorama | null>>();

export function loadDiorama(name = "stage"): Promise<Diorama | null> {
  let p = pending.get(name);
  if (!p) {
    p = fetch(`${import.meta.env.BASE_URL}diorama/${name}.json`)
      .then((response) => (response.ok ? (response.json() as Promise<Diorama>) : null))
      .catch(() => null);
    pending.set(name, p);
  }
  return p;
}

/** Recognisable buildings: real materials from the research catalogue (wall, roof, label). */
export const LANDMARKS: Array<{ match: RegExp; wall: number; roof?: number; label?: string }> = [
  { match: /treehouse/i, wall: 0xc99a62, roof: 0x7f9a5c }, // named by its shelter marker
  { match: /science and engineering/i, wall: 0xc9cdd1, roof: 0x7e9f5a, label: "SCIENCE & ENGINEERING COMPLEX" },
  { match: /atlas hotel/i, wall: 0xc6ae88, roof: 0x6f90a8, label: "ATLAS HOTEL" },
  { match: /verra/i, wall: 0x3f8f6e, label: "VERRA" },
  { match: /milestone/i, wall: 0xa8653f },
  { match: /district energy/i, wall: 0xb9bec2 },
  { match: /baker library/i, wall: 0x9c3d2c, roof: 0x4d5359, label: "BAKER LIBRARY" },
  { match: /1959 chapel/i, wall: 0x6fa58c, roof: 0x6fa58c },
  { match: /klarman/i, wall: 0x9c3d2c, label: "KLARMAN HALL" },
  { match: /tata hall/i, wall: 0xd9d3c4 },
  { match: /innovation lab|batten/i, wall: 0xd8dadb, label: "HARVARD i-LAB" },
  { match: /newell/i, wall: 0x8e4a3e, roof: 0x5f7a68, label: "NEWELL BOATHOUSE" },
  { match: /weld boat/i, wall: 0xe3d6bc, roof: 0xa65a3a, label: "WELD BOATHOUSE" },
  { match: /dunster/i, wall: 0x9c3d2c, roof: 0x4d5359, label: "DUNSTER HOUSE" },
  { match: /mather house tower/i, wall: 0xa7a39a, label: "MATHER TOWER" },
  { match: /mather/i, wall: 0xa7a39a },
  { match: /leverett .*tower/i, wall: 0xd9d3c4 },
  { match: /peabody terrace/i, wall: 0xa9a59c, label: "PEABODY TERRACE" },
  { match: /soldiers field park/i, wall: 0x9a5a44 },
  { match: /one western/i, wall: 0xb9b3a8 },
  { match: /stadium/i, wall: 0xbdb5a6, label: "HARVARD STADIUM" },
  { match: /doubletree/i, wall: 0xc8b699 },
];

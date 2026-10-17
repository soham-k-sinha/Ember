import comparisonJson from "../../contracts/fixtures/comparison.fixture.json";
import wsEventsJson from "../../contracts/fixtures/ws-events.fixture.json";
import townJson from "../../contracts/fixtures/town.fixture.json";
import trajectoriesJson from "../../contracts/fixtures/trajectories.fixture.json";
import scenarioJson from "../../scenarios/allston_flood_v1/scenario.json";
import { scatterFromEnvelopes } from "./live";
import { buildOpening, type OpeningScenario } from "./opening";
import type { Comparison, Scenario, StateSnapshot, Town, Trajectories } from "./types";

const openingScenario = scenarioJson as unknown as OpeningScenario;

export const town = townJson as unknown as Town;
export const scenario = openingScenario as unknown as Scenario;
export const publishedState: StateSnapshot = buildOpening(openingScenario, town);
export const trajectories = trajectoriesJson as unknown as Trajectories;
export const publishedComparison = comparisonJson as unknown as Comparison;
export const publishedScatter = scatterFromEnvelopes(wsEventsJson);

/** First keyframe where the river is on the roads, so the fixture map opens on the flood. */
export const fixtureClock =
  scenario.hazard.keyframes.find((frame) => frame.t_s >= 5400)?.t_s
  ?? scenario.hazard.keyframes[0]?.t_s
  ?? publishedState.t_s;

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

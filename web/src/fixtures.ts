import comparisonJson from "../../contracts/fixtures/comparison.fixture.json";
import wsEventsJson from "../../contracts/fixtures/ws-events.fixture.json";
import townJson from "../../contracts/fixtures/town.fixture.json";
import scenarioJson from "../../scenarios/allston_flood_v1/scenario.json";
import playbackJson from "../../contracts/fixtures/playback.fixture.json";
import playbackBaselineJson from "../../contracts/fixtures/playback.baseline.fixture.json";
import { scatterFromEnvelopes } from "./live";
import { buildOpening, type OpeningScenario } from "./opening";
import type { Playback } from "./playback";
import type { Comparison, Scenario, StateSnapshot, Town } from "./types";

const openingScenario = scenarioJson as unknown as OpeningScenario;

export const town = townJson as unknown as Town;
export const scenario = openingScenario as unknown as Scenario;
export const publishedState: StateSnapshot = buildOpening(openingScenario, town);
export const publishedComparison = comparisonJson as unknown as Comparison;
export const publishedScatter = scatterFromEnvelopes(wsEventsJson);
/** allston_flood_v1 simulated end to end (`ember playback --fixtures`): EMBER's plan and the baseline. */
export const fixturePlaybacks: { ember: Playback; baseline: Playback } = {
  ember: playbackJson as unknown as Playback,
  baseline: playbackBaselineJson as unknown as Playback,
};

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
/** The drill line players text "JOIN EMBER" to (the QR card). */
export const JOIN_NUMBER = import.meta.env.VITE_JOIN_NUMBER ?? null;

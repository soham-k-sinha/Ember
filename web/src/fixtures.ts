import scenarioJson from "../../contracts/fixtures/scenario.fixture.json";
import stateJson from "../../contracts/fixtures/state.fixture.json";
import townJson from "../../contracts/fixtures/town.fixture.json";
import trajectoriesJson from "../../contracts/fixtures/trajectories.fixture.json";
import type { Comparison, Scenario, StateSnapshot, Town, Trajectories } from "./types";

export const town = townJson as unknown as Town;
export const scenario = scenarioJson as unknown as Scenario;
export const publishedState = stateJson as unknown as StateSnapshot;
export const trajectories = trajectoriesJson as unknown as Trajectories;

const comparisonModules = import.meta.glob("../../contracts/fixtures/comparison.fixture.json", {
  eager: true,
  import: "default",
}) as Record<string, Comparison>;

export const publishedComparison: Comparison | null =
  Object.values(comparisonModules)[0] ?? null;

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

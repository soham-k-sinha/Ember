import comparisonJson from "../../contracts/fixtures/comparison.fixture.json";
import scenarioJson from "../../contracts/fixtures/scenario.fixture.json";
import stateJson from "../../contracts/fixtures/state.fixture.json";
import townJson from "../../contracts/fixtures/town.fixture.json";
import trajectoriesJson from "../../contracts/fixtures/trajectories.fixture.json";
import type { Comparison, Scenario, StateSnapshot, Town, Trajectories } from "./types";

export const town = townJson as unknown as Town;
export const scenario = scenarioJson as unknown as Scenario;
export const publishedState = stateJson as unknown as StateSnapshot;
export const trajectories = trajectoriesJson as unknown as Trajectories;
export const publishedComparison = comparisonJson as unknown as Comparison;

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

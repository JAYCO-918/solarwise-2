import type { AnalysisDetail, DecisionRules, Meta, Plant, ReferenceSchema } from "../api/types";
import cleanNow from "./fixtures/analysis_clean_now.json";
import missingData from "./fixtures/analysis_missing_data.json";
import unprofitable from "./fixtures/analysis_unprofitable.json";
import decisionRules from "./fixtures/decision_rules.json";
import meta from "./fixtures/meta.json";
import plant from "./fixtures/plant.json";
import referenceSchema from "./fixtures/reference_schema.json";

/** A deep copy, so that a test can change a fixture without affecting the others. */
function copy<T>(value: unknown): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export const fixtures = {
  /** Scenario 2: every gate passed, CLEAN_NOW, simulated. */
  cleanNow: () => copy<AnalysisDetail>(cleanNow),
  /** Scenario 7: INVESTIGATE; some gates failed and some could not be evaluated. */
  missingData: () => copy<AnalysisDetail>(missingData),
  /** Scenario 10: soiling is real but cleaning does not pay; MONITOR. */
  unprofitable: () => copy<AnalysisDetail>(unprofitable),
  decisionRules: () => copy<DecisionRules>(decisionRules),
  meta: () => copy<Meta>(meta),
  plant: () => copy<Plant>(plant),
  referenceSchema: () => copy<ReferenceSchema>(referenceSchema),
};

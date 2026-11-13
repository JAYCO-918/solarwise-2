import type {
  AiStatus,
  AnalysisDetail,
  DataReview,
  DecisionRules,
  InsightOut,
  Meta,
  Plant,
  ReferenceSchema,
  UploadCheck,
  UploadPreviewOut,
} from "../api/types";
import aiStatusOff from "./fixtures/ai_status_off.json";
import aiStatusOn from "./fixtures/ai_status_on.json";
import cleanNow from "./fixtures/analysis_clean_now.json";
import missingData from "./fixtures/analysis_missing_data.json";
import unprofitable from "./fixtures/analysis_unprofitable.json";
import dataReview from "./fixtures/data_review.json";
import decisionRules from "./fixtures/decision_rules.json";
import insightAi from "./fixtures/insight_ai.json";
import insightEngine from "./fixtures/insight_engine.json";
import meta from "./fixtures/meta.json";
import plant from "./fixtures/plant.json";
import referenceSchema from "./fixtures/reference_schema.json";
import uploadCheck from "./fixtures/upload_check.json";
import uploadPreview from "./fixtures/upload_preview.json";

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
  /** An operator's export at first look: its own headers, a column the reader cannot place, three alarms. */
  uploadPreview: () => copy<UploadPreviewOut>(uploadPreview),
  /** The same file validated with what the uploader declared: accepted, two cells rejected, three events. */
  uploadCheck: () => copy<UploadCheck>(uploadCheck),
  /** What a stand-in model suggested for that file, after the server's checks (one proposal discarded). */
  dataReview: () => copy<DataReview>(dataReview),
  /** Scenario 7 read by the engine alone: nothing stored, no language model. */
  insightEngine: () => copy<InsightOut>(insightEngine),
  /** Scenario 2 with a narrative written by a stand-in model and accepted by the server's checks. */
  insightAi: () => copy<InsightOut>(insightAi),
  aiStatusOff: () => copy<AiStatus>(aiStatusOff),
  aiStatusOn: () => copy<AiStatus>(aiStatusOn),
};

/**
 * Types of the API.
 *
 * `schema.d.ts` is generated from the backend's OpenAPI description (`npm run gen:api`); nothing in it is written
 * by hand. A backend test fails when `openapi.json` no longer matches the code.
 */
import type { components } from "./schema";

type S = components["schemas"];

/**
 * Responses always carry every field (the server serialises defaults), but the schema marks fields that have a
 * default as optional. This removes the `undefined` from response types; `null` - "not available" - stays.
 */
export type DeepRequired<T> = T extends (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<T[K]> }
    : T;

// ----------------------------------------------------------------------------- responses
export type User = DeepRequired<S["UserOut"]>;
export type Token = DeepRequired<S["TokenOut"]>;
export type Plant = DeepRequired<S["PlantOut"]>;
export type PlantSpec = DeepRequired<S["PlantSpec"]>;
export type Device = DeepRequired<S["DeviceOut"]>;
export type Permission = DeepRequired<S["PermissionOut"]>;
export type Dataset = DeepRequired<S["DatasetOut"]>;
export type DatasetDetail = DeepRequired<S["DatasetDetail"]>;
export type Channel = DeepRequired<S["ChannelOut"]>;
export type UploadCheck = DeepRequired<S["UploadCheck"]>;
export type ValidationReport = DeepRequired<S["ValidationReport"]>;
export type ValidationIssue = DeepRequired<S["ValidationIssue"]>;
export type EvidenceRow = DeepRequired<S["EvidenceOut"]>;
export type AnalysisSummary = DeepRequired<S["AnalysisSummary"]>;
export type AnalysisDetail = DeepRequired<S["AnalysisDetail"]>;
export type AnalysisResult = AnalysisDetail["result"];
export type Recommendation = AnalysisResult["recommendation"];
export type Gate = DeepRequired<S["Gate"]>;
export type Hypothesis = DeepRequired<S["Hypothesis"]>;
export type AttributionScope = DeepRequired<S["AttributionScope"]>;
export type FactorContribution = DeepRequired<S["FactorContribution"]>;
export type DailyGap = DeepRequired<S["DailyGap"]>;
export type DailyAttribution = DeepRequired<S["DailyAttribution"]>;
export type ProvenanceTag = DeepRequired<S["ProvenanceTag"]>;
export type Traced = DeepRequired<S["Traced"]>;
export type EconomicsResult = DeepRequired<S["EconomicsResult"]>;
export type RecoverableEnergy = DeepRequired<S["RecoverableEnergy"]>;
export type AiExplanation = DeepRequired<S["AiExplanation"]>;
export type UploadPreviewOut = DeepRequired<S["UploadPreviewOut"]>;
export type UploadPreview = UploadPreviewOut["preview"];
export type ColumnPreview = DeepRequired<S["ColumnPreview"]>;
export type DataNote = DeepRequired<S["DataNote"]>;
export type MappingProposal = UploadPreview["proposal"];
export type DataReview = DeepRequired<S["DataReview"]>;
export type DataSuggestion = DeepRequired<S["DataSuggestion"]>;
export type EventSummary = DeepRequired<S["EventSummary"]>;
export type InsightOut = DeepRequired<S["InsightOut"]>;
export type Insight = InsightOut["insight"];
export type InsightCause = DeepRequired<S["InsightCause"]>;
export type InsightItem = DeepRequired<S["InsightItem"]>;
export type InsightGate = DeepRequired<S["InsightGate"]>;
export type GuardrailCheck = DeepRequired<S["GuardrailCheck"]>;
export type AiStatus = DeepRequired<S["AiStatus"]>;
export type ForecastResponse = DeepRequired<S["ForecastResponse"]>;
export type PerformanceForecast = ForecastResponse["forecast"];
export type EconomicsResponse = DeepRequired<S["EconomicsResponse"]>;
export type EvaluateResponse = DeepRequired<S["EvaluateResponse"]>;
export type Stage = DeepRequired<S["StageStatus"]>;
export type SoilingEvidence = DeepRequired<S["SoilingEvidence"]>;
export type PvgisMonth = DeepRequired<S["PvgisMonth"]>;
export type Decision = S["Decision"];
export type Provenance = S["Provenance"];

// ----------------------------------------------------------------------------- requests (optional fields stay optional)
export type PlantSpecIn = S["PlantSpec"];
export type AnalysisOptionsIn = S["AnalysisOptions"];
export type CleaningAssumptionsIn = S["CleaningAssumptions"];
export type EconomicInputsIn = S["EconomicInputs"];
export type DatasetMetadataIn = S["DatasetMetadata"];
export type ChannelDeclarationIn = S["ChannelDeclaration"];
export type EvidenceIn = S["EvidenceIn"];
export type DeviceIn = S["DeviceIn"];
export type UserCreate = S["UserCreate"];
export type RegisterRequest = S["RegisterRequest"];
export type UserUpdate = S["UserUpdate"];

// ----------------------------------------------------------------------------- endpoints without a response model
export interface Meta {
  name: string;
  version: string;
  engine_version: string;
  demo_mode: boolean;
  /** Whether visitors may create their own account. Absent on a server that predates sign-up: read as closed. */
  registration_open?: boolean;
  demo_statement: string | null;
  demo_limits: { max_upload_mb: number; max_datasets_per_plant: number } | null;
  max_upload_mb: number;
  external_data_enabled: boolean;
  ai: { enabled: boolean; provider: string | null; role: string };
  schema_revision: string;
}

export interface Series {
  dataset_id: number;
  interval_minutes: number;
  timezone: string;
  truncated: boolean;
  start_utc: string[];
  columns: Record<string, (number | null)[]>;
  units: Record<string, string>;
  devices: string[];
}

export interface MetricSpec {
  metric: string;
  column: string;
  unit: string;
  dimension: string;
  table: string;
  description: string;
  minimum: number | null;
  maximum: number | null;
  /** Units a column of this quantity may be declared in; irradiation also takes irradiance (W/m2). */
  accepted_units?: string[];
}

/** A file offered for download: column names only (template), or with invented values (example). */
export interface UploadTemplate {
  name: string;
  title: string;
  description: string;
  example: boolean;
}

export interface EventsReference {
  principle: string;
  cleaning_marks: string[];
  no_event_cells: string[];
  vocabulary: { evidence_type: string; matches: string }[];
  unmatched: string;
  max_events_per_file: number;
}

export interface ReferenceSchema {
  metrics: MetricSpec[];
  units: Record<string, { canonical: string; accepted: string[] }>;
  provenance: { value: Provenance; meaning: string }[];
  evidence_types: string[];
  inspection_findings: string[];
  soiling_methods: { value: string; direct: boolean }[];
  baseline_methods: string[];
  metering_boundaries: string[];
  irradiance_planes: string[];
  tracking_types: string[];
  energy_value_bases: string[];
  value_classifications: string[];
  limits: { max_rows: number; max_columns: number };
  missing_values: string;
  events?: EventsReference;
  templates?: UploadTemplate[];
}

export interface DecisionRules {
  engine_version: string;
  principle: string;
  gates: { id: string; label: string; requirement: string }[];
  rules: { id: string; outcome: Decision; applies_when: string; rationale: string }[];
  thresholds: { name: string; default: number; description: string }[];
}

export interface EconomicReference {
  key: string;
  label: string;
  category: string;
  classification: string;
  /** `null` when no amount is stored - which is the case of every entry that could not be verified. */
  amount: number | null;
  currency: string | null;
  unit: string | null;
  source_title: string;
  source_reference: string;
  verification_status: string;
  applicability: string;
  notes: string;
}

export interface EconomicReferences {
  statement: string;
  entries: EconomicReference[];
}

/** What a demonstration dataset says about itself (`Dataset.scenario`). */
export interface ScenarioInfo {
  key: string;
  number: number;
  title: string;
  story: string;
  injected: string[];
  expected_decision: Decision;
  expected_rule: string;
  expected_diagnostic_status: string;
  cleaning: CleaningAssumptionsIn | null;
  economics: EconomicInputsIn | null;
  seed: number;
}

export function scenarioOf(dataset: { scenario: unknown }): ScenarioInfo | null {
  const value = dataset.scenario as Partial<ScenarioInfo> | null;
  return value && typeof value.key === "string" && typeof value.title === "string" ? (value as ScenarioInfo) : null;
}

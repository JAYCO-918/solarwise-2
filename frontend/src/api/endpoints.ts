import { api, download } from "./client";
import type {
  AiExplanation,
  AiStatus,
  AnalysisDetail,
  AnalysisOptionsIn,
  AnalysisSummary,
  DataReview,
  Dataset,
  DatasetDetail,
  DatasetMetadataIn,
  DecisionRules,
  Device,
  DeviceIn,
  EconomicInputsIn,
  EconomicReferences,
  EconomicsResponse,
  EvaluateResponse,
  EvidenceIn,
  EvidenceRow,
  ForecastResponse,
  InsightOut,
  Meta,
  Permission,
  Plant,
  PlantSpecIn,
  PvgisMonth,
  ReferenceSchema,
  RegisterRequest,
  Series,
  Token,
  UploadCheck,
  UploadPreviewOut,
  User,
  UserCreate,
  UserUpdate,
} from "./types";

type Signal = AbortSignal | undefined;

export interface EconomicsCalculation {
  recoverable_low_kwh: number | null;
  recoverable_base_kwh: number | null;
  recoverable_high_kwh: number | null;
  inputs: EconomicInputsIn;
  horizon_days: number | null;
  projected_daily_clean_energy_kwh?: number | null;
  cleaning_effectiveness?: number | null;
}

function uploadForm(file: File, metadata: DatasetMetadataIn | null = null): FormData {
  const form = new FormData();
  form.append("file", file, file.name);
  if (metadata !== null) form.append("metadata", JSON.stringify(metadata));
  return form;
}

export const endpoints = {
  meta: (signal?: Signal) => api.get<Meta>("/meta", { signal }),

  login: (email: string, password: string) => api.post<Token>("/auth/login", { email, password }),
  register: (body: RegisterRequest) => api.post<Token>("/auth/register", body),
  demoLogin: () => api.post<Token>("/auth/demo-login"),
  me: (signal?: Signal) => api.get<User>("/auth/me", { signal }),

  users: (signal?: Signal) => api.get<User[]>("/users", { signal }),
  createUser: (body: UserCreate) => api.post<User>("/users", body),
  updateUser: (id: number, body: UserUpdate) => api.patch<User>(`/users/${id}`, body),

  plants: (signal?: Signal) => api.get<Plant[]>("/plants", { signal }),
  plant: (id: number, signal?: Signal) => api.get<Plant>(`/plants/${id}`, { signal }),
  createPlant: (spec: PlantSpecIn, description: string) => api.post<Plant>("/plants", { spec, description }),
  updatePlant: (id: number, spec: Partial<PlantSpecIn>, description: string | null) =>
    api.patch<Plant>(`/plants/${id}`, { spec, description }),
  deletePlant: (id: number) => api.delete(`/plants/${id}`),

  devices: (plantId: number, signal?: Signal) => api.get<Device[]>(`/plants/${plantId}/devices`, { signal }),
  addDevice: (plantId: number, body: DeviceIn) => api.post<Device>(`/plants/${plantId}/devices`, body),
  removeDevice: (plantId: number, deviceId: number) => api.delete(`/plants/${plantId}/devices/${deviceId}`),

  permissions: (plantId: number, signal?: Signal) => api.get<Permission[]>(`/plants/${plantId}/permissions`, { signal }),
  grant: (plantId: number, email: string, role: string) =>
    api.put<Permission>(`/plants/${plantId}/permissions`, { email, role }),
  revoke: (plantId: number, userId: number) => api.delete(`/plants/${plantId}/permissions/${userId}`),

  setPvgis: (plantId: number, months: PvgisMonth[], source: string) =>
    api.put<Plant>(`/plants/${plantId}/pvgis`, { months, source }),
  fetchPvgis: (plantId: number) => api.post<Plant>(`/plants/${plantId}/pvgis/fetch`, {}),
  nasaPower: (plantId: number, start: string, end: string, store: boolean) =>
    api.post<UploadCheck>(`/plants/${plantId}/weather/nasa-power`, { start, end, store }),

  datasets: (plantId: number, signal?: Signal) => api.get<Dataset[]>(`/plants/${plantId}/datasets`, { signal }),
  dataset: (id: number, signal?: Signal) => api.get<DatasetDetail>(`/datasets/${id}`, { signal }),
  series: (id: number, signal?: Signal) => api.get<Series>(`/datasets/${id}/series`, { signal }),
  archiveDataset: (id: number) => api.delete(`/datasets/${id}`),
  /** A first look at a file: its first rows and what its columns probably are. Nothing is declared or stored. */
  previewUpload: (plantId: number, file: File, signal?: Signal) =>
    api.upload<UploadPreviewOut>(`/plants/${plantId}/datasets/preview`, uploadForm(file), { signal }),
  /** Suggestions of the language model on the proposed mapping. Nothing is applied by the server. */
  reviewUpload: (plantId: number, file: File) =>
    api.upload<DataReview>(`/plants/${plantId}/datasets/ai-review`, uploadForm(file)),
  validateUpload: (plantId: number, file: File, metadata: DatasetMetadataIn | null) =>
    api.upload<UploadCheck>(`/plants/${plantId}/datasets/validate`, uploadForm(file, metadata)),
  /** The rows that would be rejected, as they are in the file, with the reason next to each (CSV). */
  downloadRejectedRows: (plantId: number, file: File, metadata: DatasetMetadataIn | null) =>
    download(`/plants/${plantId}/datasets/rejected-rows`, "rejected-rows.csv", uploadForm(file, metadata)),
  importUpload: (plantId: number, file: File, metadata: DatasetMetadataIn | null) =>
    api.upload<UploadCheck>(`/plants/${plantId}/datasets`, uploadForm(file, metadata)),

  evidence: (plantId: number, signal?: Signal) => api.get<EvidenceRow[]>(`/plants/${plantId}/evidence`, { signal }),
  addEvidence: (plantId: number, body: EvidenceIn) => api.post<EvidenceRow>(`/plants/${plantId}/evidence`, body),
  deleteEvidence: (plantId: number, evidenceId: number) => api.delete(`/plants/${plantId}/evidence/${evidenceId}`),

  analyses: (plantId: number, signal?: Signal) => api.get<AnalysisSummary[]>(`/plants/${plantId}/analyses`, { signal }),
  analysis: (id: number, signal?: Signal) => api.get<AnalysisDetail>(`/analyses/${id}`, { signal }),
  runAnalysis: (datasetId: number, options: AnalysisOptionsIn, weatherDatasetId: number | null) =>
    api.post<AnalysisDetail>(`/datasets/${datasetId}/analyses`, { options, weather_dataset_id: weatherDatasetId }),
  explanation: (analysisId: number) => api.post<AiExplanation>(`/analyses/${analysisId}/explanation`),
  aiStatus: (signal?: Signal) => api.get<AiStatus>("/ai/status", { signal }),
  /** The interpretation last generated for the analysis - or the engine's own when none was. No model is called. */
  insight: (analysisId: number, signal?: Signal) => api.get<InsightOut>(`/analyses/${analysisId}/insight`, { signal }),
  /** Ask the language model (when one is configured) to interpret the analysis; the result is stored. */
  generateInsight: (analysisId: number) => api.post<InsightOut>(`/analyses/${analysisId}/insight`),
  forecast: (analysisId: number, horizonDays: number, signal?: Signal) =>
    api.get<ForecastResponse>(`/analyses/${analysisId}/forecast`, { signal, query: { horizon_days: horizonDays } }),

  calculateEconomics: (body: EconomicsCalculation) => api.post<EconomicsResponse>("/economics/calculate", body),
  evaluateCase: (body: unknown) => api.post<EvaluateResponse>("/recommendations/evaluate", body),

  referenceSchema: (signal?: Signal) => api.get<ReferenceSchema>("/reference/schema", { signal }),
  decisionRules: (signal?: Signal) => api.get<DecisionRules>("/reference/decision-rules", { signal }),
  economicReferences: (signal?: Signal) => api.get<EconomicReferences>("/reference/economic", { signal }),
};

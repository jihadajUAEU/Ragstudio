import type {
  DiagnosticsOut,
  DocumentOut,
  DomainMetadata,
  DomainProfileOut,
  EmbeddingConnectionTestOut,
  EvaluationSetOut,
  ExperimentIn,
  ExperimentOut,
  ExperimentPage,
  GraphOut,
  HealthOut,
  JobOut,
  JobQualityWarningRepairOut,
  JobQualityWarningsOut,
  IndexDocumentIn,
  LlmConnectionTestOut,
  MinerUConnectionTestOut,
  OptimizerIn,
  OptimizerOut,
  Page,
  ParserMode,
  ProviderSyncPreviewIn,
  ProviderSyncPreviewOut,
  RerankerConnectionTestOut,
  ChunkSearchIn,
  ChunkSearchOut,
  QueryIn,
  QueryOut,
  RunOut,
  SimulateRetrievalIn,
  SimulateRetrievalOut,
  SettingsProfileIn,
  SettingsProfileOut,
  VariantIn,
  VariantOut,
  VariantUpdate,
} from "./generated";
import type { DocumentParseEvidence } from "../features/document-evidence/types";

export const DEFAULT_PARSER_MODE: ParserMode = "mineru_strict";

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface ReindexDocumentOut {
  document_id: string;
  job_id: string;
  status: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const message =
      typeof body === "object" && body !== null && "detail" in body
        ? formatApiDetail(body.detail)
        : `Request failed with ${response.status}`;
    throw new ApiError(message, response.status, body);
  }

  return body as T;
}

function formatApiDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          const location = "loc" in item && Array.isArray(item.loc) ? item.loc.join(".") : "";
          return location ? `${location}: ${String(item.msg)}` : String(item.msg);
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  if (typeof detail === "object" && detail !== null) {
    return JSON.stringify(detail);
  }
  return String(detail);
}

export const apiClient = {
  health: () => request<HealthOut>("/api/health"),
  documents: () => request<Page<DocumentOut>>("/api/documents"),
  documentParseEvidence: (documentId: string) =>
    request<DocumentParseEvidence>(`/api/documents/${encodeURIComponent(documentId)}/parse-evidence`),
  uploadDocument: ({ file, options }: { file: File; options: IndexDocumentIn }) => {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("parser_mode", options.parser_mode ?? DEFAULT_PARSER_MODE);
    formData.set("domain_metadata", JSON.stringify(options.domain_metadata ?? {}));
    if (options.mineru_parse_options) {
      formData.set("mineru_parse_options", JSON.stringify(options.mineru_parse_options));
    }
    return request<DocumentOut>("/api/documents", {
      method: "POST",
      body: formData,
    });
  },
  deleteDocument: (documentId: string) =>
    request<void>(`/api/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    }),
  createDocumentReindexJob: (documentId: string, payload: IndexDocumentIn = {}) =>
    request<ReindexDocumentOut>(`/api/documents/${encodeURIComponent(documentId)}/reindex`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  jobs: () => request<Page<JobOut>>("/api/jobs"),
  jobQualityWarnings: (jobId: string) =>
    request<JobQualityWarningsOut>(
      `/api/jobs/${encodeURIComponent(jobId)}/quality-warnings?limit=5000`,
    ),
  fixJobQualityWarnings: (jobId: string) =>
    request<JobQualityWarningRepairOut>(
      `/api/jobs/${encodeURIComponent(jobId)}/quality-warnings/fix`,
      { method: "POST" },
    ),
  variants: () => request<Page<VariantOut>>("/api/variants"),
  createVariant: (payload: VariantIn) =>
    request<VariantOut>("/api/variants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateVariant: (variantId: string, payload: VariantUpdate) =>
    request<VariantOut>(`/api/variants/${encodeURIComponent(variantId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteVariant: (variantId: string) =>
    request<void>(`/api/variants/${encodeURIComponent(variantId)}`, {
      method: "DELETE",
    }),
  defaultSettings: () => request<SettingsProfileOut>("/api/settings/default"),
  updateDefaultSettings: (payload: SettingsProfileIn) =>
    request<SettingsProfileOut>("/api/settings/default", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testEmbeddingSettings: (payload: SettingsProfileIn) =>
    request<EmbeddingConnectionTestOut>("/api/settings/default/test-embedding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testLlmSettings: (payload: SettingsProfileIn) =>
    request<LlmConnectionTestOut>("/api/settings/default/test-llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testRerankerSettings: (payload: SettingsProfileIn) =>
    request<RerankerConnectionTestOut>("/api/settings/default/test-reranker", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  testMinerUSettings: (payload: SettingsProfileIn) =>
    request<MinerUConnectionTestOut>("/api/settings/default/test-mineru", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  syncProviderPreview: (payload: ProviderSyncPreviewIn) =>
    request<ProviderSyncPreviewOut>("/api/settings/default/sync-provider-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  domainProfiles: () => request<Page<DomainProfileOut>>("/api/domain-profiles"),
  getReferenceJsonExample: () =>
    request<{ custom_json: Record<string, unknown> }>(
      "/api/domain-profiles/reference-json-example",
    ),
  suggestDomainMetadata: (payload: { file: File; profile_id?: string | null }) => {
    const formData = new FormData();
    formData.set("file", payload.file);
    if (payload.profile_id) {
      formData.set("profile_id", payload.profile_id);
    }
    return request<{
      domain_metadata: DomainMetadata;
      confidence: number;
      evidence_pages: number[];
      rationale: string;
      warnings: string[];
    }>("/api/domain-profiles/suggest", {
      method: "POST",
      body: formData,
    });
  },
  searchChunks: (payload: ChunkSearchIn) =>
    request<ChunkSearchOut>("/api/chunks/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  query: (payload: QueryIn) =>
    request<QueryOut>("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  simulateRetrieval: (payload: SimulateRetrievalIn) =>
    request<SimulateRetrievalOut>("/api/query/simulate-retrieval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  evaluationSets: () => request<Page<EvaluationSetOut>>("/api/evaluation-sets"),
  importEvaluationSet: ({ file, name }: { file: File; name: string }) => {
    const formData = new FormData();
    formData.set("file", file);
    return request<EvaluationSetOut>(
      `/api/evaluation-sets/import?name=${encodeURIComponent(name)}`,
      {
        method: "POST",
        body: formData,
      },
    );
  },
  createExperiment: (payload: ExperimentIn) =>
    request<ExperimentOut>("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  experiments: () => request<ExperimentPage>("/api/experiments"),
  getExperiment: (experimentId: string) =>
    request<ExperimentOut>(`/api/experiments/${encodeURIComponent(experimentId)}`),
  optimize: (payload: OptimizerIn) =>
    request<OptimizerOut>("/api/optimizer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  runs: () => request<Page<RunOut>>("/api/runs"),
  diagnostics: () => request<DiagnosticsOut>("/api/diagnostics"),
  graph: () => request<GraphOut>("/api/graph"),
};

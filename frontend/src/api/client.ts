import type {
  DiagnosticsOut,
  DocumentOut,
  DocumentPipelineTimelineOut,
  DomainMetadataSuggestOut,
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

export interface RuntimeDefaultsOut {
  llm_timeout_ms: number;
  embedding_timeout_ms: number;
  embedding_dimensions: number;
  embedding_batch_size: number;
  mineru_timeout_ms: number;
  mineru_poll_interval_ms: number;
  mineru_max_concurrent_files: number;
  vision_timeout_ms: number;
  reranker_timeout_ms: number;
  chunk_token_size: number;
  chunk_overlap_token_size: number;
  context_window: number;
  max_context_tokens: number;
  top_k: number;
  chunk_top_k: number;
  cosine_better_than_threshold: number;
  max_total_tokens: number;
  max_entity_tokens: number;
  max_relation_tokens: number;
  llm_model_max_async: number;
  embedding_func_max_async: number;
  max_parallel_insert: number;
}

export interface DefaultsOut {
  runtime: RuntimeDefaultsOut;
  policy_versions: Record<string, string>;
}

export type ApiQueryOptions = Record<string, string | number | boolean | null | undefined>;
export type PageQueryOptions = Pick<ApiQueryOptions, "limit" | "offset">;
export const FIRST_LIST_PAGE: PageQueryOptions = { limit: 500, offset: 0 };
export const DOCUMENT_EVIDENCE_QUERY: ApiQueryOptions = {
  warning_limit: 20000,
  warning_offset: 0,
};

export function jobEventsUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${encodeURIComponent(jobId)}/events`;
}

export function createJobEventSource(jobId: string): EventSource | null {
  if (typeof EventSource === "undefined") {
    return null;
  }
  return new EventSource(jobEventsUrl(jobId));
}

function withQuery(path: string, options?: ApiQueryOptions): string {
  if (!options) {
    return path;
  }
  const params = new URLSearchParams();
  Object.entries(options).forEach(([key, value]) => {
    if (value !== null && value !== undefined) {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
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
  defaults: () => request<DefaultsOut>("/api/defaults"),
  documents: (options: PageQueryOptions = FIRST_LIST_PAGE) =>
    request<Page<DocumentOut>>(withQuery("/api/documents", options)),
  documentParseEvidence: (documentId: string, options: ApiQueryOptions = DOCUMENT_EVIDENCE_QUERY) =>
    request<DocumentParseEvidence>(
      withQuery(`/api/documents/${encodeURIComponent(documentId)}/parse-evidence`, options),
    ),
  documentPipelineTimeline: (documentId: string) =>
    request<DocumentPipelineTimelineOut>(
      `/api/documents/${encodeURIComponent(documentId)}/pipeline-timeline`,
    ),
  uploadDocument: ({ file, options }: { file: File; options: IndexDocumentIn }) => {
    const formData = new FormData();
    formData.set("file", file);
    formData.set("parser_mode", options.parser_mode ?? DEFAULT_PARSER_MODE);
    formData.set("domain_metadata", JSON.stringify(options.domain_metadata ?? {}));
    if (options.analysis_binding) {
      formData.set("analysis_binding", JSON.stringify(options.analysis_binding));
    }
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
  jobs: (options: PageQueryOptions = FIRST_LIST_PAGE) =>
    request<Page<JobOut>>(withQuery("/api/jobs", options)),
  jobEventsUrl,
  createJobEventSource,
  jobQualityWarnings: (jobId: string) =>
    request<JobQualityWarningsOut>(
      `/api/jobs/${encodeURIComponent(jobId)}/quality-warnings?limit=5000`,
    ),
  fixJobQualityWarnings: (jobId: string) =>
    request<JobQualityWarningRepairOut>(
      `/api/jobs/${encodeURIComponent(jobId)}/quality-warnings/fix`,
      { method: "POST" },
    ),
  variants: (options: PageQueryOptions = FIRST_LIST_PAGE) =>
    request<Page<VariantOut>>(withQuery("/api/variants", options)),
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
    return request<DomainMetadataSuggestOut>("/api/domain-profiles/suggest", {
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
  experiments: (options: PageQueryOptions = FIRST_LIST_PAGE) =>
    request<ExperimentPage>(withQuery("/api/experiments", options)),
  getExperiment: (experimentId: string) =>
    request<ExperimentOut>(`/api/experiments/${encodeURIComponent(experimentId)}`),
  optimize: (payload: OptimizerIn) =>
    request<OptimizerOut>("/api/optimizer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  runs: (options: PageQueryOptions = FIRST_LIST_PAGE) =>
    request<Page<RunOut>>(withQuery("/api/runs", options)),
  diagnostics: () => request<DiagnosticsOut>("/api/diagnostics"),
  graph: (options?: ApiQueryOptions) => request<GraphOut>(withQuery("/api/graph", options)),
};

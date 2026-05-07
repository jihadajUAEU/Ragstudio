import type {
  DiagnosticsOut,
  DocumentOut,
  EvaluationSetOut,
  ExperimentIn,
  ExperimentOut,
  GraphOut,
  HealthOut,
  JobOut,
  OptimizerIn,
  OptimizerOut,
  Page,
  ChunkOut,
  ChunkSearchIn,
  ChunkSearchOut,
  QueryIn,
  QueryOut,
  RunOut,
  SettingsProfileIn,
  SettingsProfileOut,
  VariantIn,
  VariantOut,
} from "./generated";

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
        ? String(body.detail)
        : `Request failed with ${response.status}`;
    throw new ApiError(message, response.status, body);
  }

  return body as T;
}

export const apiClient = {
  health: () => request<HealthOut>("/api/health"),
  documents: () => request<Page<DocumentOut>>("/api/documents"),
  uploadDocument: (file: File) => {
    const formData = new FormData();
    formData.set("file", file);
    return request<DocumentOut>("/api/documents", {
      method: "POST",
      body: formData,
    });
  },
  jobs: () => request<Page<JobOut>>("/api/jobs"),
  variants: () => request<Page<VariantOut>>("/api/variants"),
  createVariant: (payload: VariantIn) =>
    request<VariantOut>("/api/variants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  defaultSettings: () => request<SettingsProfileOut>("/api/settings/default"),
  updateDefaultSettings: (payload: SettingsProfileIn) =>
    request<SettingsProfileOut>("/api/settings/default", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
  }),
  indexDocumentChunks: (documentId: string) =>
    request<ChunkOut[]>(`/api/chunks/index/${encodeURIComponent(documentId)}`, {
      method: "POST",
    }),
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
  optimize: async (payload: OptimizerIn) => {
    const init = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
    try {
      return await request<OptimizerOut>("/api/optimizer/recommend", init);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return request<OptimizerOut>("/api/optimizer", init);
      }
      throw error;
    }
  },
  runs: () => request<Page<RunOut>>("/api/runs"),
  diagnostics: () => request<DiagnosticsOut>("/api/diagnostics"),
  graph: () => request<GraphOut>("/api/graph"),
};

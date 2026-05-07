import type {
  DiagnosticsOut,
  DocumentOut,
  GraphOut,
  HealthOut,
  JobOut,
  Page,
  RunOut,
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
  jobs: () => request<Page<JobOut>>("/api/jobs"),
  variants: () => request<Page<VariantOut>>("/api/variants"),
  runs: () => request<Page<RunOut>>("/api/runs"),
  diagnostics: () => request<DiagnosticsOut>("/api/diagnostics"),
  graph: () => request<GraphOut>("/api/graph"),
};

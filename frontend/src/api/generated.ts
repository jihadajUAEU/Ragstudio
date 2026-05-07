export type StageStatus =
  | "not_configured"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "unsupported";

export interface Page<T> {
  items: T[];
  total: number;
}

export interface HealthOut {
  status: string;
  service: string;
}

export interface DocumentOut {
  id: string;
  filename: string;
  content_type: string;
  sha256: string;
  status: StageStatus;
}

export interface SettingsProfileIn {
  provider: string;
  llm_model: string;
  embedding_model: string;
  storage_backend: string;
}

export interface SettingsProfileOut extends SettingsProfileIn {
  id: string;
}

export interface JobOut {
  id: string;
  type: string;
  status: StageStatus;
  target_id: string | null;
  progress: number;
  logs: string[];
  result: Record<string, unknown>;
}

export interface VariantOut {
  id: string;
  name: string;
  preset: string;
  parameters: Record<string, unknown>;
}

export interface VariantIn {
  name: string;
  preset: string;
  parameters: Record<string, unknown>;
}

export interface RunOut {
  id: string;
  variant_id: string;
  query: string;
  status: StageStatus;
  answer: string;
  sources: Record<string, unknown>[];
  chunk_traces: Record<string, unknown>[];
  timings: Record<string, unknown>;
  error: string | null;
}

export interface DiagnosticsOut {
  capabilities: Record<string, boolean>;
  dependency_status: Record<string, unknown>;
  warnings: string[];
}

export interface GraphOut {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}

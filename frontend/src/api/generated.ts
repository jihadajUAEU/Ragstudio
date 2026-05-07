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

export interface ChunkOut {
  id: string;
  document_id: string;
  text: string;
  source_location: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface ChunkSearchIn {
  query: string;
  document_ids: string[];
  variant_id?: string | null;
  limit: number;
}

export interface ChunkSearchOut {
  items: ChunkOut[];
  total: number;
}

export interface QueryIn {
  query: string;
  document_ids: string[];
  variant_ids: string[];
  limit: number;
}

export interface QueryOut {
  runs: RunOut[];
}

export interface EvaluationCaseIn {
  id: string;
  query: string;
  documents: string[];
  expected_answer: string | null;
  expected_sources: string[];
  must_include: string[];
  must_avoid: string[];
  expected_media: Record<string, unknown>[];
  expected_structure: Record<string, unknown>;
  rubric: Record<string, string>;
  objective: Record<string, unknown>;
  variant_hints: Record<string, string[]>;
}

export interface EvaluationSetOut {
  id: string;
  name: string;
  cases: EvaluationCaseIn[];
}

export interface ExperimentScoreOut {
  id: string;
  run_id: string;
  total: number;
  details: Record<string, unknown>;
}

export interface ExperimentIn {
  name: string;
  document_ids: string[];
  evaluation_set_id: string;
  variant_ids: string[];
  objective: Record<string, unknown>;
}

export interface ExperimentOut extends ExperimentIn {
  id: string;
  runs: RunOut[];
  scores: ExperimentScoreOut[];
}

export interface OptimizerIn {
  experiment_id: string;
  objective: Record<string, unknown>;
}

export interface OptimizerCandidateSummary {
  variant_id: string;
  run_count: number;
  average_score: number;
  total_score: number;
  best_run_id: string | null;
  best_run_score: number | null;
}

export interface OptimizerOut {
  id: string;
  experiment_id: string;
  objective: Record<string, unknown>;
  selected_variant_id: string | null;
  selected_run_id: string | null;
  explanation: string;
  tried_variant_ids: string[];
  candidate_summaries: OptimizerCandidateSummary[];
}

export interface RunOut {
  id: string;
  variant_id: string;
  experiment_id: string | null;
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

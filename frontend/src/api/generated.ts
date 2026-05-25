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
  limit?: number;
  offset?: number;
  has_more?: boolean;
}

export interface HealthOut {
  status: string;
  service: string;
}

export type RuntimeMode = "runtime";
export type RuntimeOverallStatus = "ready" | "degraded" | "failed";
export type RuntimeCheckStatus = "ok" | "warning" | "failed" | "skipped";
export type RuntimeCheckSeverity = "info" | "warning" | "blocking";
export type StorageBackend = "postgres_pgvector_neo4j";
export type RerankerProvider =
  | "disabled"
  | "cohere_compatible"
  | "jina_compatible"
  | "generic_http"
  | "llm";
export type RerankerFallbackProvider = "disabled" | "llm";
export type QueryMode = "mix" | "hybrid" | "local" | "global" | "naive";

export interface RuntimeHealthCheck {
  name: string;
  status: RuntimeCheckStatus;
  severity: RuntimeCheckSeverity;
  latency_ms?: number | null;
  detail: string;
  error_type?: string | null;
  remediation?: string | null;
}

export interface DocumentOut {
  id: string;
  filename: string;
  content_type: string;
  sha256: string;
  status: StageStatus;
  latest_index_options?: IndexDocumentIn | null;
}

export interface SettingsProfileIn {
  provider: string;
  llm_model: string;
  llm_provider?: "openai_compatible";
  llm_base_url?: string | null;
  llm_api_key?: string | null;
  llm_timeout_ms?: number;
  llm_capabilities?: Array<"text" | "vision" | "reasoning">;
  embedding_model: string;
  storage_backend: StorageBackend;
  embedding_provider?: "vllm_openai";
  embedding_base_url?: string | null;
  embedding_api_key?: string | null;
  embedding_timeout_ms?: number;
  embedding_dimensions?: number;
  embedding_batch_size?: number;
  embedding_tls_verify?: boolean;
  mineru_enabled?: boolean;
  mineru_base_url?: string | null;
  mineru_timeout_ms?: number;
  mineru_poll_interval_ms?: number;
  mineru_require_hpc?: boolean;
  mineru_backend?: string;
  mineru_device?: string;
  mineru_lang?: string | null;
  mineru_formula?: boolean;
  mineru_table?: boolean;
  mineru_source?: string | null;
  mineru_max_concurrent_files?: number;
  runtime_mode?: RuntimeMode;
  vision_model?: string | null;
  vision_base_url?: string | null;
  vision_api_key?: string | null;
  vision_timeout_ms?: number;
  reranker_provider?: RerankerProvider;
  reranker_fallback_provider?: RerankerFallbackProvider;
  reranker_model?: string | null;
  reranker_base_url?: string | null;
  reranker_api_key?: string | null;
  reranker_timeout_ms?: number;
  pgvector_schema?: string;
  pgvector_table_prefix?: string;
  neo4j_uri?: string | null;
  neo4j_username?: string | null;
  neo4j_password?: string | null;
  parser?: string;
  parse_method?: string;
  chunk_token_size?: number;
  chunk_overlap_token_size?: number;
  enable_image_processing?: boolean;
  enable_table_processing?: boolean;
  enable_equation_processing?: boolean;
  context_window?: number;
  context_mode?: string;
  max_context_tokens?: number;
  include_headers?: boolean;
  include_captions?: boolean;
  query_mode?: QueryMode;
  top_k?: number;
  chunk_top_k?: number;
  enable_rerank?: boolean;
  cosine_better_than_threshold?: number;
  max_total_tokens?: number;
  max_entity_tokens?: number;
  max_relation_tokens?: number;
  enable_llm_cache?: boolean;
  enable_llm_cache_for_entity_extract?: boolean;
  llm_model_max_async?: number;
  embedding_func_max_async?: number;
  max_parallel_insert?: number;
}

export interface SettingsProfileOut {
  id: string;
  provider: string;
  llm_model: string;
  llm_provider: "openai_compatible";
  llm_base_url: string | null;
  has_llm_api_key: boolean;
  llm_timeout_ms: number;
  llm_capabilities: Array<"text" | "vision" | "reasoning">;
  embedding_model: string;
  storage_backend: StorageBackend;
  embedding_provider: "vllm_openai";
  embedding_base_url: string | null;
  has_embedding_api_key: boolean;
  embedding_timeout_ms: number;
  embedding_dimensions: number;
  embedding_batch_size: number;
  embedding_tls_verify: boolean;
  mineru_enabled: boolean;
  mineru_base_url: string | null;
  mineru_timeout_ms: number;
  mineru_poll_interval_ms: number;
  mineru_require_hpc: boolean;
  mineru_backend: string;
  mineru_device: string;
  mineru_lang: string | null;
  mineru_formula: boolean;
  mineru_table: boolean;
  mineru_source: string | null;
  mineru_max_concurrent_files: number;
  runtime_mode: RuntimeMode;
  vision_model: string | null;
  vision_base_url: string | null;
  has_vision_api_key: boolean;
  vision_timeout_ms: number;
  reranker_provider: RerankerProvider;
  reranker_fallback_provider: RerankerFallbackProvider;
  reranker_model: string | null;
  reranker_base_url: string | null;
  has_reranker_api_key: boolean;
  reranker_timeout_ms: number;
  pgvector_schema: string;
  pgvector_table_prefix: string;
  neo4j_uri: string | null;
  neo4j_username: string | null;
  has_neo4j_password: boolean;
  parser: string;
  parse_method: string;
  chunk_token_size: number;
  chunk_overlap_token_size: number;
  enable_image_processing: boolean;
  enable_table_processing: boolean;
  enable_equation_processing: boolean;
  context_window: number;
  context_mode: string;
  max_context_tokens: number;
  include_headers: boolean;
  include_captions: boolean;
  query_mode: QueryMode;
  top_k: number;
  chunk_top_k: number;
  enable_rerank: boolean;
  cosine_better_than_threshold: number;
  max_total_tokens: number;
  max_entity_tokens: number;
  max_relation_tokens: number;
  enable_llm_cache: boolean;
  enable_llm_cache_for_entity_extract: boolean;
  llm_model_max_async: number;
  embedding_func_max_async: number;
  max_parallel_insert: number;
}

export interface EmbeddingConnectionTestOut {
  ok: boolean;
  provider: string;
  model: string;
  dimensions: number | null;
  latency_ms: number;
  detail: string;
}

export interface LlmConnectionTestOut {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  detail: string;
}

export interface MinerUConnectionTestOut {
  ok: boolean;
  base_url: string;
  latency_ms: number;
  detail: string;
  optimization: {
    requested?: Record<string, unknown>;
    reported?: Record<string, unknown>;
    capacity_reported?: boolean;
    warning?: string | null;
    backend?: unknown;
    device?: unknown;
    max_concurrent_files?: unknown;
  };
}

export interface RerankerConnectionTestOut {
  ok: boolean;
  provider: string;
  model: string | null;
  base_url: string | null;
  latency_ms: number;
  detail: string;
}

export interface ProviderSyncPreviewIn {
  manifest_url: string;
}

export interface ProviderSyncPreviewOut {
  ok: boolean;
  manifest_url: string;
  manifest_version?: number | null;
  updated_at?: string | null;
  patch: Partial<SettingsProfileIn>;
  changed_fields: string[];
  ignored_sections: string[];
  detail: string;
}

export type ParserMode = "mineru_strict";

export interface DomainMetadata {
  domain?: string;
  document_type?: string;
  language?: string;
  tags?: string[];
  authority?: string | null;
  source?: string | null;
  collection?: string | null;
  citation_style?: string | null;
  expected_structure?: string | null;
  custom_json?: Record<string, unknown>;
  reference_pattern?: string | null;
  script?: string | null;
  content_role?: string | null;
  metadata_sources?: string[];
}

export interface MinerUParseOptionsIn {
  parser?: string | null;
  parse_method?: string | null;
  backend?: string | null;
  device?: string | null;
  lang?: string | null;
  formula?: boolean | null;
  table?: boolean | null;
  source?: string | null;
  max_concurrent_files?: number | null;
}

export interface DomainProfileOut {
  id: string;
  name: string;
  description: string;
  metadata: DomainMetadata;
}

export interface DomainMetadataSuggestOut {
  domain_metadata: DomainMetadata;
  raw_domain_metadata?: DomainMetadata | null;
  reference_contract_validation?: Record<string, unknown> | null;
  confidence: number;
  evidence_pages: number[];
  rationale: string;
  warnings: string[];
}

export interface IndexDocumentIn {
  parser_mode?: ParserMode;
  domain_metadata?: DomainMetadata;
  mineru_parse_options?: MinerUParseOptionsIn | null;
}

export interface JobOut {
  id: string;
  type: string;
  status: StageStatus;
  target_id: string | null;
  progress: number;
  logs: string[];
  result: Record<string, unknown>;
  worker_id: string | null;
  lease_expires_at: string | null;
  heartbeat_at: string | null;
  attempts: number;
  max_attempts: number;
  recovery_action: string | null;
}

export type PipelineStageState =
  | "pending"
  | "running"
  | "complete"
  | "warning"
  | "blocked"
  | "failed"
  | "skipped"
  | "metadata_only";

export type PipelineEventSource =
  | "document"
  | "structured_event"
  | "inferred_log"
  | "job"
  | "chunk"
  | "index_record"
  | "graph_projection"
  | "contract"
  | "warning";

export interface DocumentPipelineStageOut {
  id: string;
  label: string;
  state: PipelineStageState;
  detail: string;
  order: number;
  category: string;
  icon_hint: string;
  inspector_kind: string;
  progress: number | null;
  is_current: boolean;
  event_count: number;
  warning_count: number;
  chunk_count: number | null;
  source: PipelineEventSource;
  started_at: string | null;
  completed_at: string | null;
  detail_payload: Record<string, unknown>;
}

export interface DocumentPipelineEventOut {
  sequence: number;
  stage_id: string;
  label: string;
  detail: string;
  state: PipelineStageState;
  progress: number | null;
  occurred_at: string | null;
  source: PipelineEventSource;
  job_id: string | null;
  chunk_count: number | null;
  warning: string | null;
  evidence_refs: Record<string, unknown>[];
  detail_payload: Record<string, unknown>;
}

export interface DocumentPipelineWarningGroupOut {
  code: string;
  expected_script: string | null;
  count: number;
  message: string | null;
  sample_chunk_ids: string[];
  sample_references: string[];
  sample_pages: Array<number | string>;
}

export interface DocumentPipelineContractOut {
  contract_status: string | null;
  verified: boolean | null;
  canonical_units: boolean | null;
  schema_type: string | null;
  repair_status: string | null;
  validation_status: string | null;
  validation_matched_units: number | null;
  selected_strategy: string | null;
  rejection_reasons: string[];
  detail_payload: Record<string, unknown>;
}

export interface DocumentPipelineTotalsOut {
  jobs: number;
  chunks: number;
  warnings: number;
  graph_nodes: number;
  graph_edges: number;
  index_records: number;
  graph_records: number;
}

export interface DocumentPipelineTimelineOut {
  document_id: string;
  filename: string;
  status: StageStatus;
  latest_job_id: string | null;
  contract_version: number;
  stages: DocumentPipelineStageOut[];
  events: DocumentPipelineEventOut[];
  contract: DocumentPipelineContractOut;
  warning_groups: DocumentPipelineWarningGroupOut[];
  totals: DocumentPipelineTotalsOut;
  missing_sections: string[];
}

export interface ParserQualityWarningOut {
  chunk_id: string;
  chunk_preview: string;
  source_location: Record<string, unknown>;
  parser_metadata: Record<string, unknown>;
  reference_metadata: Record<string, unknown> | null;
  code: string | null;
  message: string | null;
  block_type: string | null;
  page: number | string | null;
  warning: Record<string, unknown>;
}

export interface JobQualityWarningsOut {
  job_id: string;
  document_id: string | null;
  parser_quality: Record<string, unknown>;
  index_quality_report: Record<string, unknown> | null;
  job_warnings: string[];
  warning_counts: Record<string, number>;
  affected_chunks: number;
  total: number;
  offset: number;
  limit: number;
  truncated: boolean;
  items: ParserQualityWarningOut[];
}

export interface JobQualityWarningRepairOut {
  source_job_id: string;
  document_id: string;
  queued_job_id: string;
  queued_job_status: StageStatus;
  index_options: Record<string, unknown>;
  repair_plan: Record<string, unknown>;
  message: string;
}

export type VariantPreset = "balanced" | "precise" | "broad" | "fast";

export interface VariantOut {
  id: string;
  name: string;
  preset: VariantPreset;
  parameters: Record<string, unknown>;
}

export interface VariantIn {
  name: string;
  preset: VariantPreset;
  parameters: Record<string, unknown>;
}

export interface VariantUpdate {
  name: string;
  preset: VariantPreset;
  parameters?: Record<string, unknown>;
}

export interface ChunkOut {
  id: string;
  document_id: string;
  text: string;
  source_location: Record<string, unknown>;
  metadata: Record<string, unknown>;
  runtime_profile_id?: string | null;
  runtime_source_id?: string | null;
  content_type: string;
  preview_ref?: string | null;
  indexed_at?: string | null;
  retrieval_explain?: Record<string, unknown> | null;
  relationship_refs: Record<string, string>;
}

export interface HybridSearchWeights {
  reference_exact?: number | null;
  neighbor_match?: number | null;
  same_chapter?: number | null;
  exact_phrase?: number | null;
  term_coverage?: number | null;
  semantic_density?: number | null;
  arabic_exact?: number | null;
  arabic_token?: number | null;
  metadata_boost?: number | null;
  domain_intent?: number | null;
}

export interface ChunkSearchIn {
  query: string;
  document_ids: string[];
  variant_id?: string | null;
  limit: number;
  offset?: number;
  explain?: boolean;
  include_neighbors?: boolean;
  search_weights?: HybridSearchWeights | null;
}

export interface ChunkSearchOut {
  items: ChunkOut[];
  total: number;
  has_more?: boolean;
}

export interface QueryIn {
  query: string;
  document_ids: string[];
  variant_ids: string[];
  limit: number;
  response_mode?: "fast" | "full";
  answer_budget_ms?: number | null;
  response_budget_ms?: number | null;
  search_weights?: HybridSearchWeights | null;
}

export interface QueryOut {
  runs: RunOut[];
}

export interface SimulateRetrievalIn {
  query: string;
  document_ids: string[];
  variant_ids?: string[];
  limit?: number;
  search_weights?: HybridSearchWeights | null;
}

export interface SimulateRetrievalOut {
  items: ChunkOut[];
  total: number;
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

export interface ExperimentSummaryOut extends ExperimentIn {
  id: string;
  run_count: number;
  score_count: number;
}

export interface ExperimentPage {
  items: ExperimentSummaryOut[];
  total: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
}

export interface OptimizerIn {
  experiment_id: string;
  objective: Record<string, unknown>;
}

export interface OptimizerCandidateSummary {
  variant_id: string;
  run_count: number;
  average_score: number | null;
  total_score: number | null;
  best_run_id: string | null;
  best_run_score: number | null;
  score_status?: string;
  scoreable_run_count?: number;
  unscored_run_count?: number;
  failed_run_count?: number;
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

export interface PathwayDiagnosticOut {
  stage: string;
  label: string;
  input: string;
  action: string;
  output: string;
  status: "success" | "warning" | "failed" | "skipped" | "unknown";
  time_ms?: number | null;
  budget_ms?: number | null;
  diagnosis: string;
  suggested_action: string;
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
  runtime_profile_id?: string | null;
  document_ids: string[];
  query_config: Record<string, unknown>;
  reranker_traces: Record<string, unknown>[];
  token_metadata: Record<string, unknown>;
  error_type?: string | null;
  pathway_diagnostics?: PathwayDiagnosticOut[];
}

export interface DiagnosticsOut {
  capabilities: Record<string, boolean>;
  dependency_status: Record<string, unknown>;
  warnings: string[];
  runtime_mode: string;
  overall_status: RuntimeOverallStatus;
  checks: RuntimeHealthCheck[];
}

export interface GraphOut {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  detail?: string | null;
  total?: number | null;
  limit?: number | null;
  offset?: number | null;
  has_more?: boolean | null;
}

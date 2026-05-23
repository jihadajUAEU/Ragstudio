export type EvidenceMode = "local" | "public";

export interface DocumentEvidenceSummary {
  id: string;
  filename: string;
  content_type: string;
  status: string;
  page_count?: number | null;
  parser_mode?: string | null;
}

export interface SourceArtifactEvidence {
  id: string;
  kind: string;
  path?: string | null;
  checksum?: string | null;
  href?: string | null;
  preview_available: boolean;
  preview_capped: boolean;
  hidden_count: number;
}

export interface ParserBlockEvidence {
  id: string;
  page?: number | null;
  block_index?: number | null;
  block_type: string;
  text_preview: string;
  bbox?: number[] | null;
  modality?: string | null;
  warning_ids: string[];
}

export type NormalizationDecisionType =
  | "page_stitch"
  | "modal_route"
  | "quality_gate"
  | "quality_warning"
  | "chunk_materialization"
  | "unresolved";

export type DiffRowKind = "added" | "unchanged" | "removed" | "blocked";

export interface DiffRowEvidence {
  id: string;
  kind: DiffRowKind;
  text: string;
  capped?: boolean;
  hidden_count?: number;
}

export interface NormalizationDecisionEvidence {
  id: string;
  decision_type: NormalizationDecisionType;
  title: string;
  summary: string;
  input_block_ids: string[];
  output_chunk_ids: string[];
  warning_ids: string[];
  status: string;
  diff_rows?: DiffRowEvidence[];
}

export interface ChunkEvidence {
  id: string;
  text_preview: string;
  page_start?: number | null;
  page_end?: number | null;
  source_location: Record<string, unknown>;
  metadata: Record<string, unknown>;
  modality?: string | null;
  quality_status?: string | null;
  warning_ids: string[];
}

export interface WarningEvidence {
  id: string;
  code: string;
  message: string;
  severity: string;
  page?: number | null;
  block_id?: string | null;
  block_type?: string | null;
  quality_gate_action?: string | null;
  suppressed_from_counts?: boolean;
  decision_id?: string | null;
  affected_chunk_ids: string[];
}

export interface ProofEvidence {
  source_commit?: string | null;
  source_commit_href?: string | null;
  proof_packet_id?: string | null;
  proof_packet_href?: string | null;
  mode: "local" | "static-fixture" | "export";
  replay_command?: string | null;
  replay_href?: string | null;
  limitations: string[];
  redaction_summary: string[];
}

export interface EvidenceTotals {
  chunks: number;
}

export interface DocumentParseEvidence {
  document: DocumentEvidenceSummary;
  totals?: EvidenceTotals;
  source_artifacts: SourceArtifactEvidence[];
  parser_blocks: ParserBlockEvidence[];
  normalization_decisions: NormalizationDecisionEvidence[];
  chunks: ChunkEvidence[];
  warnings: WarningEvidence[];
  proof: ProofEvidence;
  missing_sections: string[];
}

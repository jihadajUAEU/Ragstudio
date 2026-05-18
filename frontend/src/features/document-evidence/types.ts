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

export interface NormalizationDecisionEvidence {
  id: string;
  decision_type: NormalizationDecisionType;
  title: string;
  summary: string;
  input_block_ids: string[];
  output_chunk_ids: string[];
  warning_ids: string[];
  status: string;
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
  decision_id?: string | null;
  affected_chunk_ids: string[];
}

export interface ProofEvidence {
  source_commit?: string | null;
  proof_packet_id?: string | null;
  mode: "local" | "static-fixture" | "export";
  replay_command?: string | null;
  limitations: string[];
  redaction_summary: string[];
}

export interface DocumentParseEvidence {
  document: DocumentEvidenceSummary;
  source_artifacts: SourceArtifactEvidence[];
  parser_blocks: ParserBlockEvidence[];
  normalization_decisions: NormalizationDecisionEvidence[];
  chunks: ChunkEvidence[];
  warnings: WarningEvidence[];
  proof: ProofEvidence;
  missing_sections: string[];
}

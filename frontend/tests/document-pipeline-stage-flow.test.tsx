import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentPipelineTimelineOut } from "../src/api/generated";
import { DocumentPipelineStageFlow } from "../src/features/document-evidence/document-pipeline-stage-flow";

const timeline: DocumentPipelineTimelineOut = {
  document_id: "doc-quran",
  filename: "quran_arabic_english.pdf",
  status: "running",
  latest_job_id: "job-quran",
  contract_version: 1,
  stages: [
    {
      id: "vision",
      label: "Vision profile",
      state: "complete",
      detail: "religious_text - quran_translation - mixed",
      order: 20,
      category: "domain",
      icon_hint: "vision",
      inspector_kind: "generic",
      progress: null,
      is_current: false,
      event_count: 1,
      warning_count: 0,
      chunk_count: null,
      source: "document",
      started_at: null,
      completed_at: null,
      detail_payload: {},
    },
    {
      id: "contract",
      label: "Contract",
      state: "metadata_only",
      detail: "Reference structure is metadata only and is not enforced.",
      order: 30,
      category: "domain",
      icon_hint: "contract",
      inspector_kind: "contract",
      progress: null,
      is_current: false,
      event_count: 1,
      warning_count: 0,
      chunk_count: null,
      source: "contract",
      started_at: null,
      completed_at: null,
      detail_payload: {},
    },
    {
      id: "chunks_persisting",
      label: "Chunks",
      state: "running",
      detail: "Persisted 4500 of 17699 canonical chunks.",
      order: 70,
      category: "context",
      icon_hint: "chunks",
      inspector_kind: "generic",
      progress: 57,
      is_current: true,
      event_count: 3,
      warning_count: 0,
      chunk_count: 4500,
      source: "structured_event",
      started_at: "2026-05-24T17:16:00+00:00",
      completed_at: null,
      detail_payload: {},
    },
    {
      id: "custom_future_stage",
      label: "Custom future stage",
      state: "warning",
      detail: "Future stage emitted by backend contract.",
      order: 1004,
      category: "custom",
      icon_hint: "stage",
      inspector_kind: "generic",
      progress: null,
      is_current: false,
      event_count: 1,
      warning_count: 1,
      chunk_count: null,
      source: "structured_event",
      started_at: null,
      completed_at: null,
      detail_payload: {},
    },
    {
      id: "quality_gates",
      label: "Quality gates",
      state: "warning",
      detail: "Grouped 2826 parser warnings.",
      order: 90,
      category: "domain",
      icon_hint: "quality",
      inspector_kind: "warnings",
      progress: null,
      is_current: false,
      event_count: 1,
      warning_count: 2826,
      chunk_count: 4500,
      source: "warning",
      started_at: null,
      completed_at: null,
      detail_payload: {},
    },
  ],
  events: [
    {
      sequence: 1,
      stage_id: "vision",
      label: "Vision profile",
      detail: "religious_text - quran_translation - mixed",
      state: "complete",
      progress: null,
      occurred_at: null,
      source: "document",
      job_id: null,
      chunk_count: null,
      warning: null,
      evidence_refs: [],
      detail_payload: {},
    },
    {
      sequence: 2,
      stage_id: "contract",
      label: "Contract",
      detail: "Reference structure is metadata only and is not enforced.",
      state: "metadata_only",
      progress: null,
      occurred_at: null,
      source: "contract",
      job_id: null,
      chunk_count: null,
      warning: null,
      evidence_refs: [],
      detail_payload: {},
    },
    {
      sequence: 3,
      stage_id: "chunks_persisting",
      label: "Chunks",
      detail: "Persisted 4500 of 17699 canonical chunks.",
      state: "running",
      progress: 57,
      occurred_at: "2026-05-24T17:20:00+00:00",
      source: "structured_event",
      job_id: "job-quran",
      chunk_count: 4500,
      warning: null,
      evidence_refs: [],
      detail_payload: {},
    },
  ],
  contract: {
    contract_status: "metadata_only",
    verified: false,
    canonical_units: false,
    schema_type: "chapter_verse",
    repair_status: "unverified",
    validation_status: "unverified",
    validation_matched_units: 0,
    selected_strategy: null,
    rejection_reasons: ["named capture groups missing"],
    detail_payload: {},
  },
  warning_groups: [
    {
      code: "reference_unit_missing_expected_script",
      expected_script: "arabic",
      count: 2730,
      message: "Missing Arabic script.",
      sample_chunk_ids: ["chunk-1"],
      sample_references: ["1:1"],
      sample_pages: [2],
    },
    {
      code: "equation_missing_latex",
      expected_script: null,
      count: 96,
      message: "Equation chunk has no LaTeX content.",
      sample_chunk_ids: ["chunk-2"],
      sample_references: [],
      sample_pages: [],
    },
    {
      code: "reference_unit_unresolved",
      expected_script: null,
      count: 0,
      message: "Reference unit unresolved.",
      sample_chunk_ids: [],
      sample_references: [],
      sample_pages: [],
    },
  ],
  totals: {
    jobs: 1,
    chunks: 4500,
    warnings: 2826,
    graph_nodes: 0,
    graph_edges: 0,
    index_records: 0,
    graph_records: 0,
  },
  missing_sections: [],
};

describe("DocumentPipelineStageFlow", () => {
  it("renders compact rail, flow map, event ledger, and running-stage inspector", () => {
    render(<DocumentPipelineStageFlow timeline={timeline} />);

    expect(screen.getByRole("region", { name: "Document stage flow" })).toBeVisible();
    expect(screen.getByText("quran_arabic_english.pdf")).toBeVisible();
    expect(screen.getByText("4500 chunks")).toBeVisible();
    expect(screen.getByRole("button", { name: /Vision profile/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Contract/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Chunks/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getAllByText("Persisted 4500 of 17699 canonical chunks.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Custom future stage").length).toBeGreaterThan(0);
  });

  it("shows contract proof-boundary details when the contract stage is selected", () => {
    render(<DocumentPipelineStageFlow timeline={timeline} />);

    fireEvent.click(screen.getByRole("button", { name: /Contract/i }));

    const inspector = screen.getByRole("region", { name: "Selected stage inspector" });
    expect(within(inspector).getAllByText("metadata_only").length).toBeGreaterThan(0);
    expect(within(inspector).getByText("verified=false")).toBeVisible();
    expect(within(inspector).getByText("canonical_units=false")).toBeVisible();
    expect(within(inspector).getByText("chapter_verse")).toBeVisible();
    expect(within(inspector).getByText("repair=unverified")).toBeVisible();
    expect(within(inspector).getByText("validation=unverified")).toBeVisible();
    expect(within(inspector).getByText("matched_units=0")).toBeVisible();
    expect(within(inspector).getByText("named capture groups missing")).toBeVisible();
  });

  it("keeps warning groups separated by warning code and expected script", () => {
    render(<DocumentPipelineStageFlow timeline={timeline} />);

    fireEvent.click(screen.getByRole("button", { name: /Quality gates/i }));

    expect(screen.getByText("reference_unit_missing_expected_script")).toBeVisible();
    expect(screen.getByText("arabic")).toBeVisible();
    expect(screen.getByText("equation_missing_latex")).toBeVisible();
    expect(screen.getByText("reference_unit_unresolved")).toBeVisible();
  });

  it("renders backend-provided unknown stages with generic inspector", () => {
    render(
      <DocumentPipelineStageFlow
        timeline={{
          document_id: "doc-generic",
          filename: "generic-reference.pdf",
          status: "succeeded",
          latest_job_id: "job-generic",
          contract_version: 1,
          stages: [
            {
              id: "model_compiler",
              label: "Model compiler",
              state: "complete",
              detail: "Executed generated contract candidates.",
              order: 25,
              category: "custom",
              icon_hint: "stage",
              inspector_kind: "generic",
              source: "job",
              progress: null,
              is_current: false,
              event_count: 1,
              warning_count: 0,
              chunk_count: null,
              started_at: null,
              completed_at: null,
              detail_payload: {},
            },
          ],
          events: [
            {
              sequence: 1,
              stage_id: "model_compiler",
              label: "Model compiler",
              detail: "Executed generated contract candidates.",
              state: "complete",
              progress: null,
              occurred_at: null,
              source: "job",
              job_id: "job-generic",
              chunk_count: null,
              warning: null,
              evidence_refs: [],
              detail_payload: {},
            },
          ],
          contract: {
            contract_status: "metadata_only",
            verified: false,
            canonical_units: false,
            schema_type: "parent_item",
            repair_status: "unverified",
            validation_status: "unverified",
            validation_matched_units: 0,
            selected_strategy: null,
            rejection_reasons: [],
            detail_payload: {},
          },
          warning_groups: [],
          totals: {
            jobs: 1,
            chunks: 0,
            warnings: 0,
            graph_nodes: 0,
            graph_edges: 0,
            index_records: 0,
            graph_records: 0,
          },
          missing_sections: ["chunks"],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: /Model compiler complete/i })).toBeInTheDocument();
    expect(screen.queryByText("Contract proof boundary")).not.toBeInTheDocument();
  });
});

import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EvidenceInspector } from "../src/features/document-evidence/evidence-inspector";
import type { DocumentParseEvidence } from "../src/features/document-evidence/types";

const evidence: DocumentParseEvidence = {
  document: {
    id: "doc-1",
    filename: "synthetic.pdf",
    content_type: "application/pdf",
    status: "succeeded",
    page_count: 2,
    parser_mode: "mineru_strict",
  },
  source_artifacts: [
    {
      id: "artifact-1",
      kind: "parser",
      path: "artifacts/source_content_list.json",
      preview_available: true,
      preview_capped: true,
      hidden_count: 42,
    },
  ],
  parser_blocks: [
    {
      id: "block-1",
      page: 1,
      block_index: 0,
      block_type: "text",
      text_preview: "This paragraph starts on page one and",
      warning_ids: [],
    },
    {
      id: "block-2",
      page: 2,
      block_index: 1,
      block_type: "text",
      text_preview: "continues on page two before ending.",
      warning_ids: ["warning-1"],
    },
  ],
  normalization_decisions: [
    {
      id: "decision-1",
      decision_type: "page_stitch",
      title: "Page 1 -> 2 stitch",
      summary: "Ragstudio kept a semantic unit together across physical page boundaries.",
      input_block_ids: ["block-1", "block-2"],
      output_chunk_ids: ["chunk-1"],
      warning_ids: ["warning-1"],
      status: "recorded",
    },
  ],
  chunks: [
    {
      id: "chunk-1",
      text_preview: "This paragraph starts on page one and\n\ncontinues on page two before ending.",
      page_start: 1,
      page_end: 2,
      source_location: { page_start: 1, page_end: 2 },
      metadata: {},
      quality_status: "warning",
      warning_ids: ["warning-1"],
    },
  ],
  warnings: [
    {
      id: "warning-1",
      code: "missing_required_script",
      message: "Expected script was not detected on page 2.",
      severity: "warning",
      page: 2,
      affected_chunk_ids: ["chunk-1"],
    },
  ],
  proof: {
    mode: "export",
    source_commit: "abc1234",
    proof_packet_id: "ragstudio-oss-proof-v1",
    replay_command: "./scripts/proof.sh --fixtures static-fixtures",
    limitations: ["Synthetic fixture only."],
    redaction_summary: ["Redacted local absolute path."],
  },
  missing_sections: [],
};

describe("EvidenceInspector", () => {
  it("renders selected decision source blocks, chunk output, proof metadata, and diff labels", () => {
    render(<EvidenceInspector evidence={evidence} mode="public" />);

    expect(screen.getByRole("heading", { name: "Document parse evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Page 1 -> 2 stitch/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
    const sourceBlocks = screen.getByRole("region", { name: "Source blocks" });
    expect(sourceBlocks).toBeVisible();
    expect(within(sourceBlocks).getByText("This paragraph starts on page one and")).toBeVisible();
    expect(within(sourceBlocks).getByText("continues on page two before ending.")).toBeVisible();
    expect(screen.getByRole("region", { name: "Chunk output" })).toBeVisible();
    const normalizedUnit = screen.getByRole("region", { name: "Normalized unit" });
    expect(within(normalizedUnit).getByText("Added")).toBeVisible();
    expect(within(normalizedUnit).getAllByText("Unchanged")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Proof metadata" })).toBeVisible();
    expect(screen.getByText("abc1234")).toBeVisible();
    expect(screen.getByText("Redacted local absolute path.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reindex document" })).not.toBeInTheDocument();
  });

  it("supports rail selection and local actions", () => {
    const onReindex = vi.fn();
    const withSecondDecision: DocumentParseEvidence = {
      ...evidence,
      normalization_decisions: [
        ...evidence.normalization_decisions,
        {
          id: "decision-2",
          decision_type: "quality_warning",
          title: "Parser warning",
          summary: "Parser warning attached to chunk.",
          input_block_ids: ["block-2"],
          output_chunk_ids: ["chunk-1"],
          warning_ids: ["warning-1"],
          status: "warning",
        },
      ],
    };

    render(<EvidenceInspector evidence={withSecondDecision} mode="local" onReindex={onReindex} />);

    fireEvent.click(screen.getByRole("button", { name: /Parser warning/i }));

    expect(screen.getByRole("button", { name: /Parser warning/i })).toHaveAttribute(
      "aria-current",
      "true",
    );

    const reindexButton = screen.getByRole("button", { name: "Reindex document" });
    expect(reindexButton).toBeVisible();
    fireEvent.click(reindexButton);
    expect(onReindex).toHaveBeenCalledTimes(1);
  });

  it("shows missing evidence sections explicitly", () => {
    render(
      <EvidenceInspector
        evidence={{ ...evidence, parser_blocks: [], missing_sections: ["parserBlocks"] }}
      />,
    );

    expect(screen.getByText("Evidence unavailable")).toBeVisible();
    expect(screen.getByText("parserBlocks")).toBeVisible();
    expect(screen.getByText("Source blocks not recorded for this decision.")).toBeVisible();
  });

  it("keeps artifact previews bounded", () => {
    render(<EvidenceInspector evidence={evidence} mode="public" />);

    const metadata = screen.getByRole("region", { name: "Proof metadata" });
    expect(within(metadata).getByText("42 hidden characters")).toBeVisible();
  });
});

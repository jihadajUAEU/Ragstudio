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
      href: "/proof/artifacts/source_content_list.json",
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
    source_commit_href: "https://example.com/commit/abc1234",
    proof_packet_id: "ragstudio-oss-proof-v1",
    proof_packet_href: "https://example.com/proof/ragstudio-oss-proof-v1",
    replay_command: "./scripts/proof.sh --fixtures static-fixtures",
    replay_href: "https://example.com/proof/replay",
    limitations: ["Synthetic fixture only."],
    redaction_summary: ["Redacted local absolute path."],
  },
  missing_sections: [],
};

describe("EvidenceInspector", () => {
  it("shows full document chunk totals when evidence rows are a capped preview", () => {
    render(<EvidenceInspector evidence={{ ...evidence, totals: { chunks: 205 } }} mode="public" />);

    const summary = screen.getByRole("region", { name: "Evidence summary" });
    expect(within(summary).getByText("205")).toBeVisible();
    expect(within(summary).getByText("Total chunks")).toBeVisible();
  });

  it("renders selected decision source blocks, chunk output, proof metadata, and public links", () => {
    render(<EvidenceInspector evidence={evidence} mode="public" />);

    expect(screen.getByRole("heading", { name: "Document parse evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Page 1 -> 2 stitch/i })).toHaveAttribute("aria-pressed", "true");
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
    expect(screen.getByRole("link", { name: "Open raw artifact" })).toHaveAttribute(
      "href",
      "/proof/artifacts/source_content_list.json",
    );
    expect(screen.getByRole("link", { name: "View source commit" })).toHaveAttribute(
      "href",
      "https://example.com/commit/abc1234",
    );
    expect(screen.getByRole("link", { name: "Replay proof" })).toHaveAttribute(
      "href",
      "https://example.com/proof/replay",
    );
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

    expect(screen.getByRole("button", { name: /Parser warning/i })).toHaveAttribute("aria-pressed", "true");

    const reindexButton = screen.getByRole("button", { name: "Reindex document" });
    expect(reindexButton).toBeVisible();
    fireEvent.click(reindexButton);
    expect(onReindex).toHaveBeenCalledTimes(1);
  });

  it("paginates and searches evidence decisions", () => {
    const manyDecisions = Array.from({ length: 30 }, (_, index) => ({
      ...evidence.normalization_decisions[0],
      id: `decision-${index + 1}`,
      title: index === 29 ? "Needle parser warning" : `Decision ${index + 1}`,
      summary: index === 29 ? "Find this decision by search." : `Decision ${index + 1} summary.`,
    }));

    render(<EvidenceInspector evidence={{ ...evidence, normalization_decisions: manyDecisions }} />);

    const evidenceDecisions = screen.getByRole("complementary", { name: "Evidence decisions" });
    expect(within(evidenceDecisions).getByText("Showing 1-25 of 30")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Needle parser warning/i })).not.toBeInTheDocument();

    const nextButtons = within(evidenceDecisions).getAllByRole("button", { name: /Next/i });
    fireEvent.click(nextButtons.find((button) => !button.hasAttribute("disabled"))!);

    expect(within(evidenceDecisions).getByText("Showing 26-30 of 30")).toBeVisible();
    expect(screen.getByRole("button", { name: /Needle parser warning/i })).toBeVisible();

    fireEvent.change(screen.getByLabelText("Search evidence"), {
      target: { value: "needle" },
    });

    expect(within(evidenceDecisions).getByText("Showing 1-1 of 1")).toBeVisible();
    expect(screen.getByRole("button", { name: /Needle parser warning/i })).toBeVisible();
  });

  it("paginates and filters all warning rows separately from decisions", () => {
    const manyWarnings = Array.from({ length: 30 }, (_, index) => ({
      ...evidence.warnings[0],
      id: `warning-${index + 1}`,
      code: index === 29 ? "needle_warning" : "missing_required_script",
      message: index === 29 ? "Needle warning row." : `Warning row ${index + 1}.`,
      affected_chunk_ids: [`chunk-${index + 1}`],
    }));

    render(<EvidenceInspector evidence={{ ...evidence, warnings: manyWarnings }} />);

    const allWarnings = screen.getByRole("region", { name: "All warning rows" });
    expect(within(allWarnings).getByText("Showing 1-25 of 30")).toBeVisible();
    expect(within(allWarnings).queryByText("needle_warning")).not.toBeInTheDocument();

    const nextButtons = within(allWarnings).getAllByRole("button", { name: /Next/i });
    fireEvent.click(nextButtons.find((button) => !button.hasAttribute("disabled"))!);

    expect(within(allWarnings).getByText("Showing 26-30 of 30")).toBeVisible();
    expect(within(allWarnings).getByText("needle_warning")).toBeVisible();

    fireEvent.change(within(allWarnings).getByLabelText("Search all warnings"), {
      target: { value: "needle" },
    });

    expect(within(allWarnings).getByText("Showing 1-1 of 1")).toBeVisible();
    expect(within(allWarnings).getByText("Needle warning row.")).toBeVisible();
  });

  it("keeps preview decision tab counts separate from full counted warning rows", () => {
    const warningRows = [
      ...Array.from({ length: 3 }, (_, index) => ({
        ...evidence.warnings[0],
        id: `counted-warning-${index + 1}`,
        code: "missing_required_script",
        message: `Counted warning row ${index + 1}.`,
        severity: "warning",
        decision_id: "decision-1",
        affected_chunk_ids: ["chunk-1"],
      })),
      {
        ...evidence.warnings[0],
        id: "audit-warning-1",
        code: "recovered_text_from_disallowed_block",
        message: "Audit recovery row.",
        severity: "info",
        suppressed_from_counts: true,
        decision_id: "decision-1",
        affected_chunk_ids: ["chunk-1"],
      },
    ];

    render(<EvidenceInspector evidence={{ ...evidence, warnings: warningRows }} />);

    expect(screen.getByRole("button", { name: "Preview counted decisions 1" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview audit decisions 1" })).toBeVisible();

    const allWarnings = screen.getByRole("region", { name: "All warning rows" });
    fireEvent.change(within(allWarnings).getByLabelText("Warning row scope"), {
      target: { value: "counted" },
    });

    expect(within(allWarnings).getByText("Showing 1-3 of 3")).toBeVisible();
    expect(within(allWarnings).queryByText("Audit recovery row.")).not.toBeInTheDocument();
  });

  it("groups repeated selected decision warnings in the summary", () => {
    const repeatedWarnings = [
      {
        ...evidence.warnings[0],
        id: "warning-repeat-1",
        code: "reference_unit_missing_expected_script",
        message: "Reference unit is expected to contain Arabic script.",
        severity: "warn",
        decision_id: "decision-1",
      },
      {
        ...evidence.warnings[0],
        id: "warning-repeat-2",
        code: "reference_unit_missing_expected_script",
        message: "Reference unit is expected to contain Arabic script.",
        severity: "warning",
        decision_id: "decision-1",
      },
      {
        ...evidence.warnings[0],
        id: "warning-repeat-3",
        code: "reference_unit_missing_expected_script",
        message: "Reference-bearing chunk is expected to contain Arabic script.",
        severity: "warning",
        decision_id: "decision-1",
      },
    ];

    render(
      <EvidenceInspector
        evidence={{
          ...evidence,
          normalization_decisions: [
            {
              ...evidence.normalization_decisions[0],
              warning_ids: repeatedWarnings.map((warning) => warning.id),
            },
          ],
          warnings: repeatedWarnings,
        }}
      />,
    );

    expect(screen.getByText("3 rows")).toBeVisible();
    const summary = screen.getByRole("region", {
      name: /Page 1 -> 2 stitch evidence detail/i,
    });
    expect(within(summary).getByText("3 rows")).toBeVisible();
  });

  it("supports keyboard navigation across rail decisions", () => {
    const withDecisions: DocumentParseEvidence = {
      ...evidence,
      normalization_decisions: [
        evidence.normalization_decisions[0],
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
        {
          id: "decision-3",
          decision_type: "quality_gate",
          title: "Quality gate",
          summary: "Quality gate blocked a chunk.",
          input_block_ids: ["block-1"],
          output_chunk_ids: ["chunk-1"],
          warning_ids: [],
          status: "blocked",
        },
      ],
    };

    render(<EvidenceInspector evidence={withDecisions} />);

    const first = screen.getByRole("button", { name: /Page 1 -> 2 stitch/i });
    fireEvent.keyDown(first, { key: "ArrowDown" });

    expect(screen.getByRole("button", { name: /Parser warning/i })).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(screen.getByRole("button", { name: /Parser warning/i }), { key: "End" });
    expect(screen.getByRole("button", { name: /Quality gate/i })).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(screen.getByRole("button", { name: /Quality gate/i }), { key: "Home" });
    expect(first).toHaveAttribute("aria-pressed", "true");
  });

  it("renders explicit removed, blocked, and capped diff rows", () => {
    render(
      <EvidenceInspector
        evidence={{
          ...evidence,
          normalization_decisions: [
            {
              ...evidence.normalization_decisions[0],
              diff_rows: [
                {
                  id: "diff-removed",
                  kind: "removed",
                  text: "Page footer removed from chunk output.",
                },
                {
                  id: "diff-blocked",
                  kind: "blocked",
                  text: "Low confidence OCR block blocked by quality gate.",
                },
                {
                  id: "diff-capped",
                  kind: "added",
                  text: "Large table preview",
                  capped: true,
                  hidden_count: 120,
                },
              ],
            },
          ],
        }}
      />,
    );

    const normalizedUnit = screen.getByRole("region", { name: "Normalized unit" });
    expect(within(normalizedUnit).getByText("Removed")).toBeVisible();
    expect(within(normalizedUnit).getByText("Blocked")).toBeVisible();
    expect(within(normalizedUnit).getByText("Capped preview - 120 hidden characters")).toBeVisible();
  });

  it("highlights accepted recovered text in source blocks", () => {
    render(
      <EvidenceInspector
        evidence={{
          ...evidence,
          parser_blocks: [
            {
              id: "block-recovered",
              page: 7,
              block_index: 3,
              block_type: "header",
              text_preview: "Recovered Arabic header text kept with provenance.",
              warning_ids: ["warning-recovered"],
            },
          ],
          normalization_decisions: [
            {
              id: "decision-recovered",
              decision_type: "quality_warning",
              title: "Recovered parser text",
              summary: "Recovered text was accepted as audit evidence.",
              input_block_ids: ["block-recovered"],
              output_chunk_ids: [],
              warning_ids: ["warning-recovered"],
              status: "recorded",
            },
          ],
          chunks: [],
          warnings: [
            {
              id: "warning-recovered",
              code: "recovered_text_from_disallowed_block",
              message: "Used parser-provided recovered text for a disallowed block type.",
              severity: "info",
              page: 7,
              block_id: "block-recovered",
              block_type: "header",
              quality_gate_action: "accepted_recovery",
              suppressed_from_counts: true,
              affected_chunk_ids: [],
            },
          ],
        }}
      />,
    );

    const sourceBlocks = screen.getByRole("region", { name: "Source blocks" });
    expect(within(sourceBlocks).getByText("Recovered text")).toBeVisible();
    expect(within(sourceBlocks).getByText("Accepted recovery from Header")).toBeVisible();
    expect(within(sourceBlocks).getByText("Recovered Arabic header text kept with provenance.")).toBeVisible();
    expect(
      screen.getByText("Accepted recovery from Header. Audit evidence only; not a counted parser warning."),
    ).toBeVisible();
  });

  it("preserves decision-defined ordering for source blocks and chunks", () => {
    render(
      <EvidenceInspector
        evidence={{
          ...evidence,
          parser_blocks: [...evidence.parser_blocks].reverse(),
          chunks: [
            {
              id: "chunk-2",
              text_preview: "Second chunk.",
              page_start: 3,
              page_end: 3,
              source_location: { page: 3 },
              metadata: {},
              quality_status: "passed",
              warning_ids: [],
            },
            ...evidence.chunks,
          ],
          normalization_decisions: [
            {
              ...evidence.normalization_decisions[0],
              input_block_ids: ["block-1", "block-2"],
              output_chunk_ids: ["chunk-1", "chunk-2"],
            },
          ],
        }}
      />,
    );

    const sourceBlocks = screen.getByRole("region", { name: "Source blocks" });
    const blockArticles = within(sourceBlocks).getAllByRole("article");
    expect(within(blockArticles[0]).getByText("This paragraph starts on page one and")).toBeVisible();
    expect(within(blockArticles[1]).getByText("continues on page two before ending.")).toBeVisible();

    const chunkOutput = screen.getByRole("region", { name: "Chunk output" });
    const chunkArticles = within(chunkOutput).getAllByRole("article");
    expect(within(chunkArticles[0]).getByText(/chunk-1/i)).toBeVisible();
    expect(within(chunkArticles[1]).getByText(/chunk-2/i)).toBeVisible();
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

  it("hides unsafe public proof links", () => {
    render(
      <EvidenceInspector
        evidence={{
          ...evidence,
          source_artifacts: [
            {
              ...evidence.source_artifacts[0],
              href: "//evil.example/proof",
            },
          ],
          proof: {
            ...evidence.proof,
            source_commit_href: "data:text/html,unsafe",
            replay_href: "/proof/replay",
          },
        }}
        mode="public"
      />,
    );

    expect(screen.queryByRole("link", { name: "Open raw artifact" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View source commit" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Replay proof" })).toHaveAttribute("href", "/proof/replay");
    expect(screen.getAllByText("Unsafe link hidden.").length).toBeGreaterThanOrEqual(2);
  });
});

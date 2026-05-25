import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EvidenceViewer,
  type NormalizedEvidence,
} from "../src/features/evidence/evidence-viewer";

const evidence: NormalizedEvidence = {
  id: "source-7",
  kind: "query-source",
  documentId: "doc-1",
  documentName: "source.txt",
  runtimeProfileId: "default",
  text: "Evidence text",
  sourceLocation: { page: 1, reference: "19:13" },
  metadata: {},
  architecture: {
    domain: {
      domain: "quran_tafseer",
      materializationHint: "graph",
      qualityPolicy: "allow",
      reasons: [
        "domain_profile:reference_heavy",
        "verified_reference_contract",
      ],
    },
    layout: {
      layoutGroupId: "layout-1",
      layoutRole: "paragraph",
      readingOrder: "12",
      reasons: ["bbox_overlap", "layout_group"],
    },
    context: {
      parentChunkId: "parent-1",
      previousChunkId: "prev-1",
      nextChunkId: "next-1",
      reasons: ["heading_path_context", "linked_context"],
    },
    assembly: {
      groundingStatus: "grounded",
      evidenceIds: ["metadata:source-7"],
      droppedReasons: [],
    },
  },
  raw: { id: "source-7" },
  routeLinks: {},
};

describe("EvidenceViewer", () => {
  it("renders three-pillar reason chips when they are provided", () => {
    render(<EvidenceViewer evidence={evidence} open onClose={vi.fn()} />);

    fireEvent.click(screen.getByText("Domain and materialization", { selector: "summary" }));
    expect(screen.getByText("Contract reasons")).toBeVisible();
    expect(screen.getByText("verified_reference_contract")).toBeVisible();

    fireEvent.click(screen.getByText("Layout chain", { selector: "summary" }));
    expect(screen.getByText("Layout reasons")).toBeVisible();
    expect(screen.getByText("bbox_overlap")).toBeVisible();

    fireEvent.click(screen.getByText("Context chain", { selector: "summary" }));
    expect(screen.getByText("Context reasons")).toBeVisible();
    expect(screen.getByText("heading_path_context")).toBeVisible();
    expect(screen.getByText("linked_context")).toBeVisible();
  });
});

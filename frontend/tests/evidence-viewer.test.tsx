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
  contextWarnings: [
    "runtime_bridge_missing",
    "canonical hydration: missing",
    "layout context: runtime_minimal",
  ],
  architecture: {
    domain: {
      domain: "quran_tafseer",
      materializationHint: "graph",
      qualityPolicy: "allow",
    },
    layout: {
      layoutGroupId: "layout-1",
      layoutRole: "paragraph",
      readingOrder: "12",
    },
    context: {
      parentChunkId: "parent-1",
      previousChunkId: "prev-1",
      nextChunkId: "next-1",
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
  it("renders layout and context loss warnings when native evidence is not hydrated", () => {
    render(<EvidenceViewer evidence={evidence} open onClose={vi.fn()} />);

    fireEvent.click(screen.getByText("Context chain", { selector: "summary" }));
    expect(screen.getByText("Layout/context loss")).toBeVisible();
    expect(screen.getByText("runtime_bridge_missing")).toBeVisible();
    expect(screen.getByText("canonical hydration: missing")).toBeVisible();
    expect(screen.getByText("layout context: runtime_minimal")).toBeVisible();
  });
});

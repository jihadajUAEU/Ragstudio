import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DomainMetadataPanel } from "../src/features/domain-metadata/domain-metadata-panel";

const mocks = vi.hoisted(() => ({
  suggestDomainMetadata: vi.fn(),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    suggestDomainMetadata: mocks.suggestDomainMetadata,
  },
}));

describe("DomainMetadataPanel", () => {
  it("renders parser modes and applies a selected domain profile", async () => {
    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[
          {
            id: "hadith",
            name: "Hadith",
            description: "Hadith collection",
            metadata: {
              domain: "hadith",
              document_type: "collection",
              language: "mixed",
              tags: ["hadith"],
              metadata_sources: ["profile"],
            },
          },
        ]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Parser"), {
      target: { value: "mineru_with_fallback" },
    });
    fireEvent.change(screen.getByLabelText("Domain profile"), {
      target: { value: "hadith" },
    });

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        parser_mode: "mineru_with_fallback",
      }),
    );
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({
          domain: "hadith",
          document_type: "collection",
        }),
      }),
    );
  });

  it("auto-suggests metadata and edits custom JSON", async () => {
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "admin_document",
        custom_json: { department: "research" },
      },
    });
    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={onChange}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByDisplayValue(/department/)).toBeVisible();
    expect(mocks.suggestDomainMetadata).toHaveBeenCalledWith({
      filename: "policy.pdf",
      content_type: "application/pdf",
      sample_text: "",
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({ domain: "policy" }),
      }),
    );

    fireEvent.change(screen.getByLabelText("Custom JSON"), {
      target: { value: "{\"owner\":\"library\"}" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({
          custom_json: { owner: "library" },
        }),
      }),
    );
  });
});

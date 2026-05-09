import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const autosuggestEvidence = {
  confidence: 0.91,
  evidence_pages: [1, 2, 10, 20],
  rationale: "The sampled pages show policy headings.",
  warnings: [],
};

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
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "admin_document",
        custom_json: { department: "research" },
      },
      ...autosuggestEvidence,
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
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByDisplayValue(/department/)).toBeVisible();
    expect(mocks.suggestDomainMetadata).toHaveBeenCalledWith({
      file,
      profile_id: null,
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

  it("passes the selected profile to auto-suggest", async () => {
    const file = new File(["pdf"], "hadith.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: { domain: "hadith", document_type: "collection" },
      ...autosuggestEvidence,
    });
    render(
      <DomainMetadataPanel
        profiles={[
          {
            id: "hadith",
            name: "Hadith",
            description: "Hadith collection",
            metadata: { domain: "hadith", document_type: "collection" },
          },
        ]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document" },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "hadith.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.change(screen.getByLabelText("Domain profile"), {
      target: { value: "hadith" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    await waitFor(() => {
      expect(mocks.suggestDomainMetadata).toHaveBeenCalledWith(
        expect.objectContaining({ profile_id: "hadith" }),
      );
    });
  });

  it("keeps custom JSON synchronized with profile selection and reports validity", () => {
    const onChange = vi.fn();
    const onValidityChange = vi.fn();
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
              custom_json: { collection_slug: "bukhari" },
            },
          },
        ]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", custom_json: {} },
        }}
        onChange={onChange}
        onValidityChange={onValidityChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Domain profile"), {
      target: { value: "hadith" },
    });

    expect(screen.getByDisplayValue(/collection_slug/)).toBeVisible();

    fireEvent.change(screen.getByLabelText("Custom JSON"), {
      target: { value: "{bad-json" },
    });

    expect(screen.getByText("Custom JSON must be valid JSON.")).toBeVisible();
    expect(onValidityChange).toHaveBeenCalledWith(false);
  });

  it("shows all autosuggested metadata changes and marks changed fields", async () => {
    const file = new File(["pdf"], "tafseer_ibn_kathir.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "tafseer",
        document_type: "book",
        language: "mixed",
        collection: "Tafseer Ibn Kathir",
        tags: ["quran", "tafseer"],
        reference_pattern: "Surah N, Ayah N",
        metadata_sources: ["heuristic", "profile"],
        custom_json: {
          audience: "research",
          citation_style: "surah_ayah",
        },
      },
      ...autosuggestEvidence,
    });

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "mineru_strict",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            language: "",
            collection: "",
            tags: ["quran"],
            metadata_sources: ["user"],
            custom_json: { audience: "general" },
          },
        }}
        onChange={vi.fn()}
        suggestContext={{
          filename: "tafseer_ibn_kathir.pdf",
          content_type: "application/pdf",
          file,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    const expectVisibleText = (text: string) => {
      expect(screen.getAllByText(text)[0]).toBeVisible();
    };

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    expect(screen.getByText("8 fields changed")).toBeVisible();
    expectVisibleText("Domain");
    expect(screen.getByText("generic -> tafseer")).toBeVisible();
    expectVisibleText("Document type");
    expect(screen.getByText("document -> book")).toBeVisible();
    expectVisibleText("Language");
    expect(screen.getByText("empty -> mixed")).toBeVisible();
    expectVisibleText("Collection");
    expect(screen.getByText("empty -> Tafseer Ibn Kathir")).toBeVisible();
    expectVisibleText("Tags");
    expect(screen.getByText("added tafseer")).toBeVisible();
    expectVisibleText("Reference pattern");
    expect(screen.getByText("empty -> Surah N, Ayah N")).toBeVisible();
    expectVisibleText("Metadata sources");
    expect(screen.getByText("added heuristic, profile; removed user")).toBeVisible();
    expectVisibleText("Custom JSON");
    expect(screen.getByText("added citation_style; changed audience")).toBeVisible();
    expect(screen.getByText("Confidence 91% from pages 1, 2, 10, 20")).toBeVisible();
    expect(screen.getByText("The sampled pages show policy headings.")).toBeVisible();

    expect(screen.getByLabelText("Domain").closest("[data-autosuggest-changed]")).toHaveAttribute(
      "data-autosuggest-changed",
      "true",
    );
    expect(
      screen.getByLabelText("Document type").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
    expect(
      screen.getByLabelText("Custom JSON").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
  });

  it("clears a changed field from the autosuggest review after manual edit", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "admin_document",
        tags: [],
      },
      ...autosuggestEvidence,
    });

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("2 fields changed")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Domain"), {
      target: { value: "policy-final" },
    });

    expect(screen.queryByText("generic -> policy")).not.toBeInTheDocument();
    expect(screen.getByText("1 field changed")).toBeVisible();
    expect(screen.getByLabelText("Domain").closest("[data-autosuggest-changed]")).toBeNull();
    expect(
      screen.getByLabelText("Document type").closest("[data-autosuggest-changed]"),
    ).toHaveAttribute("data-autosuggest-changed", "true");
  });

  it("keeps previous metadata and review when autosuggest fails", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata
      .mockResolvedValueOnce({
        domain_metadata: {
          domain: "policy",
          document_type: "admin_document",
          custom_json: { department: "research" },
        },
        ...autosuggestEvidence,
      })
      .mockRejectedValueOnce(new Error("suggestion failed"));

    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            custom_json: { department: "general" },
          },
        }}
        onChange={onChange}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();
    expect(screen.getByDisplayValue(/research/)).toBeVisible();

    onChange.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Metadata suggestion failed.")).toBeVisible();
    expect(screen.getByText("generic -> policy")).toBeVisible();
    expect(screen.getByDisplayValue(/research/)).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows and hides a sample custom JSON object", () => {
    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", custom_json: {} },
        }}
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /view sample/i }));

    expect(screen.getByText("Sample custom JSON")).toBeVisible();
    expect(screen.getByText(/source_system/)).toBeVisible();
    expect(screen.getByText(/citation_style/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /hide sample/i }));

    expect(screen.queryByText("Sample custom JSON")).not.toBeInTheDocument();
  });
});

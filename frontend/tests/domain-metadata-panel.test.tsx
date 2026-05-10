import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DomainMetadataPanel } from "../src/features/domain-metadata/domain-metadata-panel";

const mocks = vi.hoisted(() => ({
  getReferenceJsonExample: vi.fn(),
  suggestDomainMetadata: vi.fn(),
}));

vi.mock("../src/api/client", () => ({
  apiClient: {
    getReferenceJsonExample: mocks.getReferenceJsonExample,
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
  beforeEach(() => {
    mocks.getReferenceJsonExample.mockReset();
    mocks.suggestDomainMetadata.mockReset();
  });

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

  it("rejects an autosuggested scalar field and restores the prior value", async () => {
    const file = new File(["memo"], "memo.txt", { type: "text/plain" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: { domain: "policy", document_type: "memo", tags: [] },
      confidence: 0.9,
      evidence_pages: [1],
      rationale: "Detected memo heading.",
      warnings: [],
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
        suggestContext={{ filename: "memo.txt", content_type: "text/plain", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reject Domain" }));

    expect(onChange).toHaveBeenLastCalledWith({
      parser_mode: "local_fallback",
      domain_metadata: { domain: "generic", document_type: "memo", tags: [] },
    });
    expect(screen.queryByText("generic -> policy")).not.toBeInTheDocument();
    expect(screen.getByText("1 field changed")).toBeVisible();
  });

  it("accepts an autosuggested field and keeps the suggested value", async () => {
    const file = new File(["memo"], "memo.txt", { type: "text/plain" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: { domain: "policy", document_type: "memo", tags: [] },
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
        suggestContext={{ filename: "memo.txt", content_type: "text/plain", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    onChange.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Accept Domain" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByText("generic -> policy")).not.toBeInTheDocument();
    expect(screen.getByText("1 field changed")).toBeVisible();
  });

  it("rejects autosuggested tags and metadata sources", async () => {
    const file = new File(["pdf"], "tafseer.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "tafseer",
        document_type: "document",
        tags: ["quran", "tafseer"],
        metadata_sources: ["heuristic", "profile"],
      },
      ...autosuggestEvidence,
    });
    const onChange = vi.fn();

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            tags: ["quran"],
            metadata_sources: ["user"],
          },
        }}
        onChange={onChange}
        suggestContext={{ filename: "tafseer.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest updated metadata")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reject Tags" }));

    expect(onChange).toHaveBeenLastCalledWith({
      parser_mode: "local_fallback",
      domain_metadata: {
        domain: "tafseer",
        document_type: "document",
        tags: ["quran"],
        metadata_sources: ["heuristic", "profile"],
      },
    });
    expect(screen.queryByText("added tafseer")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reject Metadata sources" }));

    expect(onChange).toHaveBeenLastCalledWith({
      parser_mode: "local_fallback",
      domain_metadata: {
        domain: "tafseer",
        document_type: "document",
        tags: ["quran"],
        metadata_sources: ["user"],
      },
    });
    expect(screen.queryByText("added heuristic, profile; removed user")).not.toBeInTheDocument();
  });

  it("rejects autosuggested custom JSON and restores the textarea validity", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "document",
        custom_json: { department: "research" },
      },
      ...autosuggestEvidence,
    });
    const onChange = vi.fn();
    const onValidityChange = vi.fn();

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
        onValidityChange={onValidityChange}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    const customJsonInput = await screen.findByDisplayValue(/research/);
    fireEvent.change(customJsonInput, {
      target: { value: "{bad-json" },
    });
    expect(screen.getByText("Custom JSON must be valid JSON.")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Reject Custom JSON" }));

    expect(screen.getByDisplayValue(/general/)).toBeVisible();
    expect(screen.queryByText("Custom JSON must be valid JSON.")).not.toBeInTheDocument();
    expect(onValidityChange).toHaveBeenLastCalledWith(true);
    expect(onChange).toHaveBeenLastCalledWith({
      parser_mode: "local_fallback",
      domain_metadata: {
        domain: "policy",
        document_type: "document",
        custom_json: { department: "general" },
      },
    });
  });

  it("preserves inserted reference schema when another autosuggested field is rejected", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "policy",
        document_type: "document",
        custom_json: { department: "research" },
      },
      ...autosuggestEvidence,
    });
    mocks.getReferenceJsonExample.mockResolvedValueOnce({
      custom_json: {
        reference_schema: {
          type: "chapter_verse",
        },
      },
    });
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

    fireEvent.click(screen.getByRole("button", { name: /Auto-suggest/i }));

    expect(await screen.findByDisplayValue(/research/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /insert reference schema/i }));
    await waitFor(() => {
      expect(screen.getByLabelText("Custom JSON")).toHaveDisplayValue(/chapter_verse/);
    });

    fireEvent.click(screen.getByRole("button", { name: "Reject Domain" }));

    expect(onChange).toHaveBeenLastCalledWith({
      parser_mode: "local_fallback",
      domain_metadata: {
        domain: "generic",
        document_type: "document",
        custom_json: {
          department: "research",
          reference_schema: {
            type: "chapter_verse",
          },
        },
      },
    });
  });

  it("passes the selected profile to auto-suggest and applies profile-refined metadata", async () => {
    const file = new File(["pdf"], "hadith.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "hadith",
        document_type: "collection",
        metadata_sources: ["profile", "ai"],
        custom_json: {
          reference_schema: {
            type: "book_hadith",
          },
          chunking: {
            unit: "hadith",
          },
        },
      },
      ...autosuggestEvidence,
    });
    const onChange = vi.fn();

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
        onChange={onChange}
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
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({
          domain: "hadith",
          document_type: "collection",
          metadata_sources: ["profile", "ai"],
          custom_json: {
            reference_schema: {
              type: "book_hadith",
            },
            chunking: {
              unit: "hadith",
            },
          },
        }),
      }),
    );
    expect(screen.getByDisplayValue(/book_hadith/)).toBeVisible();
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
        authority: "Classical tafsir",
        source: "Sampled pages",
        collection: "Tafseer Ibn Kathir",
        citation_style: "surah_ayah",
        expected_structure: "surah_ayah_sections",
        tags: ["quran", "tafseer"],
        reference_pattern: "Surah N, Ayah N",
        script: "arabic_latin",
        content_role: "tafseer",
        metadata_sources: ["heuristic", "profile"],
        custom_json: {
          audience: "research",
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
            authority: "",
            source: "",
            collection: "",
            citation_style: "",
            expected_structure: "",
            tags: ["quran"],
            reference_pattern: "",
            script: "",
            content_role: "",
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
    expect(screen.getByText("14 fields changed")).toBeVisible();
    expectVisibleText("Domain");
    expect(screen.getByText("generic -> tafseer")).toBeVisible();
    expectVisibleText("Document type");
    expect(screen.getByText("document -> book")).toBeVisible();
    expectVisibleText("Language");
    expect(screen.getByText("empty -> mixed")).toBeVisible();
    expectVisibleText("Authority");
    expect(screen.getByText("empty -> Classical tafsir")).toBeVisible();
    expectVisibleText("Source");
    expect(screen.getByText("empty -> Sampled pages")).toBeVisible();
    expectVisibleText("Collection");
    expect(screen.getByText("empty -> Tafseer Ibn Kathir")).toBeVisible();
    expectVisibleText("Citation style");
    expect(screen.getByText("empty -> surah_ayah")).toBeVisible();
    expectVisibleText("Expected structure");
    expect(screen.getByText("empty -> surah_ayah_sections")).toBeVisible();
    expectVisibleText("Tags");
    expect(screen.getByText("added tafseer")).toBeVisible();
    expectVisibleText("Reference pattern");
    expect(screen.getByText("empty -> Surah N, Ayah N")).toBeVisible();
    expectVisibleText("Script");
    expect(screen.getByText("empty -> arabic_latin")).toBeVisible();
    expectVisibleText("Content role");
    expect(screen.getByText("empty -> tafseer")).toBeVisible();
    expectVisibleText("Metadata sources");
    expect(screen.getByText("added heuristic, profile; removed user")).toBeVisible();
    expectVisibleText("Custom JSON");
    expect(screen.getByText("1 custom JSON change")).toBeVisible();
    expect(screen.getByText('audience changed to "research"')).toBeVisible();
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

  it("shows autosuggest evidence even when metadata is unchanged", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "generic",
        document_type: "document",
        tags: [],
      },
      confidence: 0.42,
      evidence_pages: [1],
      rationale: "The sampled page matches the current metadata.",
      warnings: ["Only one readable page was sampled."],
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

    expect(await screen.findByText("Auto-suggest reviewed metadata")).toBeVisible();
    expect(screen.getByText("0 fields changed")).toBeVisible();
    expect(screen.getByText("Confidence 42% from pages 1")).toBeVisible();
    expect(screen.getByText("The sampled page matches the current metadata.")).toBeVisible();
    expect(screen.getByText("Only one readable page was sampled.")).toBeVisible();
  });

  it("clears autosuggest evidence when a domain profile is selected", async () => {
    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "generic",
        document_type: "document",
        tags: [],
      },
      confidence: 0.42,
      evidence_pages: [1],
      rationale: "The sampled page matches the current metadata.",
      warnings: ["Only one readable page was sampled."],
    });

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
              tags: ["hadith"],
            },
          },
        ]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: { domain: "generic", document_type: "document", tags: [] },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "policy.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Auto-suggest reviewed metadata")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Domain profile"), {
      target: { value: "hadith" },
    });

    await waitFor(() => {
      expect(screen.queryByText("Auto-suggest reviewed metadata")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("The sampled page matches the current metadata.")).not.toBeInTheDocument();
    expect(screen.queryByText("Only one readable page was sampled.")).not.toBeInTheDocument();
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

  it("inserts the reference schema helper into custom JSON", async () => {
    mocks.getReferenceJsonExample.mockResolvedValueOnce({
      custom_json: {
        reference_schema: {
          type: "chapter_verse",
          fields: {
            chapter: "chapter_number",
            verse: "verse_number",
          },
        },
        chunking: {
          unit: "verse",
          include_neighbors: 1,
        },
        retrieval: {
          exact_reference_top1: true,
        },
      },
    });
    const onChange = vi.fn();
    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "local_fallback",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            custom_json: { source_system: "library_upload" },
          },
        }}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /insert reference schema/i }));

    const customJsonInput = screen.getByLabelText("Custom JSON") as HTMLTextAreaElement;
    await waitFor(() => {
      expect(customJsonInput.value).toContain("reference_schema");
    });
    expect(customJsonInput.value).toContain("chunking");
    expect(customJsonInput.value).toContain("retrieval");
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        domain_metadata: expect.objectContaining({
          custom_json: expect.objectContaining({
            source_system: "library_upload",
            reference_schema: expect.any(Object),
            chunking: expect.any(Object),
            retrieval: expect.any(Object),
          }),
        }),
      }),
    );
  });

  it("shows nested autosuggest custom JSON changes", async () => {
    const file = new File(["pdf"], "quran.pdf", { type: "application/pdf" });
    mocks.suggestDomainMetadata.mockResolvedValueOnce({
      domain_metadata: {
        domain: "religion",
        document_type: "religious_text",
        custom_json: {
          reference_schema: {
            type: "surah_ayah",
          },
          chunking: {
            unit: "verse",
          },
          retrieval: {
            exact_reference_top1: true,
          },
        },
      },
      confidence: 0.95,
      evidence_pages: [1, 2, 507, 1012],
      rationale: "The sampled pages show Quran references.",
      warnings: [],
    });

    render(
      <DomainMetadataPanel
        profiles={[]}
        value={{
          parser_mode: "mineru_strict",
          domain_metadata: {
            domain: "generic",
            document_type: "document",
            custom_json: {
              chunking: {
                unit: "section",
              },
            },
          },
        }}
        onChange={vi.fn()}
        suggestContext={{ filename: "quran.pdf", content_type: "application/pdf", file }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    expect(await screen.findByText("Confidence 95% from pages 1, 2, 507, 1012")).toBeVisible();
    expect(screen.getByText('reference_schema.type added as "surah_ayah"')).toBeVisible();
    expect(screen.getByText('chunking.unit changed to "verse"')).toBeVisible();
    expect(screen.getByText("retrieval.exact_reference_top1 added as true")).toBeVisible();
  });
});

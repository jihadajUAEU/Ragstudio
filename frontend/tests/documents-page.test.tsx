import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPage } from "../src/features/documents/documents-page";
import { apiClient } from "../src/api/client";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    documents: vi.fn(),
    jobs: vi.fn(),
    domainProfiles: vi.fn(),
    suggestDomainMetadata: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    createDocumentReindexJob: vi.fn(),
  },
}));

function renderDocumentsPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={queryClient}>
      <DocumentsPage />
    </QueryClientProvider>,
  );
}

describe("DocumentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.documents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.jobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.suggestDomainMetadata).mockResolvedValue({
      domain_metadata: { domain: "policy", document_type: "admin_document" },
      confidence: 0.91,
      evidence_pages: [1, 2, 10, 20],
      rationale: "The sampled pages show policy headings.",
      warnings: [],
    });
    vi.mocked(apiClient.deleteDocument).mockResolvedValue(undefined);
    vi.mocked(apiClient.uploadDocument).mockResolvedValue({
      id: "doc-upload",
      filename: "sample.pdf",
      content_type: "application/pdf",
      status: "running",
      sha256: "sha-upload",
    });
    vi.mocked(apiClient.createDocumentReindexJob).mockResolvedValue({
      document_id: "doc-1",
      job_id: "job-1",
      status: "ready",
    });
  });

  it("keeps the file upload control visible and enables upload after file selection", () => {
    renderDocumentsPage();

    const uploadInput = screen.getByLabelText(/upload file/i);
    expect(uploadInput).toBeVisible();

    const uploadButton = screen.getByRole("button", { name: /^upload$/i });
    expect(uploadButton).toBeDisabled();

    fireEvent.change(uploadInput, {
      target: {
        files: [new File(["pdf"], "sample.pdf", { type: "application/pdf" })],
      },
    });

    expect(uploadButton).toBeEnabled();
  });

  it("uploads with strict MinerU as the default parser", async () => {
    renderDocumentsPage();

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/upload file/i), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      expect(apiClient.uploadDocument).toHaveBeenCalled();
    });
    expect(vi.mocked(apiClient.uploadDocument).mock.calls[0][0]).toEqual({
      file,
      options: {
        parser_mode: "mineru_strict",
        domain_metadata: { domain: "generic", document_type: "document", tags: [] },
      },
    });
  });

  it("uses MinerU strict as the only parser mode", async () => {
    renderDocumentsPage();

    expect(screen.queryByText("Local fallback")).not.toBeInTheDocument();
    expect(screen.queryByText("MinerU with fallback")).not.toBeInTheDocument();
    expect(await screen.findByText("MinerU strict")).toBeVisible();
  });

  it("passes the selected upload file to metadata autosuggest", async () => {
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({
      items: [
        {
          id: "profile-1",
          name: "Policy",
          description: "Policy metadata",
          metadata: { domain: "policy", document_type: "admin_document" },
        },
      ],
      total: 1,
    });
    renderDocumentsPage();

    const file = new File(["pdf"], "policy.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/upload file/i), {
      target: { files: [file] },
    });
    await screen.findByRole("option", { name: "Policy" });
    fireEvent.change(screen.getByLabelText("Domain profile"), {
      target: { value: "profile-1" },
    });

    fireEvent.click(screen.getByRole("button", { name: /auto-suggest/i }));

    await waitFor(() => {
      expect(apiClient.suggestDomainMetadata).toHaveBeenCalledWith({
        file,
        profile_id: "profile-1",
      });
    });
  });

  it("places auto-suggest after the domain profile selector", async () => {
    renderDocumentsPage();

    fireEvent.change(screen.getByLabelText(/upload file/i), {
      target: {
        files: [new File(["pdf"], "sample.pdf", { type: "application/pdf" })],
      },
    });

    const domainProfile = await screen.findByLabelText("Domain profile");
    const autoSuggest = screen.getByRole("button", { name: /auto-suggest/i });

    expect(
      domainProfile.compareDocumentPosition(autoSuggest) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("places the upload action after the custom JSON editor", () => {
    renderDocumentsPage();

    const customJson = screen.getByLabelText("Custom JSON");
    const uploadButton = screen.getByRole("button", { name: /^upload$/i });

    expect(
      customJson.compareDocumentPosition(uploadButton) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("confirms and deletes an uploaded document", async () => {
    vi.mocked(apiClient.documents)
      .mockResolvedValueOnce({
        items: [
          {
            id: "doc-1",
            filename: "delete-me.pdf",
            content_type: "application/pdf",
            status: "succeeded",
            sha256: "sha-1",
          },
        ],
        total: 1,
      })
      .mockResolvedValue({ items: [], total: 0 });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderDocumentsPage();

    fireEvent.click(await screen.findByRole("button", { name: /delete delete-me\.pdf/i }));

    await waitFor(() => {
      expect(apiClient.deleteDocument).toHaveBeenCalled();
    });
    expect(vi.mocked(apiClient.deleteDocument).mock.calls[0][0]).toBe("doc-1");
    expect(confirmSpy).toHaveBeenCalledWith(
      "Delete delete-me.pdf and all indexed chunks? This cannot be undone.",
    );
    expect(await screen.findByText("Deleted delete-me.pdf")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /delete delete-me\.pdf/i })).not.toBeInTheDocument();
      expect(apiClient.jobs).toHaveBeenCalledTimes(2);
    });

    confirmSpy.mockRestore();
  });

  it("does not display SHA-256 values in the documents table", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "quiet-hash.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-hidden-from-documents-table",
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    expect(await screen.findByText("quiet-hash.pdf")).toBeVisible();
    expect(screen.queryByText("SHA-256")).not.toBeInTheDocument();
    expect(screen.queryByText("sha-hidden-from-documents-table")).not.toBeInTheDocument();
  });

  it("reindexes an uploaded document with the current parser and metadata", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "tafseer.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    expect(await screen.findByLabelText("Parser")).toHaveValue("mineru_strict");
    fireEvent.change(screen.getByLabelText("Custom JSON"), {
      target: {
        value: JSON.stringify({
          reference_schema: { type: "surah_ayah" },
          retrieval: { exact_reference_top1: true },
        }),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /reindex tafseer\.pdf/i }));

    await waitFor(() => {
      expect(apiClient.createDocumentReindexJob).toHaveBeenCalledWith("doc-1", {
        parser_mode: "mineru_strict",
        domain_metadata: expect.objectContaining({
          domain: "generic",
          document_type: "document",
          custom_json: {
            reference_schema: { type: "surah_ayah" },
            retrieval: { exact_reference_top1: true },
          },
        }),
      });
    });
    expect(await screen.findByText("Reindex queued for tafseer.pdf")).toBeVisible();
  });

  it("reindexes with the document's current index options when available", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "quran.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
          latest_index_options: {
            parser_mode: "mineru_strict",
            domain_metadata: {
              domain: "quran_tafseer",
              document_type: "commentary",
              tags: ["quran"],
              custom_json: {
                reference_schema: { type: "chapter_verse" },
                retrieval: { exact_reference_top1: true },
              },
            },
          },
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    fireEvent.click(await screen.findByRole("button", { name: /reindex quran\.pdf/i }));

    await waitFor(() => {
      expect(apiClient.createDocumentReindexJob).toHaveBeenCalledWith("doc-1", {
        parser_mode: "mineru_strict",
        domain_metadata: expect.objectContaining({
          domain: "quran_tafseer",
          document_type: "commentary",
          custom_json: {
            reference_schema: { type: "chapter_verse" },
            retrieval: { exact_reference_top1: true },
          },
        }),
      });
    });
  });

  it("allows stored-option reindex while the upload metadata form is invalid", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "quran.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
          latest_index_options: {
            parser_mode: "mineru_strict",
            domain_metadata: {
              domain: "quran_tafseer",
              document_type: "commentary",
              tags: ["quran"],
            },
          },
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    fireEvent.change(await screen.findByLabelText("Custom JSON"), {
      target: { value: "{not-json" },
    });
    const reindexButton = await screen.findByRole("button", { name: /reindex quran\.pdf/i });
    expect(reindexButton).toBeEnabled();

    fireEvent.click(reindexButton);

    await waitFor(() => {
      expect(apiClient.createDocumentReindexJob).toHaveBeenCalledWith("doc-1", {
        parser_mode: "mineru_strict",
        domain_metadata: expect.objectContaining({ domain: "quran_tafseer" }),
      });
    });
  });

  it("uses document filenames and MinerU progress in the jobs table", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "tafseer.pdf",
          content_type: "application/pdf",
          status: "running",
          sha256: "sha-1",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          id: "job-1",
          type: "index_document",
          status: "running",
          target_id: "doc-1",
          progress: 12,
          logs: ["MinerU parsing on HPC"],
          result: {
            mineru: {
              status: "parsing",
              progress: 47,
              detail: "OCR page 3",
            },
          },
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    expect(await screen.findByText("Index tafseer.pdf")).toBeVisible();
    expect(screen.getByText("Index Document · job-1")).toBeVisible();
    expect(screen.getByText("47%")).toBeVisible();
    expect(screen.getByText("MinerU Parsing")).toBeVisible();
    expect(screen.getByText("MinerU: Parsing · 47% · OCR page 3")).toBeVisible();
    expect(screen.queryByText("doc-1")).not.toBeInTheDocument();
  });

  it("polls jobs and documents while work is active", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.jobs)
      .mockResolvedValueOnce({
        items: [
          {
            id: "job-1",
            type: "index_document",
            status: "running",
            target_id: "doc-1",
            progress: 25,
            logs: [],
            result: {},
          },
        ],
        total: 1,
      })
      .mockResolvedValue({
        items: [
          {
            id: "job-1",
            type: "index_document",
            status: "succeeded",
            target_id: "doc-1",
            progress: 100,
            logs: [],
            result: {},
          },
        ],
        total: 1,
      });

    try {
      renderDocumentsPage();

      await vi.waitFor(() => {
        expect(apiClient.jobs).toHaveBeenCalledTimes(1);
        expect(apiClient.documents).toHaveBeenCalledTimes(1);
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      await vi.waitFor(() => {
        expect(apiClient.jobs).toHaveBeenCalledTimes(2);
      });
      await vi.waitFor(() => {
        expect(apiClient.documents).toHaveBeenCalledTimes(3);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not delete when confirmation is cancelled", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "keep-me.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
        },
      ],
      total: 1,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderDocumentsPage();

    fireEvent.click(await screen.findByRole("button", { name: /delete keep-me\.pdf/i }));

    expect(apiClient.deleteDocument).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});

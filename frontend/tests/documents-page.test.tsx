import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPage } from "../src/features/documents/documents-page";
import { apiClient } from "../src/api/client";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  FIRST_LIST_PAGE: { limit: 500, offset: 0 },
  apiClient: {
    documents: vi.fn(),
    jobs: vi.fn(),
    jobQualityWarnings: vi.fn(),
    domainProfiles: vi.fn(),
    suggestDomainMetadata: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    createDocumentReindexJob: vi.fn(),
    createJobEventSource: vi.fn(),
    fixJobQualityWarnings: vi.fn(),
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

function openJobsWarningsTab() {
  fireEvent.click(screen.getByRole("tab", { name: /jobs & warnings/i }));
}

const jobDefaults = {
  worker_id: null,
  lease_expires_at: null,
  heartbeat_at: null,
  attempts: 0,
  max_attempts: 3,
  recovery_action: null,
};

class MockJobEventSource {
  static instances: MockJobEventSource[] = [];

  readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  onmessage: ((event: MessageEvent) => void) | null = null;
  closed = false;

  constructor(readonly jobId: string) {
    MockJobEventSource.instances.push(this);
  }

  addEventListener(eventName: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(eventName, [...(this.listeners.get(eventName) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(eventName: string, payload: Record<string, unknown>) {
    const event = new MessageEvent(eventName, { data: JSON.stringify(payload) });
    if (eventName === "message") {
      this.onmessage?.(event);
    }
    this.listeners.get(eventName)?.forEach((listener) => listener(event));
  }
}

describe("DocumentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockJobEventSource.instances = [];
    vi.mocked(apiClient.documents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.jobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.jobQualityWarnings).mockResolvedValue({
      job_id: "job-empty",
      document_id: null,
      parser_quality: {},
      index_quality_report: null,
      job_warnings: [],
      warning_counts: {},
      affected_chunks: 0,
      total: 0,
      offset: 0,
      limit: 5000,
      truncated: false,
      items: [],
    });
    vi.mocked(apiClient.domainProfiles).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.suggestDomainMetadata).mockResolvedValue({
      domain_metadata: {
        domain: "quran_tafseer",
        document_type: "translation",
        metadata_sources: ["ai_vision"],
        custom_json: {
          quality_policy: {
            required_scripts: ["arabic", "latin"],
          },
        },
      },
      confidence: 0.95,
      evidence_pages: [1, 2, 3],
      rationale: "The sampled pages show Quran and translation references.",
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
    vi.mocked(apiClient.createJobEventSource).mockImplementation(
      (jobId) => new MockJobEventSource(jobId) as unknown as EventSource,
    );
    vi.mocked(apiClient.fixJobQualityWarnings).mockResolvedValue({
      source_job_id: "job-1",
      document_id: "doc-1",
      queued_job_id: "job-repair",
      queued_job_status: "ready",
      index_options: {
        parser_mode: "mineru_strict",
        domain_metadata: { domain: "quran_tafseer" },
      },
      repair_plan: {
        strategy: "metadata_aware_warning_repair",
        summary: "Apply metadata-aware fixes before reindex.",
        ai_suggestion: {
          status: "succeeded",
          suggestion: {
            summary: "Preserve Arabic and English hadith text in the same reference unit.",
          },
        },
        steps: [
          {
            code: "reference_unit_missing_expected_script",
            count: 176,
            action: "preserve_parallel_reference_units",
            reason: "Reference chunks are missing the expected Arabic script.",
            expected_effect: "Parallel Arabic/English chunks stay together.",
          },
        ],
      },
      message: "Generated a metadata-aware repair plan.",
    });
  });

  it("requests the first page of documents and jobs", async () => {
    renderDocumentsPage();

    await waitFor(() => {
      expect(apiClient.documents).toHaveBeenCalledWith({ limit: 500, offset: 0 });
      expect(apiClient.jobs).toHaveBeenCalledWith({ limit: 500, offset: 0 });
    });
  });

  it("keeps the file upload control visible and requires vision before upload", () => {
    renderDocumentsPage();

    const uploadInput = screen.getByLabelText(/upload file/i);
    expect(uploadInput).toBeVisible();

    const uploadButton = screen.getByRole("button", { name: /upload and index/i });
    expect(uploadButton).toBeDisabled();

    fireEvent.change(uploadInput, {
      target: {
        files: [new File(["pdf"], "sample.pdf", { type: "application/pdf" })],
      },
    });

    expect(uploadButton).toBeDisabled();
  });

  it("uploads only after vision metadata is generated for the selected file", async () => {
    renderDocumentsPage();

    const file = new File(["pdf"], "quran-arabic-english.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/upload file/i), { target: { files: [file] } });

    const uploadButton = screen.getByRole("button", { name: /upload and index/i });
    expect(uploadButton).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));

    await waitFor(() => {
      expect(apiClient.suggestDomainMetadata).toHaveBeenCalled();
    });
    expect(vi.mocked(apiClient.suggestDomainMetadata).mock.calls[0][0]).toEqual({ file });
    expect(await screen.findByText("quran_tafseer")).toBeVisible();
    expect(uploadButton).toBeEnabled();

    fireEvent.click(uploadButton);

    await waitFor(() => {
      expect(apiClient.uploadDocument).toHaveBeenCalled();
    });
    expect(vi.mocked(apiClient.uploadDocument).mock.calls[0][0]).toEqual({
      file,
      options: {
        parser_mode: "mineru_strict",
        domain_metadata: expect.objectContaining({
          domain: "quran_tafseer",
          document_type: "translation",
        }),
      },
    });
    expect(apiClient.uploadDocument).toHaveBeenCalledWith(
      {
        file,
        options: {
          parser_mode: "mineru_strict",
          domain_metadata: expect.objectContaining({
            domain: "quran_tafseer",
            document_type: "translation",
          }),
        },
      },
      expect.anything(),
    );
  });

  it("does not show manual profile or metadata controls in the upload flow", () => {
    renderDocumentsPage();

    expect(screen.queryByLabelText("Domain profile")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Parser")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Domain")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Document type")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Language")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Collection")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tags")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Custom JSON")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Override MinerU parser options")).not.toBeInTheDocument();
  });

  it("clears generated vision metadata when the selected file changes", async () => {
    renderDocumentsPage();

    const firstFile = new File(["first"], "first.pdf", { type: "application/pdf" });
    const secondFile = new File(["second"], "second.pdf", { type: "application/pdf" });
    const fileInput = screen.getByLabelText(/upload file/i);

    fireEvent.change(fileInput, { target: { files: [firstFile] } });
    fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));
    expect(await screen.findByText("Vision metadata generated")).toBeVisible();

    fireEvent.change(fileInput, { target: { files: [secondFile] } });

    expect(screen.queryByText("Vision metadata generated")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and index/i })).toBeDisabled();
  });

  it("blocks upload when vision metadata generation fails", async () => {
    vi.mocked(apiClient.suggestDomainMetadata).mockRejectedValueOnce(
      new Error("Vision service unavailable"),
    );
    renderDocumentsPage();

    const file = new File(["pdf"], "sample.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/upload file/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /analyze with vision/i }));

    expect(await screen.findByText("Vision service unavailable")).toBeVisible();
    expect(screen.getByRole("button", { name: /upload and index/i })).toBeDisabled();
    expect(apiClient.uploadDocument).not.toHaveBeenCalled();
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

  it("opens document parse evidence from a document row action", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-evidence",
          filename: "traceable.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-evidence",
        },
      ],
      total: 1,
    });

    renderDocumentsPage();

    fireEvent.click(await screen.findByRole("button", { name: /open parse evidence for traceable\.pdf/i }));

    expect(window.location.pathname).toBe("/document-evidence");
    expect(new URLSearchParams(window.location.search).get("documentId")).toBe("doc-evidence");
  });

  it("searches the documents and jobs tables", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-quran",
          filename: "quran.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-quran",
        },
        {
          id: "doc-tafseer",
          filename: "tafseer-notes.pdf",
          content_type: "application/pdf",
          status: "running",
          sha256: "sha-tafseer",
        },
      ],
      total: 2,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          ...jobDefaults,
          id: "job-quran",
          type: "index_document",
          status: "succeeded",
          target_id: "doc-quran",
          progress: 100,
          logs: ["Parser quality warnings: reference_unit_missing_expected_script=2"],
          result: {
            warnings: ["Graph extraction skipped because Neo4j is unavailable"],
          },
        },
        {
          ...jobDefaults,
          id: "job-tafseer",
          type: "index_document",
          status: "running",
          target_id: "doc-tafseer",
          progress: 41,
          logs: ["MinerU parsing on HPC"],
          result: {},
        },
      ],
      total: 2,
    });

    renderDocumentsPage();

    const documentsTable = await screen.findByRole("table", { name: "Documents table" });
    expect(within(documentsTable).getByText("quran.pdf")).toBeVisible();
    expect(within(documentsTable).getByText("tafseer-notes.pdf")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Search documents"), {
      target: { value: "tafseer" },
    });

    expect(within(documentsTable).queryByText("quran.pdf")).not.toBeInTheDocument();
    expect(within(documentsTable).getByText("tafseer-notes.pdf")).toBeVisible();

    openJobsWarningsTab();
    const jobsTable = await screen.findByRole("table", { name: "Jobs table" });
    fireEvent.change(screen.getByLabelText("Search jobs"), {
      target: { value: "graph extraction" },
    });

    expect(within(jobsTable).getByText("Index quran.pdf")).toBeVisible();
    expect(within(jobsTable).queryByText("Index tafseer-notes.pdf")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Job status"), {
      target: { value: "running" },
    });

    expect(screen.getByText("No matching jobs")).toBeVisible();
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
            mineru_parse_options: {
              parse_method: "ocr",
              backend: "pipeline",
              device: "cuda:0",
              lang: "arabic",
              formula: false,
              table: true,
              max_concurrent_files: 2,
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
        mineru_parse_options: {
          parse_method: "ocr",
          backend: "pipeline",
          device: "cuda:0",
          lang: "arabic",
          formula: false,
          table: true,
          max_concurrent_files: 2,
        },
      });
    });
  });

  it("disables reindex when a document has no stored index options", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "legacy.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
          latest_index_options: null,
        },
      ],
      total: 1,
      limit: 500,
      offset: 0,
    });

    renderDocumentsPage();

    expect(await screen.findByRole("button", { name: /reindex legacy\.pdf/i })).toBeDisabled();
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
          ...jobDefaults,
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
    openJobsWarningsTab();

    expect(await screen.findByText("Index tafseer.pdf")).toBeVisible();
    expect(screen.getByText("Index Document · job-1")).toBeVisible();
    expect(screen.getByText("47%")).toBeVisible();
    expect(screen.getByText("MinerU Parsing")).toBeVisible();
    expect(screen.getByText("MinerU: Parsing · 47% · OCR page 3")).toBeVisible();
    expect(screen.queryByText("doc-1")).not.toBeInTheDocument();
  });

  it("shows indexing stage details and warnings", async () => {
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
              document_type: "scripture",
              tags: ["arabic"],
            },
          },
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          ...jobDefaults,
          id: "job-1",
          type: "index_document",
          status: "succeeded",
          target_id: "doc-1",
          progress: 100,
          logs: ["Indexing completed with warnings"],
          result: {
            mineru: {
              status: "ready",
              progress: 80,
              detail: "MinerU artifacts ready",
            },
            indexing_stage: {
              status: "ready_with_warnings",
              label: "Ready with warnings",
              detail: "Vector index ready; graph skipped",
              progress: 100,
              chunk_count: 1754,
            },
            warnings: [
              "Graph extraction skipped because Neo4j is unavailable",
              "Some chunk metadata could not be normalized",
            ],
            parser_quality_details: {
              version: 1,
              sample_limit: 5,
              groups: [
                {
                  code: "reference_unit_missing_expected_script",
                  chunk_count: 2847,
                  warning_count: 2847,
                  raw_chunk_count: 2847,
                  raw_warning_count: 2847,
                  message:
                    "Reference-bearing chunk is expected to contain Arabic script, but no Arabic letters were detected.",
                  block_types: {},
                  expected_scripts: { arabic: 2847 },
                  actions: { quarantine_exact_arabic: 2847 },
                  pages: [412],
                  references: ["19:13"],
                  examples: [
                    {
                      chunk_id: "chunk-19-13",
                      page: 412,
                      reference: "19:13",
                      block_type: null,
                      expected_script: "arabic",
                      action: "quarantine_exact_arabic",
                      counted: true,
                      message:
                        "Reference-bearing chunk is expected to contain Arabic script, but no Arabic letters were detected.",
                      text_preview:
                        "[19:13] And affection from Us and purity, and he was fearing of Allah",
                    },
                  ],
                },
              ],
            },
          },
        },
      ],
      total: 1,
    });

    renderDocumentsPage();
    openJobsWarningsTab();

    const jobsTable = await screen.findByRole("table", { name: "Jobs table" });
    expect(within(jobsTable).getByText("Index quran.pdf")).toBeVisible();
    expect(
      screen.getByText("Ready with warnings · Vector index ready; graph skipped · 1754 chunks"),
    ).toBeVisible();
    expect(screen.getByText("Graph extraction skipped because Neo4j is unavailable")).toBeVisible();
    expect(screen.getByText("Some chunk metadata could not be normalized")).toBeVisible();
    const parserDetails = screen.getByText("Parser warning details · 1 types · 2847 counted warnings");
    expect(parserDetails).toBeVisible();
    fireEvent.click(parserDetails);
    expect(
      screen.getByText(
        "reference_unit_missing_expected_script · 2847 counted chunks · 2847 counted warnings",
      ),
    ).toBeVisible();
    expect(screen.getByText("Expected scripts: arabic=2847")).toBeVisible();
    expect(screen.getByText("References: 19:13")).toBeVisible();
    expect(
      screen.getByText("[19:13] And affection from Us and purity, and he was fearing of Allah"),
    ).toBeVisible();
    expect(screen.getByText("Indexing completed with warnings")).toBeVisible();
    expect(screen.getByText("100%")).toBeVisible();
    expect(screen.queryByText("MinerU: Ready · 80% · MinerU artifacts ready")).not.toBeInTheDocument();
    expect(screen.getByText("MinerU: Ready · MinerU artifacts ready")).toBeVisible();
  });

  it("renders live parser and canonical stage updates from job event streams", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "canonical.pdf",
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
          ...jobDefaults,
          id: "job-live",
          type: "index_document",
          status: "running",
          target_id: "doc-1",
          progress: 12,
          logs: ["Index job started"],
          result: {},
        },
      ],
      total: 1,
    });

    renderDocumentsPage();
    openJobsWarningsTab();

    expect(await screen.findByText("Index canonical.pdf")).toBeVisible();
    await waitFor(() => {
      expect(apiClient.createJobEventSource).toHaveBeenCalledWith("job-live");
    });

    act(() => {
      MockJobEventSource.instances[0].emit("job_stage", {
        stage: "canonical_assembly",
        label: "Canonicalizing chunks",
        detail: "Normalizing references before materialization",
        progress: 64,
        chunk_count: 128,
        log: "Canonical stage reached 64%",
      });
    });

    expect(await screen.findByText("64%")).toBeVisible();
    expect(
      screen.getByText(
        "Canonicalizing chunks · Normalizing references before materialization · 128 chunks",
      ),
    ).toBeVisible();
    expect(screen.getByText("Canonical stage reached 64%")).toBeVisible();
  });

  it("keeps polling when job event streams are unavailable", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "polling.pdf",
          content_type: "application/pdf",
          status: "running",
          sha256: "sha-1",
          artifact_path: "/tmp/polling.pdf",
          metadata: {},
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          ...jobDefaults,
          id: "job-polling",
          type: "index_document",
          status: "running",
          target_id: "doc-1",
          progress: 25,
          logs: ["Polling fallback remains active"],
          result: {},
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.createJobEventSource).mockReturnValue(null);

    renderDocumentsPage();
    openJobsWarningsTab();

    expect(await screen.findByText("Index polling.pdf")).toBeVisible();
    expect(screen.getByText("Polling fallback remains active")).toBeVisible();
    expect(MockJobEventSource.instances).toHaveLength(0);
  });

  it("opens persisted parser quality warning details from a compact job summary", async () => {
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
              document_type: "scripture",
              tags: ["arabic"],
            },
          },
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          ...jobDefaults,
          id: "job-1",
          type: "index_document",
          status: "succeeded",
          target_id: "doc-1",
          progress: 100,
          logs: ["Parser quality warnings: disallowed_block_type_quarantined=176"],
          result: {
            parser_quality: {
              warning_counts: { disallowed_block_type_quarantined: 176 },
              affected_chunks: 176,
            },
            warnings: ["Parser quality warnings: disallowed_block_type_quarantined=176"],
          },
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobQualityWarnings).mockResolvedValue({
      job_id: "job-1",
      document_id: "doc-1",
      parser_quality: {
        warning_counts: { disallowed_block_type_quarantined: 176 },
        affected_chunks: 176,
      },
      index_quality_report: {
        status: "passed_with_warnings",
        summary: {
          reference_units_missing_expected_script: 2,
          reference_unit_unresolved_count: 1,
        },
      },
      job_warnings: ["Parser quality warnings: disallowed_block_type_quarantined=176"],
      warning_counts: { disallowed_block_type_quarantined: 176 },
      affected_chunks: 176,
      total: 176,
      offset: 0,
      limit: 5000,
      truncated: false,
      items: [
        {
          chunk_id: "chunk-warning-1",
          chunk_preview: "Recovered body text near the quarantined parser block.",
          source_location: { page: 12, artifact: "content_list.json" },
          parser_metadata: { artifact_ref: "content_list.json", chunk_index: 42 },
          reference_metadata: { references: ["19:13"] },
          code: "disallowed_block_type_quarantined",
          message: "Quarantined text-bearing block because the profile disallows it.",
          block_type: "heading",
          page: 12,
          warning: {
            code: "disallowed_block_type_quarantined",
            message: "Quarantined text-bearing block because the profile disallows it.",
            block_type: "heading",
            page: 12,
          },
        },
        {
          chunk_id: "chunk-warning-2",
          chunk_preview: "English-only ayah 19:13 preview.",
          source_location: { page: 99, artifact: "content_list.json" },
          parser_metadata: { artifact_ref: "content_list.json", chunk_index: 43 },
          reference_metadata: { references: ["19:13"] },
          code: "reference_unit_missing_expected_script",
          message:
            "Reference-bearing chunk is expected to contain Arabic script, but no Arabic letters were detected.",
          block_type: null,
          page: 99,
          warning: {
            code: "reference_unit_missing_expected_script",
            message:
              "Reference-bearing chunk is expected to contain Arabic script, but no Arabic letters were detected.",
            page: 99,
          },
        },
      ],
    });

    renderDocumentsPage();
    openJobsWarningsTab();

    fireEvent.click(
      await screen.findByRole("button", {
        name: /inspect warning details for index quran\.pdf/i,
      }),
    );

    await waitFor(() => {
      expect(apiClient.jobQualityWarnings).toHaveBeenCalledWith("job-1");
    });
    expect(await screen.findByText("Warning details")).toBeVisible();
    expect(screen.getByText("disallowed_block_type_quarantined=176")).toBeVisible();
    expect(screen.getByText("counted_warning_chunks=176")).toBeVisible();
    expect(screen.getByText("warning_detail_rows=176")).toBeVisible();
    expect(
      screen.getByText("Index quality: Passed With Warnings · 2 missing expected script · 1 unresolved references"),
    ).toBeVisible();
    expect(screen.getByText("Quarantined text-bearing block because the profile disallows it.")).toBeVisible();
    expect(screen.getByText("Recovered body text near the quarantined parser block.")).toBeVisible();
    expect(screen.getByText("chunk-warning-1")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Search warning details"), {
      target: { value: "english-only" },
    });
    expect(await screen.findByText("chunk-warning-2")).toBeVisible();
    expect(screen.queryByText("chunk-warning-1")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Warning type"), {
      target: { value: "disallowed_block_type_quarantined" },
    });
    expect(screen.getByText("No matching warnings")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Search warning details"), {
      target: { value: "" },
    });
    expect(await screen.findByText("chunk-warning-1")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /fix warnings for index quran\.pdf/i }));

    await waitFor(() => {
      expect(vi.mocked(apiClient.fixJobQualityWarnings).mock.calls[0][0]).toBe("job-1");
    });
    expect(await screen.findByText("Repair job queued: job-repair")).toBeVisible();
    expect(screen.getByText("Repair plan")).toBeVisible();
    expect(screen.getByText("Apply metadata-aware fixes before reindex.")).toBeVisible();
    expect(
      screen.getByText("reference_unit_missing_expected_script · 176 · preserve_parallel_reference_units"),
    ).toBeVisible();
    expect(
      screen.getByText("AI suggestion: Preserve Arabic and English hadith text in the same reference unit."),
    ).toBeVisible();
  });

  it("shows suppressed parser recovery rows without counting them", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
      items: [
        {
          id: "doc-1",
          filename: "quran.pdf",
          content_type: "application/pdf",
          status: "succeeded",
          sha256: "sha-1",
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobs).mockResolvedValue({
      items: [
        {
          ...jobDefaults,
          id: "job-1",
          type: "index_document",
          status: "succeeded",
          target_id: "doc-1",
          progress: 100,
          logs: ["Parser quality warnings were audited"],
          result: {
            warnings: ["Parser quality warnings were audited"],
          },
        },
      ],
      total: 1,
    });
    vi.mocked(apiClient.jobQualityWarnings).mockResolvedValue({
      job_id: "job-1",
      document_id: "doc-1",
      parser_quality: { warning_counts: {}, affected_chunks: 0 },
      index_quality_report: null,
      job_warnings: [],
      warning_counts: {},
      affected_chunks: 0,
      total: 1,
      offset: 0,
      limit: 5000,
      truncated: false,
      items: [
        {
          chunk_id: "chunk-audit-1",
          chunk_preview: "Audit-only recovered parser text.",
          source_location: { page: 12 },
          parser_metadata: {},
          reference_metadata: null,
          code: "recovered_text_from_disallowed_block",
          message: "Used parser-provided recovered text.",
          block_type: "equation",
          page: 12,
          warning: {
            code: "recovered_text_from_disallowed_block",
            message: "Used parser-provided recovered text.",
            severity: "info",
            quality_gate_action: "accepted_recovery",
            suppressed_from_counts: true,
          },
        },
      ],
    });

    renderDocumentsPage();
    openJobsWarningsTab();

    fireEvent.click(
      await screen.findByRole("button", {
        name: /inspect warning details for index quran\.pdf/i,
      }),
    );

    expect(await screen.findByText("No counted parser warnings.")).toBeVisible();
    expect(screen.getByText("Recovered text")).toBeVisible();
    expect(screen.getByText("Accepted recovery")).toBeVisible();
    expect(
      screen.getByText("This row is audit evidence, not a counted parser warning."),
    ).toBeVisible();
    expect(screen.getByText("counted_warning_chunks=0")).toBeVisible();
    expect(screen.getByText("warning_detail_rows=1")).toBeVisible();
    expect(screen.getByText("Audit-only recovered parser text.")).toBeVisible();
  });

  it("polls jobs and documents while work is active", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.jobs)
      .mockResolvedValueOnce({
        items: [
          {
            ...jobDefaults,
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
            ...jobDefaults,
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

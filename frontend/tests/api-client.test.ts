import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient, createJobEventSource, jobEventsUrl } from "../src/api/client";
import type { IndexDocumentIn } from "../src/api/generated";

describe("apiClient document uploads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes document-specific MinerU parser options on upload", async () => {
    let body: BodyInit | null | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url, init?: RequestInit) => {
        body = init?.body;
        return new Response(
          JSON.stringify({
            id: "doc-upload",
            filename: "tafseer.pdf",
            content_type: "application/pdf",
            status: "ready",
            sha256: "sha",
          }),
          { headers: { "Content-Type": "application/json" }, status: 201 },
        );
      }),
    );
    const file = new File(["pdf"], "tafseer.pdf", { type: "application/pdf" });
    const mineruParseOptions = {
      parse_method: "ocr",
      backend: "pipeline",
      device: "cuda:0",
      lang: "arabic",
      formula: false,
      table: false,
      source: "huggingface",
      max_concurrent_files: 2,
    };

    await apiClient.uploadDocument({
      file,
      options: {
        parser_mode: "mineru_strict",
        domain_metadata: { domain: "quran_tafseer" },
        mineru_parse_options: mineruParseOptions,
      } as IndexDocumentIn,
    });

    const formData = body as FormData;
    expect(formData.get("parser_mode")).toBe("mineru_strict");
    expect(formData.get("domain_metadata")).toBe(
      JSON.stringify({ domain: "quran_tafseer" }),
    );
    expect(formData.get("mineru_parse_options")).toBe(JSON.stringify(mineruParseOptions));
  });

  it("builds job event stream URLs and EventSource instances", () => {
    const eventSourceMock = vi.fn();
    vi.stubGlobal("EventSource", eventSourceMock);

    expect(jobEventsUrl("job/with spaces")).toBe("/api/jobs/job%2Fwith%20spaces/events");
    createJobEventSource("job-1");

    expect(eventSourceMock).toHaveBeenCalledWith("/api/jobs/job-1/events");
    expect(apiClient.jobEventsUrl("job-1")).toBe("/api/jobs/job-1/events");
  });

  it("returns null for job event streams when EventSource is unavailable", () => {
    vi.stubGlobal("EventSource", undefined);

    expect(createJobEventSource("job-1")).toBeNull();
  });

  it("passes pagination query params for list endpoints", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        urls.push(String(url));
        return new Response(
          JSON.stringify({ items: [], total: 0, limit: 25, offset: 50, has_more: false }),
          { headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    await apiClient.documents({ limit: 25, offset: 50 });
    await apiClient.jobs({ limit: 25, offset: 50 });
    await apiClient.runs({ limit: 25, offset: 50 });
    await apiClient.variants({ limit: 25, offset: 50 });
    await apiClient.experiments({ limit: 25, offset: 50 });

    expect(urls).toEqual([
      "/api/documents?limit=25&offset=50",
      "/api/jobs?limit=25&offset=50",
      "/api/runs?limit=25&offset=50",
      "/api/variants?limit=25&offset=50",
      "/api/experiments?limit=25&offset=50",
    ]);
  });

  it("requests the maximum first page for legacy list callers", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        urls.push(String(url));
        return new Response(
          JSON.stringify({ items: [], total: 0, limit: 500, offset: 0, has_more: false }),
          { headers: { "Content-Type": "application/json" } },
        );
      }),
    );

    await apiClient.documents();
    await apiClient.jobs();
    await apiClient.runs();
    await apiClient.variants();
    await apiClient.experiments();

    expect(urls).toEqual([
      "/api/documents?limit=500&offset=0",
      "/api/jobs?limit=500&offset=0",
      "/api/runs?limit=500&offset=0",
      "/api/variants?limit=500&offset=0",
      "/api/experiments?limit=500&offset=0",
    ]);
  });

  it("keeps chunk pagination in the request body and graph pagination in query params", async () => {
    const urls: string[] = [];
    const bodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, init) => {
        urls.push(String(url));
        bodies.push(init?.body ? JSON.parse(String(init.body)) : null);
        return new Response(JSON.stringify({ items: [], total: 0, nodes: [], edges: [] }), {
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    await apiClient.searchChunks(
      { query: "reference", document_ids: [], limit: 5, offset: 20 },
    );
    await apiClient.graph({ document_id: "doc-1", limit: 50, offset: 10 });

    expect(urls).toEqual([
      "/api/chunks/search",
      "/api/graph?document_id=doc-1&limit=50&offset=10",
    ]);
    expect(bodies[0]).toMatchObject({ query: "reference", limit: 5, offset: 20 });
  });

  it("fetches runtime defaults", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            runtime: { top_k: 40, chunk_top_k: 20, max_context_tokens: 2000 },
            policy_versions: { retrieval: "2026-05-24" },
          }),
          { headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const result = await apiClient.defaults();

    expect(fetch).toHaveBeenCalledWith("/api/defaults", expect.any(Object));
    expect(result.policy_versions.retrieval).toBe("2026-05-24");
  });
});

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
});

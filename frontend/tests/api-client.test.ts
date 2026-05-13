import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
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
});

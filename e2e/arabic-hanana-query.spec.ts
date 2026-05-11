import { expect, test } from "../frontend/node_modules/@playwright/test";

test("Quran Arabic lexical query shows trace behavior for live data", async ({ page }) => {
  await page.goto("/query");

  const quranDocument = page
    .locator("label")
    .filter({ hasText: "quran_arabic_english.pdf" })
    .locator('input[type="checkbox"]')
    .first();
  await expect(quranDocument).toBeVisible({ timeout: 30_000 });
  await quranDocument.check();

  const quranFastLexical = page
    .locator("label")
    .filter({ hasText: "Quran fast lexical" })
    .locator('input[type="checkbox"]')
    .first();
  if (await quranFastLexical.count()) {
    await quranFastLexical.check();
  } else {
    await page.locator('fieldset:has(legend:text("Variants")) input[type="checkbox"]').first().check();
  }

  await page.getByLabel("Question").fill("حنانا");
  await page.getByLabel("Chunk limit").fill("5");

  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/query") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /run/i }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const responseBody = await response.json();

  await expect(page.getByText("Run complete")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole("heading", { name: "حنانا" })).toBeVisible();

  const body = await page.locator("body").innerText();
  expect(body).toMatch(/chunk traces/i);

  const runs = Array.isArray(responseBody.runs) ? responseBody.runs : [];
  const runWithTraces = runs.find(
    (run) => Array.isArray(run.chunk_traces) && run.chunk_traces.length > 0,
  );
  expect(runWithTraces, "expected at least one query run to include chunk traces").toBeTruthy();

  const chunkTraces = runWithTraces?.chunk_traces ?? [];
  const serializedTraces = JSON.stringify(chunkTraces);
  expect(
    chunkTraces.some(hasRetrievalTraceData),
    "expected chunk traces to include metadata retrieval or candidate-count data",
  ).toBe(true);

  const hasSources = runs.some((run) => Array.isArray(run.sources) && run.sources.length > 0);
  const serializedResponse = JSON.stringify(responseBody);
  if (!hasSources || body.includes("No sources returned.")) {
    expect(serializedTraces).toMatch(/"metadata_candidates":\s*0/);
  } else {
    expect(`${body}\n${serializedResponse}`).toContain("19:13");
  }
});

function hasRetrievalTraceData(trace: unknown) {
  if (!isTraceRecord(trace)) {
    return false;
  }

  const serialized = JSON.stringify(trace);
  return (
    Object.hasOwn(trace, "metadata_candidates") ||
    serialized.includes("metadata_candidates") ||
    serialized.includes("metadata_retrieval") ||
    serialized.includes("metadata_fallback") ||
    serialized.includes("retrieval")
  );
}

function isTraceRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

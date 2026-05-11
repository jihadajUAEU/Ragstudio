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
  expect(body).toContain("metadata_candidates");

  const runs = Array.isArray(responseBody.runs) ? responseBody.runs : [];
  const hasSources = runs.some((run) => Array.isArray(run.sources) && run.sources.length > 0);
  const serializedResponse = JSON.stringify(responseBody);
  if (!hasSources || body.includes("No sources returned.")) {
    expect(`${body}\n${serializedResponse}`).toMatch(/"metadata_candidates":\s*0/);
  } else {
    expect(`${body}\n${serializedResponse}`).toContain("19:13");
  }
});

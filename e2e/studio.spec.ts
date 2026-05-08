import { expect, test } from "@playwright/test";

test("Studio shell loads dashboard", async ({ page }) => {
  await page.goto("http://127.0.0.1:5173");

  await expect(page.getByText("RAG-Anything").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Studio Dashboard" })).toBeVisible();
  await expect(page.getByText("Pipeline, retrieval, and evaluation state")).toBeVisible();
});

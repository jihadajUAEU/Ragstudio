import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../src/api/client";
import type { VariantOut, VariantPreset } from "../src/api/generated";
import { VariantsPage } from "../src/features/variants/variants-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    variants: vi.fn(),
    createVariant: vi.fn(),
    updateVariant: vi.fn(),
    deleteVariant: vi.fn(),
  },
}));

describe("VariantsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(apiClient.variants).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.createVariant).mockResolvedValue(variant("variant-new", "Balanced"));
    vi.mocked(apiClient.updateVariant).mockResolvedValue(variant("variant-1", "Edited"));
    vi.mocked(apiClient.deleteVariant).mockResolvedValue(undefined);
  });

  it("creates a variant from the form", async () => {
    renderVariantsPage();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Balanced QA" } });
    fireEvent.change(screen.getByLabelText("Preset"), { target: { value: "broad" } });
    fireEvent.change(screen.getByLabelText("Parameters"), {
      target: { value: '{ "top_k": 9, "enable_rerank": true }' },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Create$/i }));

    await waitFor(() => expect(apiClient.createVariant).toHaveBeenCalled());
    expect(vi.mocked(apiClient.createVariant).mock.calls[0][0]).toEqual({
      name: "Balanced QA",
      preset: "broad",
      parameters: { top_k: 9, enable_rerank: true },
    });
  });

  it("previews preset defaults when the preset changes", async () => {
    renderVariantsPage();

    fireEvent.change(screen.getByLabelText("Preset"), { target: { value: "fast" } });

    await waitFor(() =>
      expect(screen.getByLabelText("Parameters")).toHaveValue(
        '{\n  "top_k": 4,\n  "temperature": 0,\n  "enable_rerank": false\n}',
      ),
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Fast QA" } });
    fireEvent.click(screen.getByRole("button", { name: /^Create$/i }));

    await waitFor(() => expect(apiClient.createVariant).toHaveBeenCalled());
    expect(vi.mocked(apiClient.createVariant).mock.calls[0][0]).toEqual({
      name: "Fast QA",
      preset: "fast",
      parameters: { top_k: 4, temperature: 0, enable_rerank: false },
    });
  });

  it("loads a variant into edit mode and updates it", async () => {
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [variant("variant-1", "Original", "balanced", { top_k: 5, temperature: 0.2 })],
      total: 1,
    });

    renderVariantsPage();

    expect(await screen.findByText("Original")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Edit variant Original"));

    expect(screen.getByRole("heading", { name: "Edit variant" })).toBeVisible();
    expect(screen.getByDisplayValue("Original")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Edited" } });
    fireEvent.change(screen.getByLabelText("Preset"), { target: { value: "precise" } });
    fireEvent.change(screen.getByLabelText("Parameters"), {
      target: { value: '{ "temperature": 0.05 }' },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Update$/i }));

    await waitFor(() => expect(apiClient.updateVariant).toHaveBeenCalled());
    expect(vi.mocked(apiClient.updateVariant).mock.calls[0]).toEqual([
      "variant-1",
      {
        name: "Edited",
        preset: "precise",
        parameters: { temperature: 0.05 },
      },
    ]);
  });

  it("deletes a variant from the matrix", async () => {
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [variant("variant-1", "Disposable")],
      total: 1,
    });

    renderVariantsPage();

    expect(await screen.findByText("Disposable")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Delete variant Disposable"));

    expect(window.confirm).toHaveBeenCalledWith(
      "Delete variant Disposable? This cannot be undone.",
    );
    await waitFor(() => expect(apiClient.deleteVariant).toHaveBeenCalledWith("variant-1"));
  });

  it("keeps a variant when delete confirmation is cancelled", async () => {
    vi.mocked(apiClient.variants).mockResolvedValue({
      items: [variant("variant-1", "Keeper")],
      total: 1,
    });
    vi.mocked(window.confirm).mockReturnValue(false);

    renderVariantsPage();

    expect(await screen.findByText("Keeper")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Delete variant Keeper"));

    expect(apiClient.deleteVariant).not.toHaveBeenCalled();
  });
});

function renderVariantsPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <VariantsPage />
    </QueryClientProvider>,
  );
}

function variant(
  id: string,
  name: string,
  preset: VariantPreset = "balanced",
  parameters: Record<string, unknown> = { top_k: 5, temperature: 0.2, enable_rerank: true },
): VariantOut {
  return {
    id,
    name,
    preset,
    parameters,
  };
}

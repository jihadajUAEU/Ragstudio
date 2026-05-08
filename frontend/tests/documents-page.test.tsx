import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsPage } from "../src/features/documents/documents-page";
import { apiClient } from "../src/api/client";

vi.mock("../src/api/client", () => ({
  apiClient: {
    documents: vi.fn(),
    jobs: vi.fn(),
    domainProfiles: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
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
    vi.mocked(apiClient.deleteDocument).mockResolvedValue(undefined);
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

  it("confirms and deletes an uploaded document", async () => {
    vi.mocked(apiClient.documents).mockResolvedValue({
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
    });
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

    confirmSpy.mockRestore();
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

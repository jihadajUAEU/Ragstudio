import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComparisonPage } from "../src/features/comparison/comparison-page";

vi.mock("../src/api/client", () => ({
  apiClient: {
    runs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    variants: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

describe("ComparisonPage", () => {
  it("renders the heading", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ComparisonPage />
      </QueryClientProvider>,
    );

    expect(screen.getByRole("heading", { name: /run comparison/i })).toBeInTheDocument();
  });
});

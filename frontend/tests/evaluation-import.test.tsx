import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EvaluationPage } from "../src/features/evaluation/evaluation-page";

vi.mock("../src/api/client", () => ({
  DEFAULT_PARSER_MODE: "mineru_strict",
  apiClient: {
    evaluationSets: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    importEvaluationSet: vi.fn(),
  },
}));

describe("EvaluationPage", () => {
  it("renders the upload control", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <EvaluationPage />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/upload evaluation file/i)).toBeInTheDocument();
  });
});

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, Search } from "lucide-react";

import { apiClient } from "../../api/client";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { DocumentPipelineStageFlow } from "./document-pipeline-stage-flow";
import { EvidenceInspector } from "./evidence-inspector";

const queryKey = "document-parse-evidence";
const timelineQueryKey = "document-pipeline-timeline";

export function DocumentEvidencePage() {
  const documentId = new URLSearchParams(window.location.search).get("documentId")?.trim() ?? "";
  const evidenceQuery = useQuery({
    queryKey: [queryKey, documentId],
    queryFn: () => apiClient.documentParseEvidence(documentId),
    enabled: documentId.length > 0,
  });
  const timelineQuery = useQuery({
    queryKey: [timelineQueryKey, documentId],
    queryFn: () => apiClient.documentPipelineTimeline(documentId),
    enabled: documentId.length > 0,
  });

  if (!documentId) {
    return (
      <EmptyState
        icon={Search}
        title="Select a document"
        description="Open document parse evidence from a document row or add ?documentId=... to the URL."
      />
    );
  }

  if (evidenceQuery.isLoading) {
    return (
      <EmptyState
        icon={Loader2}
        title="Loading evidence"
        description="Fetching document parse evidence."
      />
    );
  }

  const errorMessage =
    evidenceQuery.error instanceof Error
      ? evidenceQuery.error.message
      : "Document parse evidence could not be loaded.";
  const timelineErrorMessage =
    timelineQuery.error instanceof Error
      ? timelineQuery.error.message
      : "Document pipeline stage flow could not be loaded.";

  if (evidenceQuery.isError && !evidenceQuery.data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Evidence unavailable"
        description={errorMessage}
        action={
          <Button type="button" variant="secondary" onClick={() => void evidenceQuery.refetch()}>
            Retry
          </Button>
        }
      />
    );
  }

  if (!evidenceQuery.data) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Evidence unavailable"
        description="No evidence returned."
      />
    );
  }

  return (
    <div className="space-y-4">
      {evidenceQuery.isError ? (
        <section
          className="rounded-md border border-[#e5c36b] bg-[#fff8e6] p-4"
          role="alert"
          aria-live="polite"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[#5f4600]">Showing cached evidence</p>
              <p className="mt-1 text-sm text-[#705300]">{errorMessage}</p>
            </div>
            <Button type="button" variant="secondary" onClick={() => void evidenceQuery.refetch()}>
              Retry
            </Button>
          </div>
        </section>
      ) : null}
      {timelineQuery.data ? (
        <DocumentPipelineStageFlow timeline={timelineQuery.data} />
      ) : timelineQuery.isError ? (
        <section
          className="rounded-md border border-[#e5c36b] bg-[#fff8e6] p-4"
          role="alert"
          aria-live="polite"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[#5f4600]">
                Pipeline stage flow unavailable
              </p>
              <p className="mt-1 text-sm text-[#705300]">{timelineErrorMessage}</p>
            </div>
            <Button type="button" variant="secondary" onClick={() => void timelineQuery.refetch()}>
              Retry
            </Button>
          </div>
        </section>
      ) : null}
      <EvidenceInspector key={evidenceQuery.data.document.id} evidence={evidenceQuery.data} mode="local" />
    </div>
  );
}

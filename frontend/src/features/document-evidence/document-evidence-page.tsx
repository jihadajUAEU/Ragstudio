import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Loader2, Search } from "lucide-react";

import { apiClient } from "../../api/client";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { EvidenceInspector } from "./evidence-inspector";

const queryKey = "document-parse-evidence";

export function DocumentEvidencePage() {
  const documentId = new URLSearchParams(window.location.search).get("documentId")?.trim() ?? "";
  const evidenceQuery = useQuery({
    queryKey: [queryKey, documentId],
    queryFn: () => apiClient.documentParseEvidence(documentId),
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

  if (evidenceQuery.isError) {
    return (
      <EmptyState
        icon={AlertCircle}
        title="Evidence unavailable"
        description={
          evidenceQuery.error instanceof Error
            ? evidenceQuery.error.message
            : "Document parse evidence could not be loaded."
        }
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

  return <EvidenceInspector evidence={evidenceQuery.data} mode="local" />;
}

import { ExternalLink, X } from "lucide-react";
import type { ReactNode } from "react";

import { FocusTrapDialog } from "../../components/focus-trap-dialog";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

export interface EvidenceRouteLinks {
  documents?: boolean;
  chunks?: boolean;
  query?: boolean;
  graph?: boolean;
  diagnostics?: boolean;
  documentUnavailableLabel?: string;
}

export interface EvidenceRerankerSummary {
  status?: string;
  provider?: string;
  model?: string;
  detail?: string;
  note?: string;
  raw?: unknown;
}

export interface NormalizedEvidence {
  id: string;
  kind: "query-source" | "chunk" | "evidence";
  documentId?: string | null;
  documentName?: string | null;
  runtimeProfileId?: string | null;
  text?: string | null;
  sourceLocation?: Record<string, unknown> | string | null;
  metadata?: Record<string, unknown> | null;
  parserWarnings?: string[];
  qualityStatus?: string | null;
  retrievalReasons?: string[];
  relationshipRefs?: string[];
  rerankerSummary?: EvidenceRerankerSummary | null;
  raw?: unknown;
  routeLinks?: EvidenceRouteLinks;
}

export function EvidenceViewer({
  evidence,
  open,
  onClose,
  onNavigate,
}: {
  evidence: NormalizedEvidence | null;
  open: boolean;
  onClose: () => void;
  onNavigate?: (path: string) => void;
}) {
  const isOpen = open && evidence !== null;

  return (
    <FocusTrapDialog
      open={isOpen}
      title="Evidence details"
      overlayLabel="Close evidence details"
      onClose={onClose}
      overlayClassName="z-30"
      className="fixed inset-0 z-40 flex max-h-screen flex-col overflow-hidden bg-white sm:inset-y-0 sm:left-auto sm:right-0 sm:w-full sm:max-w-2xl sm:border-l sm:border-[#d6dde1]"
    >
      {evidence ? (
        <>
          <div className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-[#d6dde1] px-4 sm:px-5">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[#176b87]">Evidence details</p>
              <p className="truncate text-xs text-[#62717a]">{evidence.id}</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close evidence details"
              onClick={onClose}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 sm:px-5">
            <EvidenceSection title="Summary" defaultOpen>
              <SummaryGrid evidence={evidence} />
            </EvidenceSection>
            <EvidenceSection title="Chunk text">
              <TextBlock>{evidence.text || "Chunk text not recorded"}</TextBlock>
            </EvidenceSection>
            <EvidenceSection title="Source location">
              {evidence.sourceLocation ? (
                <JsonBlock value={evidence.sourceLocation} />
              ) : (
                <MissingText>Source location not recorded</MissingText>
              )}
            </EvidenceSection>
            <EvidenceSection title="Parser quality">
              <div className="space-y-2">
                <KeyValue label="Quality" value={evidence.qualityStatus || "Quality policy not recorded"} />
                {evidence.parserWarnings?.length ? (
                  <List values={evidence.parserWarnings} />
                ) : (
                  <MissingText>Parser warnings not recorded</MissingText>
                )}
              </div>
            </EvidenceSection>
            <EvidenceSection title="Retrieval reasons">
              {evidence.retrievalReasons?.length ? (
                <List values={evidence.retrievalReasons} />
              ) : (
                <MissingText>Retrieval reasons not recorded</MissingText>
              )}
            </EvidenceSection>
            <EvidenceSection title="Reranker">
              {evidence.rerankerSummary ? (
                <div className="space-y-2 text-sm text-[#3a4a53]">
                  <KeyValue label="Status" value={evidence.rerankerSummary.status || "Reranker status not recorded"} />
                  <KeyValue label="Provider" value={evidence.rerankerSummary.provider || "Provider not recorded"} />
                  <KeyValue label="Model" value={evidence.rerankerSummary.model || "Model not recorded"} />
                  {evidence.rerankerSummary.detail ? <p>{evidence.rerankerSummary.detail}</p> : null}
                  {evidence.rerankerSummary.note ? (
                    <p className="rounded-md bg-[#fff4d7] px-2 py-1 text-xs text-[#8a5a00]">
                      {evidence.rerankerSummary.note}
                    </p>
                  ) : null}
                </div>
              ) : (
                <MissingText>Reranker context not recorded</MissingText>
              )}
            </EvidenceSection>
            <EvidenceSection title="Graph context">
              {evidence.relationshipRefs?.length ? (
                <List values={evidence.relationshipRefs} />
              ) : (
                <MissingText>No graph relationship recorded for this evidence</MissingText>
              )}
            </EvidenceSection>
            <EvidenceSection title="Metadata">
              {evidence.metadata && Object.keys(evidence.metadata).length ? (
                <JsonBlock value={evidence.metadata} />
              ) : (
                <MissingText>Metadata not recorded</MissingText>
              )}
            </EvidenceSection>
            <EvidenceSection title="Route links">
              <RouteActions links={evidence.routeLinks} onNavigate={onNavigate} onClose={onClose} />
            </EvidenceSection>
            <EvidenceSection title="Raw JSON">
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]">
                {JSON.stringify(evidence.raw ?? evidence, null, 2)}
              </pre>
            </EvidenceSection>
          </div>
        </>
      ) : null}
    </FocusTrapDialog>
  );
}

function SummaryGrid({ evidence }: { evidence: NormalizedEvidence }) {
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-2">
      <KeyValue label="Evidence id" value={evidence.id} mono />
      <KeyValue label="Kind" value={evidence.kind} />
      <KeyValue label="Document" value={evidence.documentName || evidence.documentId || "Document link not recorded"} />
      <KeyValue label="Runtime profile" value={evidence.runtimeProfileId || "Not recorded"} />
      <KeyValue
        label="Source location"
        value={evidence.sourceLocation ? summarizeValue(evidence.sourceLocation) : "Source location not recorded"}
      />
      <KeyValue label="Quality" value={evidence.qualityStatus || "Quality policy not recorded"} />
      <KeyValue
        label="Parser warnings"
        value={
          evidence.parserWarnings?.length
            ? `${evidence.parserWarnings.length} recorded`
            : "Parser warnings not recorded"
        }
      />
      <KeyValue
        label="Graph"
        value={
          evidence.relationshipRefs?.length
            ? `${evidence.relationshipRefs.length} relationship refs`
            : "No graph relationship recorded for this evidence"
        }
      />
    </div>
  );
}

function EvidenceSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details
      open={defaultOpen}
      className="rounded-md border border-[#d6dde1] bg-white px-3 py-2"
    >
      <summary className="cursor-pointer py-1 text-sm font-semibold text-[#1f2933]">
        {title}
      </summary>
      <div className="mt-2 border-t border-[#e1e7ea] pt-3">{children}</div>
    </details>
  );
}

function KeyValue({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-md bg-[#f8fafb] px-3 py-2">
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <p className={cn("mt-1 break-words text-sm text-[#24313a]", mono && "font-mono text-xs")}>
        {value}
      </p>
    </div>
  );
}

function TextBlock({ children }: { children: ReactNode }) {
  return (
    <div className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-sm leading-6 text-[#24313a]">
      {children}
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function MissingText({ children }: { children: ReactNode }) {
  return <p className="text-sm text-[#62717a]">{children}</p>;
}

function List({ values }: { values: string[] }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {values.map((value) => (
        <li
          key={value}
          className="max-w-full break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] px-2 py-1 text-xs text-[#24313a]"
        >
          {value}
        </li>
      ))}
    </ul>
  );
}

function RouteActions({
  links,
  onNavigate,
  onClose,
}: {
  links?: EvidenceRouteLinks;
  onNavigate?: (path: string) => void;
  onClose: () => void;
}) {
  const routeActions = [
    { label: "Open Documents", path: "/documents", enabled: Boolean(links?.documents) },
    { label: "Open Chunks", path: "/chunks", enabled: Boolean(links?.chunks) },
    { label: "Open Query", path: "/query", enabled: Boolean(links?.query) },
    { label: "Open Graph", path: "/graph", enabled: Boolean(links?.graph) },
    { label: "Open Diagnostics", path: "/diagnostics", enabled: Boolean(links?.diagnostics) },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {routeActions.map((action) =>
        action.enabled && onNavigate ? (
          <Button
            key={action.label}
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              onClose();
              onNavigate(action.path);
            }}
          >
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            {action.label}
          </Button>
        ) : (
          <span
            key={action.label}
            className="inline-flex min-h-8 items-center rounded-md bg-[#f8fafb] px-3 text-xs text-[#62717a]"
            aria-disabled="true"
          >
            {action.label === "Open Documents"
              ? links?.documentUnavailableLabel ?? "Document link not recorded"
              : `${action.label.replace("Open ", "")} link not recorded`}
          </span>
        ),
      )}
    </div>
  );
}

function summarizeValue(value: Record<string, unknown> | string) {
  if (typeof value === "string") {
    return value;
  }
  const candidates = [
    value.label,
    value.page,
    value.page_number,
    value.chunk_index,
    value.reference,
    value.source,
  ]
    .filter((item) => item !== undefined && item !== null && item !== "")
    .map(String);
  return candidates.length ? candidates.join(" · ") : JSON.stringify(value);
}

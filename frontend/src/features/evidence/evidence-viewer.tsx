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
  originalRank?: number | null;
  newRank?: number | null;
  rankChange?: number | null;
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
  contextWarnings?: string[];
  relationshipRefs?: string[];
  graphUnavailableDetail?: string | null;
  rerankerSummary?: EvidenceRerankerSummary | null;
  rank?: number | null;
  score?: number | null;
  signals?: string[];
  architecture?: {
    domain?: {
      domain: string;
      materializationHint: string;
      qualityPolicy: string;
    };
    layout?: {
      layoutGroupId: string;
      layoutRole: string;
      readingOrder: string;
    };
    context?: {
      parentChunkId: string;
      previousChunkId: string;
      nextChunkId: string;
    };
    assembly?: {
      groundingStatus: string;
      evidenceIds: string[];
      droppedReasons: string[];
      contextSlot?: string;
      linkedBy?: string;
      addedToContext?: boolean;
      contextTokens?: number | null;
    };
  };
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
                <KeyValue label="Quality" value={evidence.qualityStatus || "Default quality policy"} />
                {evidence.parserWarnings?.length ? (
                  <List values={evidence.parserWarnings} />
                ) : (
                  <MissingText>No parser warnings for this evidence</MissingText>
                )}
              </div>
            </EvidenceSection>
            <EvidenceSection title="Domain and materialization">
              <ArchitectureKeyValues
                values={[
                  ["Domain", evidence.architecture?.domain?.domain],
                  ["Materialization", evidence.architecture?.domain?.materializationHint],
                  ["Quality policy", evidence.architecture?.domain?.qualityPolicy],
                ]}
              />
            </EvidenceSection>
            <EvidenceSection title="Layout chain">
              <ArchitectureKeyValues
                values={[
                  ["Layout group", evidence.architecture?.layout?.layoutGroupId],
                  ["Layout role", evidence.architecture?.layout?.layoutRole],
                  ["Reading order", evidence.architecture?.layout?.readingOrder],
                ]}
              />
            </EvidenceSection>
            <EvidenceSection title="Context chain">
              <div className="space-y-2">
                <ArchitectureKeyValues
                  values={[
                    ["Parent", evidence.architecture?.context?.parentChunkId],
                    ["Previous", evidence.architecture?.context?.previousChunkId],
                    ["Next", evidence.architecture?.context?.nextChunkId],
                  ]}
                />
                <ReasonList
                  label="Layout/context loss"
                  values={evidence.contextWarnings}
                />
              </div>
            </EvidenceSection>
            {evidence.architecture?.assembly ? (
              <EvidenceSection title="Context assembly">
                <ArchitectureKeyValues
                  values={[
                    ["Grounding", evidence.architecture.assembly.groundingStatus],
                    ["Context slot", evidence.architecture.assembly.contextSlot],
                    ["Linked by", evidence.architecture.assembly.linkedBy],
                    ["Added to context", evidence.architecture.assembly.addedToContext ? "yes" : "no"],
                    [
                      "Context tokens",
                      evidence.architecture.assembly.contextTokens === null ||
                      evidence.architecture.assembly.contextTokens === undefined
                        ? undefined
                        : String(evidence.architecture.assembly.contextTokens),
                    ],
                    ["Evidence ids", evidence.architecture.assembly.evidenceIds.join(", ")],
                    ["Dropped", evidence.architecture.assembly.droppedReasons.join(", ")],
                  ]}
                />
              </EvidenceSection>
            ) : null}
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
                  <KeyValue
                    label="Original rank"
                    value={
                      evidence.rerankerSummary.originalRank === null ||
                      evidence.rerankerSummary.originalRank === undefined
                        ? "not recorded"
                        : String(evidence.rerankerSummary.originalRank)
                    }
                  />
                  <KeyValue
                    label="New rank"
                    value={
                      evidence.rerankerSummary.newRank === null ||
                      evidence.rerankerSummary.newRank === undefined
                        ? "not recorded"
                        : String(evidence.rerankerSummary.newRank)
                    }
                  />
                  <KeyValue
                    label="Rank change"
                    value={
                      evidence.rerankerSummary.rankChange === null ||
                      evidence.rerankerSummary.rankChange === undefined
                        ? "not recorded"
                        : String(evidence.rerankerSummary.rankChange)
                    }
                  />
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
                <MissingText>
                  {evidence.graphUnavailableDetail ||
                    "No graph relationship recorded for this evidence"}
                </MissingText>
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
      <KeyValue
        label="Document"
        value={evidence.documentName || evidence.documentId || "Document link not recorded"}
      />
      <KeyValue label="Runtime profile" value={evidence.runtimeProfileId || "Not recorded"} />
      <KeyValue
        label="Source location"
        value={
          evidence.sourceLocation
            ? summarizeValue(evidence.sourceLocation)
            : "Source location not recorded"
        }
      />
      <KeyValue label="Quality" value={evidence.qualityStatus || "Default quality policy"} />
      <KeyValue
        label="Parser warnings"
        value={
          evidence.parserWarnings?.length
            ? `${evidence.parserWarnings.length} recorded`
            : "No parser warnings for this evidence"
        }
      />
      <KeyValue
        label="Reranker"
        value={
          evidence.rerankerSummary
            ? [
                evidence.rerankerSummary.status,
                evidence.rerankerSummary.provider,
                evidence.rerankerSummary.model,
                evidence.rerankerSummary.note,
              ]
                .filter(Boolean)
                .join(" · ")
            : "Reranker context not recorded"
        }
      />
      <KeyValue
        label="Graph"
        value={
          evidence.relationshipRefs?.length
            ? `${evidence.relationshipRefs.length} relationship refs`
            : evidence.graphUnavailableDetail || "No graph relationship recorded for this evidence"
        }
      />
    </div>
  );
}

function ArchitectureKeyValues({ values }: { values: Array<[string, string | undefined]> }) {
  const visibleValues = values.map(([label, value]) => [label, value || "not recorded"] as const);
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-2">
      {visibleValues.map(([label, value]) => (
        <KeyValue key={label} label={label} value={value} />
      ))}
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

function ReasonList({ label, values }: { label: string; values?: string[] }) {
  return values?.length ? (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <List values={values} />
    </div>
  ) : null;
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
        action.enabled ? (
          <Button
            key={action.label}
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              onClose();
              navigateTo(action.path, onNavigate);
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

function navigateTo(path: string, onNavigate?: (path: string) => void) {
  if (onNavigate) {
    onNavigate(path);
    return;
  }
  window.history.pushState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function summarizeValue(value: Record<string, unknown> | string) {
  if (typeof value === "string") {
    return value;
  }
  if (value.label) {
    return String(value.label);
  }
  const candidates = [
    value.page,
    value.page_start === value.page_end ? undefined : value.page_start,
    value.page_end,
    value.page_number,
    value.line,
    value.line_start === value.line_end ? undefined : value.line_start,
    value.line_end,
    value.chunk_index,
    value.reference,
    value.source,
  ]
    .filter((item) => item !== undefined && item !== null && item !== "")
    .map(String);
  return candidates.length ? candidates.join(" · ") : JSON.stringify(value);
}

import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ChevronDown,
  Database,
  Eye,
  FileText,
  Loader2,
  RefreshCcw,
  Search,
  SlidersHorizontal,
  Wand2,
} from "lucide-react";

import { apiClient, DEFAULT_PARSER_MODE } from "../../api/client";
import type {
  ChunkOut,
  ChunkSearchIn,
  ChunkSearchOut,
  DocumentOut,
  IndexDocumentIn,
} from "../../api/generated";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { titleCase, toggleId } from "../../lib/utils";
import { DomainMetadataPanel } from "../domain-metadata/domain-metadata-panel";
import { EvidenceViewer, type NormalizedEvidence } from "../evidence/evidence-viewer";

const queryKeys = {
  documents: ["documents"],
  jobs: ["jobs"],
} as const;

interface SearchResult {
  filters: ChunkSearchIn;
  data: ChunkSearchOut;
}

interface SearchRequest {
  filters: ChunkSearchIn;
}

interface RetrievalExplain {
  query_reference?: string | null;
  matched_references?: string[];
  relationship_refs?: Record<string, string>;
  signals?: Array<{ name: string; value: number }>;
}

export function ChunkInspector() {
  const queryClient = useQueryClient();
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => apiClient.documents(),
  });
  const [queryText, setQueryText] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[] | null>(null);
  const [limit, setLimit] = useState(10);
  const [formError, setFormError] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [expandedChunkId, setExpandedChunkId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<NormalizedEvidence | null>(null);
  const [indexOptionsOverride, setIndexOptionsOverride] = useState<IndexDocumentIn | null>(null);
  const [metadataValid, setMetadataValid] = useState(true);
  const profilesQuery = useQuery({
    queryKey: ["domain-profiles"],
    queryFn: apiClient.domainProfiles,
  });

  const documents = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data?.items]);
  const defaultDocumentId = useMemo(
    () => (documents.find((document) => document.status === "succeeded") ?? documents[0])?.id,
    [documents],
  );
  const activeSelectedDocumentIds = useMemo(
    () => selectedDocumentIds ?? (defaultDocumentId ? [defaultDocumentId] : []),
    [defaultDocumentId, selectedDocumentIds],
  );
  const selectedDocuments = useMemo(
    () => documents.filter((document) => activeSelectedDocumentIds.includes(document.id)),
    [activeSelectedDocumentIds, documents],
  );
  const selectedDocumentNames = selectedDocuments.map((document) => document.filename).join(", ");
  const activeIndexOptions = indexOptionsOverride ??
    selectedDocuments[0]?.latest_index_options ?? {
      parser_mode: DEFAULT_PARSER_MODE,
      domain_metadata: { domain: "generic", document_type: "document", tags: [] },
    };

  const currentSearchFilters = useMemo(
    () => normalizeSearchFilters({ query: queryText.trim(), document_ids: activeSelectedDocumentIds, limit }),
    [activeSelectedDocumentIds, limit, queryText],
  );

  const searchChunks = useMutation({
    mutationFn: (request: SearchRequest) => apiClient.searchChunks(request.filters),
    onSuccess: (data, variables) => {
      setSearchResult({ filters: normalizeSearchFilters(variables.filters), data });
      setExpandedChunkId(null);
    },
  });
  const indexDocumentJob = useMutation({
    mutationFn: (documentId: string) => apiClient.createDocumentReindexJob(documentId, activeIndexOptions),
    onSuccess: () => {
      setSearchResult(null);
      setExpandedChunkId(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
    },
  });

  const activeSearchResult =
    searchResult && filtersEqual(searchResult.filters, currentSearchFilters)
      ? searchResult.data
      : null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (activeSelectedDocumentIds.length === 0) {
      setFormError("Select at least one document.");
      return;
    }
    setFormError("");
    searchChunks.mutate({ filters: currentSearchFilters });
  };

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex items-center gap-2">
              <Database className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
              <h2 className="truncate text-base font-semibold text-[#1f2933]">Chunk evidence table</h2>
            </div>
            <DocumentSelector
              documents={documents}
              selectedDocumentIds={activeSelectedDocumentIds}
              documentsQueryState={{
                isLoading: documentsQuery.isLoading,
                isError: documentsQuery.isError,
                errorMessage: documentsQuery.error?.message,
              }}
              onToggle={(document, checked) => {
                setSelectedDocumentIds((ids) =>
                  toggleId(ids ?? activeSelectedDocumentIds, document.id, checked),
                );
                setIndexOptionsOverride(checked ? document.latest_index_options ?? null : null);
              }}
            />
          </div>

          <form onSubmit={submit} className="grid min-w-0 flex-[1.4] gap-3 lg:grid-cols-[minmax(0,1fr)_88px_auto]">
            <label className="block min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Search reference, phrase, or question</span>
              <input
                className="h-11 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
                value={queryText}
                onChange={(event) => setQueryText(event.target.value)}
                placeholder="12:13"
              />
            </label>
            <label className="block min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Limit</span>
              <input
                type="number"
                min={1}
                max={100}
                className="h-11 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
              />
            </label>
            <div className="flex items-end gap-2">
              <Button type="submit" disabled={searchChunks.isPending || activeSelectedDocumentIds.length === 0}>
                {searchChunks.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Search className="h-4 w-4" aria-hidden="true" />
                )}
                Search
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void documentsQuery.refetch()}
                disabled={documentsQuery.isFetching}
                aria-label="Refresh documents"
              >
                {documentsQuery.isFetching ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                )}
              </Button>
            </div>
          </form>
        </div>

        <details className="mt-4 rounded-md border border-[#dce5e8] bg-[#f8fafb]">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-semibold text-[#24313a]">
            <span className="flex min-w-0 items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 shrink-0 text-[#176b87]" aria-hidden="true" />
              <span className="truncate">Index settings</span>
              <span className="truncate text-xs font-medium text-[#62717a]">
                MinerU strict, domain metadata, and custom JSON
              </span>
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 text-[#62717a]" aria-hidden="true" />
          </summary>
          <div className="grid gap-4 border-t border-[#dce5e8] p-3 lg:grid-cols-[minmax(0,1fr)_auto]">
            <DomainMetadataPanel
              profiles={profilesQuery.data?.items ?? []}
              value={activeIndexOptions}
              onChange={setIndexOptionsOverride}
              disabled={indexDocumentJob.isPending}
              onValidityChange={setMetadataValid}
            />
            <div className="flex flex-col justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                disabled={activeSelectedDocumentIds.length === 0 || indexDocumentJob.isPending || !metadataValid}
                onClick={() => {
                  const [documentId] = activeSelectedDocumentIds;
                  if (documentId) {
                    indexDocumentJob.mutate(documentId);
                  }
                }}
              >
                {indexDocumentJob.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Wand2 className="h-4 w-4" aria-hidden="true" />
                )}
                Index selected
              </Button>
              <p className="max-w-48 text-xs leading-5 text-[#62717a]">
                Indexing uses the first selected document. Search can inspect one or more documents.
              </p>
            </div>
          </div>
        </details>

        <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
          {formError ||
            indexDocumentJob.error?.message ||
            searchChunks.error?.message ||
            (indexDocumentJob.isSuccess ? `Index job queued: ${indexDocumentJob.data.job_id}` : "")}
        </p>
      </section>

      <section className="min-w-0 rounded-md border border-[#d6dde1] bg-white">
        <div className="flex flex-col gap-2 border-b border-[#d6dde1] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-[#1f2933]">Chunk results</h2>
            <p className="truncate text-sm text-[#62717a]">
              {selectedDocumentNames || "Select documents to inspect mirrored chunks and snapshots."}
            </p>
          </div>
          {activeSearchResult ? (
            <Badge>{activeSearchResult.items.length} result{activeSearchResult.items.length === 1 ? "" : "s"}</Badge>
          ) : null}
        </div>

        {searchChunks.isPending ? (
          <div className="p-4">
            <EmptyState icon={Loader2} title="Searching chunks" description="Ranking selected document chunks." />
          </div>
        ) : activeSearchResult?.items.length ? (
          <ChunkEvidenceTable
            chunks={activeSearchResult.items}
            expandedChunkId={expandedChunkId}
            onToggleExpanded={(chunkId) => setExpandedChunkId((current) => (current === chunkId ? null : chunkId))}
            onInspectEvidence={(chunk, retrievalExplain) =>
              setSelectedEvidence(normalizeChunkEvidence(chunk, retrievalExplain))
            }
          />
        ) : activeSearchResult ? (
          <div className="p-4">
            <EmptyState icon={Search} title="No mirrored chunks matched" description="Try another question or index selected documents." />
          </div>
        ) : (
          <div className="p-4">
            <EmptyState
              icon={Database}
              title="Inspect mirrored chunks"
              description="Select a document, search by reference or phrase, then expand a row for evidence."
            />
          </div>
        )}
      </section>

      <EvidenceViewer
        evidence={selectedEvidence}
        open={selectedEvidence !== null}
        onClose={() => setSelectedEvidence(null)}
      />
    </div>
  );
}

function DocumentSelector({
  documents,
  selectedDocumentIds,
  documentsQueryState,
  onToggle,
}: {
  documents: DocumentOut[];
  selectedDocumentIds: string[];
  documentsQueryState: { isLoading: boolean; isError: boolean; errorMessage?: string };
  onToggle: (document: DocumentOut, checked: boolean) => void;
}) {
  if (documentsQueryState.isLoading) {
    return <SmallState icon={Loader2} text="Loading documents" />;
  }
  if (documentsQueryState.isError) {
    return <SmallState icon={AlertCircle} text={documentsQueryState.errorMessage ?? "Documents unavailable"} />;
  }
  if (!documents.length) {
    return <SmallState icon={FileText} text="No documents uploaded" />;
  }

  return (
    <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Documents">
      {documents.map((document) => {
        const selected = selectedDocumentIds.includes(document.id);
        return (
          <label
            key={document.id}
            className={[
              "flex min-h-11 max-w-80 shrink-0 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-sm",
              selected
                ? "border-[#0f766e] bg-[#e3f3f1] text-[#0c524d]"
                : "border-[#e1e7ea] bg-[#f8fafb] text-[#24313a]",
            ].join(" ")}
          >
            <input
              type="checkbox"
              className="h-4 w-4 accent-[#0f766e]"
              checked={selected}
              onChange={(event) => onToggle(document, event.target.checked)}
            />
            <span className="min-w-0">
              <span className="block truncate font-semibold">{document.filename}</span>
              <span className="block truncate text-xs text-[#62717a]">{titleCase(document.status)}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}

function ChunkEvidenceTable({
  chunks,
  expandedChunkId,
  onToggleExpanded,
  onInspectEvidence,
}: {
  chunks: ChunkOut[];
  expandedChunkId: string | null;
  onToggleExpanded: (chunkId: string) => void;
  onInspectEvidence: (chunk: ChunkOut, retrievalExplain: RetrievalExplain | null) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] table-fixed text-left text-sm">
        <thead className="border-b border-[#d6dde1] bg-[#f8fafb] text-xs uppercase text-[#62717a]">
          <tr>
            <th className="w-[18%] px-4 py-3 font-semibold">Reference</th>
            <th className="w-[12%] px-4 py-3 font-semibold">Score</th>
            <th className="w-[22%] px-4 py-3 font-semibold">Source</th>
            <th className="w-[30%] px-4 py-3 font-semibold">Signals</th>
            <th className="w-[18%] px-4 py-3 text-right font-semibold">Actions</th>
          </tr>
        </thead>
        <tbody>
          {chunks.map((chunk) => {
            const retrievalExplain = getRetrievalExplain(chunk.metadata);
            const referenceLabel = primaryReferenceLabel(retrievalExplain, chunk);
            const expanded = expandedChunkId === chunk.id;
            return (
              <FragmentRow
                key={chunk.id}
                chunk={chunk}
                retrievalExplain={retrievalExplain}
                referenceLabel={referenceLabel}
                expanded={expanded}
                onToggleExpanded={() => onToggleExpanded(chunk.id)}
                onInspectEvidence={() => onInspectEvidence(chunk, retrievalExplain)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FragmentRow({
  chunk,
  retrievalExplain,
  referenceLabel,
  expanded,
  onToggleExpanded,
  onInspectEvidence,
}: {
  chunk: ChunkOut;
  retrievalExplain: RetrievalExplain | null;
  referenceLabel: string;
  expanded: boolean;
  onToggleExpanded: () => void;
  onInspectEvidence: () => void;
}) {
  const sourceSummary = summarizeSourceLocation(chunk.source_location);
  const signalSummary = summarizeSignals(retrievalExplain);

  return (
    <>
      <tr className="border-b border-[#edf1f3] align-top hover:bg-[#fbfdfd]">
        <td className="px-4 py-3">
          <p className="font-mono text-sm font-semibold text-[#18211f]">{referenceLabel}</p>
          <p className="mt-1 truncate text-xs text-[#62717a]">{shortId(chunk.id)}</p>
        </td>
        <td className="px-4 py-3">
          <Badge>score {formatValue(chunk.metadata.score)}</Badge>
        </td>
        <td className="px-4 py-3">
          <p className="truncate font-mono text-xs text-[#33413e]">{sourceSummary.primary}</p>
          <p className="mt-1 truncate text-xs text-[#62717a]">{sourceSummary.secondary}</p>
        </td>
        <td className="px-4 py-3">
          <div className="flex flex-wrap gap-1.5">
            {signalSummary.map((signal) => (
              <Badge key={signal}>{signal}</Badge>
            ))}
          </div>
        </td>
        <td className="px-4 py-3">
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={onToggleExpanded}>
              <ChevronDown
                className={["h-4 w-4 transition-transform", expanded ? "rotate-180" : ""].join(" ")}
                aria-hidden="true"
              />
              {expanded ? "Hide" : "Preview"}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={onInspectEvidence}>
              <Eye className="h-4 w-4" aria-hidden="true" />
              Inspect
            </Button>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-[#d6dde1] bg-[#fbfdfd]">
          <td colSpan={5} className="px-4 py-4">
            <ChunkPreview chunk={chunk} retrievalExplain={retrievalExplain} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

function ChunkPreview({
  chunk,
  retrievalExplain,
}: {
  chunk: ChunkOut;
  retrievalExplain: RetrievalExplain | null;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
      <div className="min-w-0">
        <p className="whitespace-pre-wrap text-sm leading-6 text-[#24313a]">{chunk.text}</p>
        {retrievalExplain ? <RetrievalExplainPanel explain={retrievalExplain} /> : null}
      </div>
      <div className="grid content-start gap-2">
        <MetadataSummary chunk={chunk} />
        <CollapsibleJsonBlock
          title="Source location"
          summary={summarizeObject(chunk.source_location)}
          value={chunk.source_location}
        />
        <CollapsibleJsonBlock
          title="Snapshot metadata"
          summary={metadataSummary(chunk.metadata)}
          value={chunk.metadata}
        />
      </div>
    </div>
  );
}

function MetadataSummary({ chunk }: { chunk: ChunkOut }) {
  return (
    <div className="rounded-md border border-[#dce5e8] bg-white p-3 text-xs text-[#3a4a53]">
      <div className="grid gap-2 sm:grid-cols-2">
        <SummaryLine label="Profile" value={chunk.runtime_profile_id ?? "n/a"} />
        <SummaryLine label="Content" value={chunk.content_type} />
        <SummaryLine label="Snapshot" value={metadataValue(chunk.metadata, ["mirrored_snapshot"], "false")} />
        <SummaryLine label="Domain" value={metadataValue(chunk.metadata, ["domain_metadata", "domain"], "generic")} />
        <SummaryLine label="Materialization" value={metadataValue(chunk.metadata, ["materialization_hint"], "not recorded")} />
        <SummaryLine label="Layout group" value={metadataValue(chunk.metadata, ["layout_group_id"], "not recorded")} />
        <SummaryLine label="Layout role" value={metadataValue(chunk.metadata, ["layout_role"], "not recorded")} />
        <SummaryLine label="Reading order" value={metadataValue(chunk.metadata, ["reading_order"], "not recorded")} />
        <SummaryLine label="Parent" value={metadataValue(chunk.metadata, ["parent_chunk_id"], "not recorded")} />
        <SummaryLine label="Previous" value={metadataValue(chunk.metadata, ["previous_chunk_id"], "not recorded")} />
        <SummaryLine label="Next" value={metadataValue(chunk.metadata, ["next_chunk_id"], "not recorded")} />
      </div>
    </div>
  );
}

function SummaryLine({ label, value }: { label: string; value: string }) {
  return (
    <p className="min-w-0">
      <span className="font-semibold uppercase text-[#62717a]">{label}</span>{" "}
      <span className="break-words font-mono text-[#18211f]">{value}</span>
    </p>
  );
}

function RetrievalExplainPanel({ explain }: { explain: RetrievalExplain }) {
  const relationshipRefs = Object.entries(explain.relationship_refs ?? {});
  const signals = explain.signals ?? [];

  return (
    <section
      aria-label="Retrieval explain"
      className="mt-4 rounded-md border border-[#dce5e8] bg-white p-3 text-xs text-[#3a4a53]"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h4 className="font-semibold uppercase text-[#62717a]">Retrieval explain</h4>
        {explain.query_reference ? <Badge>query {explain.query_reference}</Badge> : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {explain.matched_references?.length ? (
          <CompactExplainList title="Matched references" values={explain.matched_references} />
        ) : null}
        {relationshipRefs.length ? (
          <CompactExplainList
            title="Relationship refs"
            values={relationshipRefs.map(([name, reference]) => `${name}: ${reference}`)}
          />
        ) : null}
        {signals.length ? (
          <CompactExplainList
            title="Signals"
            values={signals.map((signal) => `${signal.name}: ${formatValue(signal.value)}`)}
          />
        ) : null}
      </div>
    </section>
  );
}

function CompactExplainList({ title, values }: { title: string; values: string[] }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 font-semibold text-[#62717a]">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span
            key={value}
            className="min-w-0 max-w-full break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] px-2 py-1 text-[#24313a]"
          >
            {value}
          </span>
        ))}
      </div>
    </div>
  );
}

function CollapsibleJsonBlock({
  title,
  summary,
  value,
}: {
  title: string;
  summary: string;
  value: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-md border border-[#dce5e8] bg-white">
      <button
        type="button"
        className="flex min-h-10 w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        <span className="min-w-0">
          <span className="block font-semibold uppercase text-[#62717a]">{title}</span>
          <span className="block truncate text-[#3a4a53]">{summary}</span>
        </span>
        <ChevronDown
          className={["h-4 w-4 shrink-0 text-[#62717a] transition-transform", open ? "rotate-180" : ""].join(" ")}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-[#e1e7ea] bg-[#f8fafb] p-3 font-mono text-xs leading-5 text-[#3a4a53]">
          {JSON.stringify(value, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
      {children}
    </span>
  );
}

function SmallState({ icon: Icon, text }: { icon: typeof AlertCircle; text: string }) {
  return (
    <div className="flex min-h-11 items-center gap-2 rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-3 text-sm text-[#62717a]">
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 truncate">{text}</span>
    </div>
  );
}

function normalizeChunkEvidence(
  chunk: ChunkOut,
  retrievalExplain: RetrievalExplain | null,
): NormalizedEvidence {
  const relationshipRefs = Object.entries(retrievalExplain?.relationship_refs ?? {}).map(
    ([name, reference]) => `${name}: ${reference}`,
  );
  const retrievalReasons = [
    ...(retrievalExplain?.matched_references ?? []).map((reference) => `matched ${reference}`),
    ...(retrievalExplain?.signals ?? []).map(
      (signal) => `${signal.name}: ${formatValue(signal.value)}`,
    ),
  ];
  const parserWarnings = stringArray(
    metadataAt(chunk.metadata, ["parser_quality_warning_codes"]) ??
      metadataAt(chunk.metadata, ["parser_warnings"]),
  );

  return {
    id: chunk.id,
    kind: "chunk",
    documentId: chunk.document_id,
    runtimeProfileId: chunk.runtime_profile_id,
    text: chunk.text,
    sourceLocation: chunk.source_location,
    metadata: chunk.metadata,
    parserWarnings,
    qualityStatus:
      textMetadata(chunk.metadata, ["quality_action_policy"]) ??
      textMetadata(chunk.metadata, ["quality_status"]) ??
      null,
    retrievalReasons,
    relationshipRefs,
    graphUnavailableDetail:
      textMetadata(chunk.metadata, ["graph_unavailable_detail"]) ??
      textMetadata(chunk.metadata, ["graphUnavailableDetail"]) ??
      null,
    architecture: {
      domain: {
        domain: metadataValue(chunk.metadata, ["domain_metadata", "domain"], "not recorded"),
        materializationHint: metadataValue(chunk.metadata, ["materialization_hint"], "not recorded"),
        qualityPolicy: metadataValue(chunk.metadata, ["quality_action_policy"], "not recorded"),
      },
      layout: {
        layoutGroupId: metadataValue(chunk.metadata, ["layout_group_id"], "not recorded"),
        layoutRole: metadataValue(chunk.metadata, ["layout_role"], "not recorded"),
        readingOrder: metadataValue(chunk.metadata, ["reading_order"], "not recorded"),
      },
      context: {
        parentChunkId: metadataValue(chunk.metadata, ["parent_chunk_id"], "not recorded"),
        previousChunkId: metadataValue(chunk.metadata, ["previous_chunk_id"], "not recorded"),
        nextChunkId: metadataValue(chunk.metadata, ["next_chunk_id"], "not recorded"),
      },
    },
    raw: chunk,
    routeLinks: {
      documents: Boolean(chunk.document_id),
      chunks: true,
      query: true,
      graph: relationshipRefs.length > 0,
      diagnostics: true,
      documentUnavailableLabel: "Document link not recorded",
    },
  };
}

function primaryReferenceLabel(retrievalExplain: RetrievalExplain | null, chunk: ChunkOut) {
  return (
    retrievalExplain?.query_reference ??
    retrievalExplain?.matched_references?.[0] ??
    metadataValue(chunk.metadata, ["canonical_reference_unit", "reference"], "n/a")
  );
}

function summarizeSignals(retrievalExplain: RetrievalExplain | null) {
  const signals = retrievalExplain?.signals ?? [];
  if (!signals.length) {
    return ["no signals"];
  }
  return signals.slice(0, 4).map((signal) => `${signal.name} ${formatValue(signal.value)}`);
}

function summarizeSourceLocation(sourceLocation: Record<string, unknown>) {
  const pageStart = sourceLocation.page_start;
  const pageEnd = sourceLocation.page_end;
  const pageLabel =
    typeof pageStart === "number"
      ? typeof pageEnd === "number" && pageEnd !== pageStart
        ? `pages ${pageStart}-${pageEnd}`
        : `page ${pageStart}`
      : "page n/a";
  const artifact =
    typeof sourceLocation.artifact === "string" && sourceLocation.artifact
      ? sourceLocation.artifact
      : "artifact not recorded";
  return {
    primary: pageLabel,
    secondary: artifact,
  };
}

function summarizeObject(value: Record<string, unknown>) {
  const keys = Object.keys(value);
  return keys.length ? `${keys.length} field${keys.length === 1 ? "" : "s"}: ${keys.slice(0, 3).join(", ")}` : "No fields";
}

function metadataSummary(metadata: Record<string, unknown>) {
  const keys = Object.keys(metadata);
  const relatedArtifacts = metadataAt(metadata, ["parser_metadata", "related_artifacts"]);
  const artifactCount = Array.isArray(relatedArtifacts) ? `, ${relatedArtifacts.length} artifacts` : "";
  return `${keys.length} top-level field${keys.length === 1 ? "" : "s"}${artifactCount}`;
}

function formatValue(value: unknown) {
  if (typeof value === "number") {
    return value.toFixed(2);
  }
  if (typeof value === "string") {
    return value;
  }
  return "n/a";
}

function shortId(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function metadataValue(metadata: Record<string, unknown>, path: string[], fallback: string) {
  let current: unknown = metadata;
  for (const segment of path) {
    if (typeof current !== "object" || current === null || !(segment in current)) {
      return fallback;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  if (typeof current === "string" && current) {
    return current;
  }
  if (typeof current === "boolean") {
    return current ? "true" : "false";
  }
  if (typeof current === "number") {
    return String(current);
  }
  return fallback;
}

function metadataAt(metadata: Record<string, unknown>, path: string[]) {
  let current: unknown = metadata;
  for (const segment of path) {
    if (typeof current !== "object" || current === null || !(segment in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function textMetadata(metadata: Record<string, unknown>, path: string[]) {
  const value = metadataAt(metadata, path);
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function getRetrievalExplain(metadata: Record<string, unknown>): RetrievalExplain | null {
  const explain = metadata.retrieval_explain;
  if (typeof explain !== "object" || explain === null || Array.isArray(explain)) {
    return null;
  }

  return explain as RetrievalExplain;
}

function normalizeSearchFilters(filters: ChunkSearchIn): ChunkSearchIn {
  return {
    query: filters.query.trim(),
    document_ids: [...filters.document_ids],
    limit: filters.limit,
  };
}

function filtersEqual(left: ChunkSearchIn, right: ChunkSearchIn) {
  return stringifySearchFilters(left) === stringifySearchFilters(right);
}

function stringifySearchFilters(filters: ChunkSearchIn) {
  return JSON.stringify(normalizeSearchFilters(filters));
}

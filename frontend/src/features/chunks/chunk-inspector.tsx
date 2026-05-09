import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Database,
  FileText,
  Loader2,
  RefreshCcw,
  Search,
  Wand2,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type {
  ChunkOut,
  ChunkSearchIn,
  ChunkSearchOut,
  IndexDocumentIn,
} from "../../api/generated";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { titleCase } from "../../lib/utils";
import { DomainMetadataPanel } from "../domain-metadata/domain-metadata-panel";

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
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const [queryText, setQueryText] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [limit, setLimit] = useState(10);
  const [formError, setFormError] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: "local_fallback",
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const [metadataValid, setMetadataValid] = useState(true);
  const profilesQuery = useQuery({
    queryKey: ["domain-profiles"],
    queryFn: apiClient.domainProfiles,
  });

  const currentSearchFilters = useMemo(
    () => normalizeSearchFilters({ query: queryText.trim(), document_ids: selectedDocumentIds, limit }),
    [limit, queryText, selectedDocumentIds],
  );

  const searchChunks = useMutation({
    mutationFn: (request: SearchRequest) => apiClient.searchChunks(request.filters),
    onSuccess: (data, variables) => {
      setSearchResult({ filters: normalizeSearchFilters(variables.filters), data });
    },
  });
  const indexDocumentJob = useMutation({
    mutationFn: (documentId: string) => apiClient.createIndexDocumentJob(documentId, indexOptions),
    onSuccess: () => {
      setSearchResult(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
    },
  });

  const selectedDocuments = useMemo(
    () => (documentsQuery.data?.items ?? []).filter((document) => selectedDocumentIds.includes(document.id)),
    [documentsQuery.data?.items, selectedDocumentIds],
  );

  const activeSearchResult =
    searchResult && filtersEqual(searchResult.filters, currentSearchFilters)
      ? searchResult.data
      : null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selectedDocumentIds.length === 0) {
      setFormError("Select at least one document to avoid searching every chunk.");
      return;
    }
    setFormError("");
    searchChunks.mutate({ filters: currentSearchFilters });
  };

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
      <aside className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
        <div className="mb-5 flex items-center gap-2">
          <Database className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Chunk controls</h2>
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium text-[#3a4a53]">Documents</p>
          <div className="max-h-72 space-y-2 overflow-auto pr-1">
            {documentsQuery.isLoading ? (
              <SmallState icon={Loader2} text="Loading documents" />
            ) : documentsQuery.isError ? (
              <SmallState icon={AlertCircle} text={documentsQuery.error.message} />
            ) : documentsQuery.data?.items.length ? (
              documentsQuery.data.items.map((document) => (
                <div
                  key={document.id}
                  className="flex items-start gap-3 rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-sm"
                >
                  <label className="flex min-w-0 flex-1 cursor-pointer items-start gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 accent-[#176b87]"
                      checked={selectedDocumentIds.includes(document.id)}
                      onChange={(event) =>
                        setSelectedDocumentIds((ids) => toggleId(ids, document.id, event.target.checked))
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-[#24313a]">{document.filename}</span>
                      <span className="block truncate text-xs text-[#62717a]">{titleCase(document.status)}</span>
                    </span>
                  </label>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="shrink-0"
                    disabled={indexDocumentJob.isPending || !metadataValid}
                    onClick={(event) => {
                      event.preventDefault();
                      indexDocumentJob.mutate(document.id);
                    }}
                  >
                    {indexDocumentJob.isPending && indexDocumentJob.variables === document.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Wand2 className="h-4 w-4" aria-hidden="true" />
                    )}
                    Index
                  </Button>
                </div>
              ))
            ) : (
              <SmallState icon={FileText} text="No documents uploaded" />
            )}
          </div>
        </div>

        <div className="mt-5">
          <DomainMetadataPanel
            profiles={profilesQuery.data?.items ?? []}
            value={indexOptions}
            onChange={setIndexOptions}
            disabled={indexDocumentJob.isPending}
            onValidityChange={setMetadataValid}
          />
        </div>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="block min-w-0 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block truncate">Question or search text</span>
            <textarea
              className="min-h-24 w-full resize-y rounded-md border border-[#cfd8dd] bg-white px-3 py-2 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              placeholder="Search within selected document chunks."
            />
          </label>

          <div className="flex items-end gap-3">
            <label className="min-w-0 flex-1 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Limit</span>
              <input
                type="number"
                min={1}
                max={100}
                className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
              />
            </label>
            <Button type="submit" disabled={searchChunks.isPending || selectedDocumentIds.length === 0}>
              {searchChunks.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Search className="h-4 w-4" aria-hidden="true" />
              )}
              Search
            </Button>
          </div>
        </form>

        <p className="mt-4 min-h-5 text-sm text-[#62717a]" role="status">
          {formError ||
            indexDocumentJob.error?.message ||
            searchChunks.error?.message ||
            (indexDocumentJob.isSuccess ? `Index job queued: ${indexDocumentJob.data.id}` : "")}
        </p>
      </aside>

      <section className="min-w-0">
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-[#1f2933]">Chunk results</h2>
            <p className="truncate text-sm text-[#62717a]">
              {selectedDocuments.length
                ? selectedDocuments.map((document) => document.filename).join(", ")
                : "Select documents to inspect mirrored chunks and snapshots."}
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => void documentsQuery.refetch()}
            disabled={documentsQuery.isFetching}
          >
            {documentsQuery.isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            )}
            Refresh
          </Button>
        </div>

        {searchChunks.isPending ? (
          <EmptyState icon={Loader2} title="Searching chunks" description="Ranking selected document chunks." />
        ) : activeSearchResult?.items.length ? (
          <div className="grid gap-3">
            {activeSearchResult.items.map((chunk) => (
              <ChunkCard key={chunk.id} chunk={chunk} />
            ))}
          </div>
        ) : activeSearchResult ? (
          <EmptyState icon={Search} title="No mirrored chunks matched" description="Try another question or index selected documents." />
        ) : (
          <EmptyState
            icon={Database}
            title="Inspect mirrored chunks"
            description="Index documents when needed, then search mirrored snapshots."
          />
        )}
      </section>
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: ChunkOut }) {
  const retrievalExplain = getRetrievalExplain(chunk.metadata);

  return (
    <article className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-[#1f2933]">{chunk.id}</h3>
          <p className="truncate text-xs text-[#62717a]">{chunk.document_id}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Badge>score {formatValue(chunk.metadata.score)}</Badge>
          <Badge>profile {chunk.runtime_profile_id ?? "n/a"}</Badge>
          <Badge>{chunk.content_type}</Badge>
          <Badge>snapshot {metadataValue(chunk.metadata, ["mirrored_snapshot"], "false")}</Badge>
          <Badge>{metadataValue(chunk.metadata, ["parser_metadata", "backend"], "fallback")}</Badge>
          <Badge>{metadataValue(chunk.metadata, ["domain_metadata", "domain"], "generic")}</Badge>
        </div>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[#24313a]">{chunk.text}</p>
      {retrievalExplain ? <RetrievalExplainPanel explain={retrievalExplain} /> : null}
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <JsonBlock title="Source location" value={chunk.source_location} />
        <JsonBlock title="Snapshot metadata" value={chunk.metadata} />
      </div>
    </article>
  );
}

function RetrievalExplainPanel({ explain }: { explain: RetrievalExplain }) {
  const relationshipRefs = Object.entries(explain.relationship_refs ?? {});
  const signals = explain.signals ?? [];

  return (
    <section
      aria-label="Retrieval explain"
      className="mt-4 rounded-md border border-[#dce5e8] bg-[#f8fafb] p-3 text-xs text-[#3a4a53]"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h4 className="font-semibold uppercase text-[#62717a]">Retrieval explain</h4>
        {explain.query_reference ? <Badge>query {explain.query_reference}</Badge> : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
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
            className="min-w-0 max-w-full break-words rounded-md border border-[#e1e7ea] bg-white px-2 py-1 text-[#24313a]"
          >
            {value}
          </span>
        ))}
      </div>
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

function JsonBlock({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase text-[#62717a]">{title}</h4>
      <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function SmallState({ icon: Icon, text }: { icon: typeof AlertCircle; text: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-3 text-sm text-[#62717a]">
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 truncate">{text}</span>
    </div>
  );
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
  return fallback;
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

function toggleId(ids: string[], id: string, checked: boolean) {
  if (checked) {
    return ids.includes(id) ? ids : [...ids, id];
  }
  return ids.filter((existingId) => existingId !== id);
}

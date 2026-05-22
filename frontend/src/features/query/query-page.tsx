import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckSquare,
  ChevronDown,
  FileText,
  GitBranch,
  Loader2,
  MessageSquareText,
  PlayCircle,
  RefreshCcw,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { HybridSearchWeights, RunOut, VariantOut } from "../../api/generated";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { titleCase, toggleId } from "../../lib/utils";
import {
  EvidenceViewer,
  type EvidenceRerankerSummary,
  type NormalizedEvidence,
} from "../evidence/evidence-viewer";
import { QueryPathwayViewer } from "./query-pathway-viewer";
import { SearchTuningPanel } from "./search-tuning-panel";
import { buildThreePillarTrace, type ThreePillarTraceSummary } from "./three-pillar-trace";

const queryKeys = {
  documents: ["documents"],
  variants: ["variants"],
  runs: ["runs"],
  simulateRetrieval: (
    query: string,
    documentIds: string[],
    variantIds: string[],
    limit: number,
    weights: HybridSearchWeights,
  ) => ["query", "simulate-retrieval", query, documentIds, variantIds, limit, weights],
} as const;

const defaultSearchWeights: HybridSearchWeights = {
  reference_exact: 1,
  term_coverage: 1,
  metadata_boost: 1,
  semantic_density: 1,
};

type QueryResponseMode = "fast" | "full";

export function QueryPage() {
  const queryClient = useQueryClient();
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: () => apiClient.documents() });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: () => apiClient.variants() });
  const [queryText, setQueryText] = useState("");
  const [limit, setLimit] = useState(8);
  const [responseMode, setResponseMode] = useState<QueryResponseMode>("fast");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[] | null>(null);
  const [selectedVariantIds, setSelectedVariantIds] = useState<string[] | null>(null);
  const [answerBudgetMs, setAnswerBudgetMs] = useState(3000);
  const [responseBudgetMs, setResponseBudgetMs] = useState(15000);
  const [formError, setFormError] = useState("");
  const [searchTuningOpen, setSearchTuningOpen] = useState(false);
  const [searchWeights, setSearchWeights] = useState<HybridSearchWeights>(defaultSearchWeights);
  const [hasCustomSearchWeights, setHasCustomSearchWeights] = useState(false);

  const runQuery = useMutation({
    mutationFn: apiClient.query,
    onSuccess: () => {
      setFormError("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs });
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!queryText.trim()) {
      setFormError("Enter a query before running.");
      return;
    }
    if (activeSelectedDocumentIds.length === 0) {
      setFormError("Select at least one document so the run is scoped.");
      return;
    }
    if (activeSelectedVariantIds.length === 0) {
      setFormError("Select at least one variant.");
      return;
    }
    runQuery.mutate({
      query: queryText.trim(),
      document_ids: activeSelectedDocumentIds,
      variant_ids: activeSelectedVariantIds,
      limit,
      response_mode: responseMode,
      answer_budget_ms: responseMode === "fast" ? answerBudgetMs : null,
      response_budget_ms: responseMode === "fast" ? responseBudgetMs : null,
      search_weights: hasCustomSearchWeights ? searchWeights : null,
    });
  };

  const documents = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data?.items]);
  const variants = useMemo(() => variantsQuery.data?.items ?? [], [variantsQuery.data?.items]);
  const defaultDocumentId = useMemo(
    () => (documents.find((document) => document.status === "succeeded") ?? documents[0])?.id,
    [documents],
  );
  const defaultVariantId = useMemo(() => variants[0]?.id, [variants]);
  const defaultDocumentIds = useMemo(
    () => (defaultDocumentId ? [defaultDocumentId] : []),
    [defaultDocumentId],
  );
  const defaultVariantIds = useMemo(() => (defaultVariantId ? [defaultVariantId] : []), [defaultVariantId]);
  const activeSelectedDocumentIds = selectedDocumentIds ?? defaultDocumentIds;
  const activeSelectedVariantIds = selectedVariantIds ?? defaultVariantIds;
  const selectedDocumentNames = useMemo(
    () =>
      documents
        .filter((document) => activeSelectedDocumentIds.includes(document.id))
        .map((document) => document.filename)
        .join(", "),
    [activeSelectedDocumentIds, documents],
  );
  const selectedVariantNames = useMemo(
    () =>
      variants
        .filter((variant) => activeSelectedVariantIds.includes(variant.id))
        .map((variant) => variant.name)
        .join(", "),
    [activeSelectedVariantIds, variants],
  );
  const variantById = useMemo(
    () => new Map<string, VariantOut>(variants.map((variant) => [variant.id, variant])),
    [variants],
  );

  const isLoadingChoices = documentsQuery.isLoading || variantsQuery.isLoading;
  const choiceError = documentsQuery.error?.message ?? variantsQuery.error?.message;
  const canRun =
    !runQuery.isPending &&
    !isLoadingChoices &&
    queryText.trim().length > 0 &&
    activeSelectedDocumentIds.length > 0 &&
    activeSelectedVariantIds.length > 0;
  const canTune = !isLoadingChoices && queryText.trim().length > 0 && activeSelectedDocumentIds.length > 0;
  const simulationQuery = useQuery({
    queryKey: queryKeys.simulateRetrieval(
      queryText.trim(),
      activeSelectedDocumentIds,
      activeSelectedVariantIds,
      limit,
      searchWeights,
    ),
    queryFn: () =>
      apiClient.simulateRetrieval({
        query: queryText.trim(),
        document_ids: activeSelectedDocumentIds,
        variant_ids: activeSelectedVariantIds,
        limit,
        search_weights: hasCustomSearchWeights ? searchWeights : null,
      }),
    enabled: searchTuningOpen && canTune,
  });

  return (
    <div className="mx-auto max-w-7xl space-y-3">
      <form onSubmit={submit} className="rounded-md border border-[#d6dde1] bg-white p-3 sm:p-4">
        <div className="mb-3 flex items-center gap-2">
          <MessageSquareText className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">RAG query workbench</h2>
        </div>

        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(220px,0.3fr)_minmax(220px,0.3fr)] xl:items-end">
          <label className="block min-w-0 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1 block truncate">Question, reference, or claim</span>
            <input
              className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              disabled={runQuery.isPending}
              placeholder="Ask a focused question against selected documents."
            />
          </label>
          <ChoicePanel
            icon={FileText}
            title="Documents"
            selectedSummary={selectedDocumentNames || "Select documents"}
            isLoading={documentsQuery.isLoading}
            error={documentsQuery.error?.message}
            empty="Upload documents before querying."
          >
            {documents.map((document) => (
              <CheckboxRow
                key={document.id}
                label={document.filename}
                detail={`${titleCase(document.status)} · ${document.content_type}`}
                checked={activeSelectedDocumentIds.includes(document.id)}
                onChange={(checked) =>
                  setSelectedDocumentIds((ids) =>
                    toggleId(ids ?? activeSelectedDocumentIds, document.id, checked),
                  )
                }
              />
            ))}
          </ChoicePanel>

          <ChoicePanel
            icon={SlidersHorizontal}
            title="Variants"
            selectedSummary={selectedVariantNames || "Select variants"}
            isLoading={variantsQuery.isLoading}
            error={variantsQuery.error?.message}
            empty="Create a variant before querying."
          >
            {variants.map((variant) => (
              <CheckboxRow
                key={variant.id}
                label={variant.name}
                detail={titleCase(variant.preset)}
                checked={activeSelectedVariantIds.includes(variant.id)}
                onChange={(checked) =>
                  setSelectedVariantIds((ids) =>
                    toggleId(ids ?? activeSelectedVariantIds, variant.id, checked),
                  )
                }
              />
            ))}
          </ChoicePanel>
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="w-24 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1 block truncate">Limit</span>
            <input
              type="number"
              min={1}
              max={50}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="h-9 w-full rounded-md border border-[#cfd8dd] bg-white px-2 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            />
          </label>
          <div className="w-56">
            <span className="mb-1 block text-sm font-medium text-[#3a4a53]">Answer mode</span>
            <div
              className="grid h-9 grid-cols-2 rounded-md border border-[#cfd8dd] bg-[#f8fafb] p-1"
              role="group"
              aria-label="Answer mode"
            >
              {(["fast", "full"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={responseMode === mode}
                  className={`rounded px-2 text-xs font-medium ${
                    responseMode === mode
                      ? "bg-white text-[#174657] shadow-sm"
                      : "text-[#62717a] hover:text-[#174657]"
                  }`}
                  onClick={() => setResponseMode(mode)}
                  disabled={runQuery.isPending}
                >
                  {mode === "fast" ? "Fast" : "Full"}
                </button>
              ))}
            </div>
          </div>
          <div className="ml-auto flex items-end gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={documentsQuery.isFetching || variantsQuery.isFetching}
              onClick={() => {
                void documentsQuery.refetch();
                void variantsQuery.refetch();
              }}
              aria-label="Refresh documents and variants"
            >
              {documentsQuery.isFetching || variantsQuery.isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              )}
            </Button>
            <Button type="button" variant="secondary" disabled={!canTune} onClick={() => setSearchTuningOpen(true)}>
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              Tune retrieval
            </Button>
            <Button type="submit" disabled={!canRun}>
              {runQuery.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <PlayCircle className="h-4 w-4" aria-hidden="true" />
              )}
              Run
            </Button>
          </div>
        </div>

        <details open className="mt-3 rounded-md border border-[#dce5e8] bg-[#f8fafb]">
          <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 py-1.5 text-sm font-semibold text-[#24313a]">
            <span className="flex min-w-0 items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 shrink-0 text-[#176b87]" aria-hidden="true" />
              <span className="truncate">Retrieval tuning</span>
              <span className="truncate text-xs font-medium text-[#62717a]">
                Search weights, preview ranking, and fast-mode budgets
              </span>
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 text-[#62717a]" aria-hidden="true" />
          </summary>
          <div className="grid gap-3 border-t border-[#dce5e8] p-3 lg:grid-cols-[minmax(0,1fr)_auto]">
            <SearchWeightsSummary weights={searchWeights} custom={hasCustomSearchWeights} />
            <div className="flex flex-wrap content-start items-end gap-2">
              <BudgetInput
                label="Answer budget"
                value={answerBudgetMs}
                min={500}
                max={30000}
                disabled={responseMode !== "fast" || runQuery.isPending}
                onChange={setAnswerBudgetMs}
              />
              <BudgetInput
                label="Response budget"
                value={responseBudgetMs}
                min={1000}
                max={60000}
                disabled={responseMode !== "fast" || runQuery.isPending}
                onChange={setResponseBudgetMs}
              />
              <div className="flex gap-2">
                <Button type="button" variant="secondary" disabled={!canTune} onClick={() => setSearchTuningOpen(true)}>
                  <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                  Open preview
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!hasCustomSearchWeights || runQuery.isPending}
                  onClick={() => {
                    setSearchWeights(defaultSearchWeights);
                    setHasCustomSearchWeights(false);
                  }}
                >
                  Reset weights
                </Button>
              </div>
            </div>
          </div>
        </details>

        <p className="mt-4 min-h-5 text-sm text-[#62717a]" role="status">
          {formError || choiceError || runQuery.error?.message || (runQuery.isSuccess ? "Run complete" : "")}
        </p>
      </form>

      <SearchTuningPanel
        open={searchTuningOpen}
        weights={searchWeights}
        previewItems={simulationQuery.data?.items ?? []}
        isLoading={simulationQuery.isFetching}
        error={simulationQuery.error?.message}
        onChange={(weights) => {
          setHasCustomSearchWeights(true);
          setSearchWeights(weights);
        }}
        onClose={() => setSearchTuningOpen(false)}
      />

      <section className="min-w-0 rounded-md border border-[#d6dde1] bg-white">
        <div className="flex flex-col gap-2 border-b border-[#d6dde1] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Search className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
              <h2 className="truncate text-base font-semibold text-[#1f2933]">Answers and evidence</h2>
            </div>
            <p className="mt-1 truncate text-sm text-[#62717a]">
              {selectedDocumentNames || "Select documents"} / {selectedVariantNames || "select variants"}
            </p>
          </div>
          {runQuery.data?.runs.length ? (
            <Badge>{runQuery.data.runs.length} run{runQuery.data.runs.length === 1 ? "" : "s"}</Badge>
          ) : null}
        </div>
        {isLoadingChoices ? (
          <div className="p-4">
            <EmptyState icon={Loader2} title="Loading query controls" description="Fetching documents and variants." />
          </div>
        ) : runQuery.isPending ? (
          <div className="p-4">
            <EmptyState
              icon={Loader2}
              title="Running query"
              description={
                responseMode === "fast"
                  ? "Preparing grounded evidence."
                  : "Searching chunks and generating answers."
              }
            />
          </div>
        ) : runQuery.data?.runs.length ? (
          <div className="space-y-4 p-4">
            {runQuery.data.runs.map((run) => (
              <RunResult key={run.id} run={run} variant={variantById.get(run.variant_id)} />
            ))}
          </div>
        ) : (
          <div className="p-4">
            <EmptyState
              icon={CheckSquare}
              title="No run selected"
              description="Choose documents and variants, then run a scoped query."
            />
          </div>
        )}
      </section>
    </div>
  );
}

function ChoicePanel({
  icon: Icon,
  title,
  selectedSummary,
  isLoading,
  error,
  empty,
  children,
}: {
  icon: typeof FileText;
  title: string;
  selectedSummary: string;
  isLoading: boolean;
  error?: string;
  empty: string;
  children: ReactNode;
}) {
  const rows = Array.isArray(children) ? children : [children];
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 flex items-center gap-2 px-1 text-sm font-semibold text-[#24313a]">
        <Icon className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        {title}
      </legend>
      <details className="relative">
        <summary className="flex h-10 cursor-pointer list-none items-center justify-between gap-2 rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#24313a]">
          <span className="min-w-0 truncate">{selectedSummary}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-[#62717a]" aria-hidden="true" />
        </summary>
        <div className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-md border border-[#cfd8dd] bg-white p-2 shadow-lg">
        {isLoading ? (
          <SmallState icon={Loader2} text="Loading" />
        ) : error ? (
          <SmallState icon={AlertCircle} text={error} />
        ) : rows.length && rows.some(Boolean) ? (
          children
        ) : (
          <SmallState icon={AlertCircle} text={empty} />
        )}
        </div>
      </details>
    </fieldset>
  );
}

function CheckboxRow({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      className={[
        "flex min-h-9 cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-sm",
        checked
          ? "border-[#0f766e] bg-[#e3f3f1] text-[#0c524d]"
          : "border-[#e1e7ea] bg-[#f8fafb] text-[#24313a]",
      ].join(" ")}
    >
      <input
        type="checkbox"
        className="h-4 w-4 accent-[#0f766e]"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0">
        <span className="block truncate font-semibold">{label}</span>
        <span className="block truncate text-xs text-[#62717a]">{detail}</span>
      </span>
    </label>
  );
}

function SearchWeightsSummary({ weights, custom }: { weights: HybridSearchWeights; custom: boolean }) {
  const weightItems = [
    { key: "reference_exact", label: "Reference exact" },
    { key: "term_coverage", label: "Term coverage" },
    { key: "metadata_boost", label: "Metadata boost" },
    { key: "semantic_density", label: "Semantic density" },
  ] as const;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-[#1f2933]">Search weights</h3>
        <Badge>{custom ? "custom" : "default"}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {weightItems.map((item) => {
          const value = Number(weights[item.key] ?? 1);
          return (
            <div key={item.key} className="rounded-md border border-[#e1e7ea] bg-white px-2 py-2">
              <div className="flex items-center justify-between gap-2 text-xs font-semibold text-[#62717a]">
                <span className="truncate">{item.label}</span>
                <span>{value.toFixed(1)}</span>
              </div>
              <div className="mt-2 h-1.5 rounded-full bg-[#d6dde1]">
                <span
                  className="block h-1.5 rounded-full bg-[#176b87]"
                  style={{ width: `${Math.min(100, Math.max(0, (value / 2) * 100))}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BudgetInput({
  label,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block w-32 text-sm font-medium text-[#3a4a53]">
      <span className="mb-1 block truncate">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={500}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-9 w-full rounded-md border border-[#cfd8dd] bg-white px-2 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#eef4f6] disabled:text-[#62717a]"
      />
    </label>
  );
}

function RunResult({ run, variant }: { run: RunOut; variant?: VariantOut }) {
  const answerMode = textValue(run.token_metadata.answer_mode);
  const llmAnswerStatus = textValue(run.token_metadata.llm_answer_status);
  const [selectedEvidence, setSelectedEvidence] = useState<NormalizedEvidence | null>(null);
  const [pathwayOpen, setPathwayOpen] = useState(false);
  const architecture = useMemo(() => buildThreePillarTrace(run), [run]);
  const readableSources = useMemo(
    () => run.sources.map((source, index) => normalizeQuerySource(source, index, run, architecture)),
    [architecture, run],
  );

  return (
    <article className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-base font-semibold text-[#1f2933]">{run.query}</h3>
          <p className="mt-1 truncate text-xs text-[#62717a]">
            {variant?.name ?? run.variant_id} · {run.id}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => setPathwayOpen(true)}>
            <GitBranch className="h-4 w-4" aria-hidden="true" />
            View pathway
          </Button>
          <StatusBadge status={run.status} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge>profile {run.runtime_profile_id ?? "n/a"}</Badge>
        <Badge>documents {run.document_ids.length}</Badge>
        {run.error_type ? <Badge>{run.error_type}</Badge> : null}
      </div>
      <RerankerSummary traces={run.reranker_traces} />
      <ArchitectureTraceSummary architecture={architecture} />
      {answerMode === "evidence_first" ? (
        <div className="mt-3 rounded-md border border-[#cfe3ea] bg-[#f5fafb] p-3 text-sm text-[#3a4a53]">
          <p className="font-semibold text-[#1f2933]">Evidence-first result</p>
          {llmAnswerStatus === "timeout" ? (
            <p className="mt-1 text-xs text-[#62717a]">LLM wording exceeded the fast budget.</p>
          ) : null}
        </div>
      ) : null}

      {run.error ? (
        <p className="mt-3 rounded-md border border-[#e19a9a] bg-[#fff0f0] p-3 text-sm text-[#8c2525]">
          {run.error_type ? `${run.error_type}: ` : ""}
          {run.error}
        </p>
      ) : (
        <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#24313a]">{run.answer || "No answer returned."}</p>
      )}

      {readableSources.length ? (
        <section className="mt-4 rounded-md border border-[#d6dde1] bg-[#fbfcfd] p-3">
          <h4 className="text-sm font-semibold text-[#1f2933]">Readable sources</h4>
          <div className="mt-3 space-y-2">
            {readableSources.map((evidence) => (
              <SourceEvidenceRow
                key={evidence.id}
                evidence={evidence}
                onInspect={() => setSelectedEvidence(evidence)}
              />
            ))}
          </div>
        </section>
      ) : null}

      <EvidenceViewer
        evidence={selectedEvidence}
        open={selectedEvidence !== null}
        onClose={() => setSelectedEvidence(null)}
      />
      <QueryPathwayViewer
        run={run}
        open={pathwayOpen}
        onClose={() => setPathwayOpen(false)}
      />

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <JsonPanel title="Sources" items={run.sources} />
        <JsonPanel title="Chunk traces" items={run.chunk_traces} />
        <JsonPanel title="Query config" items={[run.query_config]} />
        <JsonPanel title="Reranker traces" items={run.reranker_traces} />
        <JsonPanel title="Token metadata" items={[run.token_metadata]} />
      </div>
      <JsonPanel title="Timings" items={[run.timings]} compact />
    </article>
  );
}

function SourceEvidenceRow({
  evidence,
  onInspect,
}: {
  evidence: NormalizedEvidence;
  onInspect: () => void;
}) {
  return (
    <div className="rounded-md border border-[#e1e7ea] bg-white p-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="break-words font-mono text-xs font-semibold text-[#1f2933]">{evidence.id}</p>
          <p className="mt-1 break-words text-xs text-[#62717a]">
            {evidence.documentName || evidence.documentId || "Document link not recorded"}
          </p>
          <p className="mt-1 break-words text-xs text-[#62717a]">
            {evidence.sourceLocation
              ? summarizeEvidenceValue(evidence.sourceLocation)
              : "Source location not recorded"}
          </p>
        </div>
        <Button type="button" variant="secondary" size="sm" className="shrink-0" onClick={onInspect}>
          Inspect evidence
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge>{evidence.qualityStatus || "Default quality policy"}</Badge>
        <Badge>
          {evidence.parserWarnings?.length
            ? `${evidence.parserWarnings.length} parser warnings`
            : "No parser warnings"}
        </Badge>
      </div>
    </div>
  );
}

function normalizeQuerySource(
  source: Record<string, unknown>,
  index: number,
  run: RunOut,
  architecture: ThreePillarTraceSummary,
): NormalizedEvidence {
  const sourceId =
    textValue(source.id) ??
    textValue(source.source_id) ??
    textValue(source.chunk_id) ??
    textValue(source.chunkId) ??
    `source-${index + 1}`;
  const metadata = recordValue(source.metadata) ?? recordValue(source.metadata_json);
  const sourceLocation =
    recordValue(source.source_location) ??
    recordValue(source.sourceLocation) ??
    textValue(source.source_location) ??
    textValue(source.location);
  const relationshipRefs = relationshipRefsFrom(source, metadata);
  const indexShape = recordValue(metadata?.index_shape);
  const sourceArchitecture = architecture.sources.find((item) => item.sourceId === sourceId);

  return {
    id: sourceId,
    kind: "query-source",
    documentId:
      textValue(source.document_id) ??
      textValue(source.documentId) ??
      textValue(metadata?.document_id) ??
      run.document_ids[0] ??
      null,
    documentName:
      textValue(source.document_name) ??
      textValue(source.documentName) ??
      textValue(source.filename) ??
      textValue(metadata?.filename) ??
      textValue(metadata?.document_name) ??
      textValue(metadata?.documentName) ??
      textValue(recordValue(metadata?.document_metadata)?.title) ??
      null,
    runtimeProfileId:
      textValue(source.runtime_profile_id) ??
      textValue(source.runtimeProfileId) ??
      textValue(metadata?.runtime_profile_id) ??
      textValue(indexShape?.runtime_profile_id) ??
      run.runtime_profile_id ??
      null,
    text:
      textValue(source.text) ??
      textValue(source.chunk_text) ??
      textValue(source.content) ??
      textValue(source.snippet) ??
      null,
    sourceLocation,
    metadata,
    parserWarnings: parserWarningsFrom(source, metadata),
    qualityStatus: qualityStatusFrom(source, metadata),
    retrievalReasons: retrievalReasonsFrom(source),
    relationshipRefs,
    graphUnavailableDetail:
      textValue(source.graph_unavailable_detail) ?? textValue(source.graphUnavailableDetail) ?? null,
    rerankerSummary: rerankerSummaryForSource(sourceId, source, run.reranker_traces),
    architecture: sourceArchitecture
      ? {
          domain: sourceArchitecture.domain,
          layout: sourceArchitecture.layout,
          context: sourceArchitecture.context,
          assembly: {
            groundingStatus: architecture.assembly.groundingStatus,
            evidenceIds: architecture.assembly.evidenceIds,
            droppedReasons: architecture.assembly.droppedReasons.map(
              (item) => `${item.candidateId}: ${item.reason}`,
            ),
          },
        }
      : undefined,
    raw: source,
    routeLinks: {
      documents: Boolean(source.document_id || source.documentId || metadata?.document_id),
      chunks: true,
      query: true,
      graph: relationshipRefs.length > 0,
      diagnostics: true,
      documentUnavailableLabel: "Document link not recorded",
    },
  };
}

function rerankerSummaryForSource(
  sourceId: string,
  source: Record<string, unknown>,
  traces: Record<string, unknown>[],
): EvidenceRerankerSummary | null {
  if (!traces.length) {
    return null;
  }
  const exactTrace = traces.find((trace) => traceMatchesSource(trace, sourceId, source));
  const trace = exactTrace ?? traces[0];
  const status = textValue(trace.status);
  const provider = textValue(trace.provider);
  const model = textValue(trace.model);
  const errorType = textValue(trace.error_type);
  const rankCount = rerankerRankCount(traces, trace);
  return {
    status,
    provider,
    model,
    detail: [errorType, rankCount ? formatRankCount(rankCount) : ""].filter(Boolean).join(" · "),
    note: exactTrace ? undefined : "Run-level reranker summary; not source-specific",
    raw: trace,
  };
}

function traceMatchesSource(
  trace: Record<string, unknown>,
  sourceId: string,
  source: Record<string, unknown>,
) {
  const candidates = [
    trace.source_id,
    trace.sourceId,
    trace.chunk_id,
    trace.chunkId,
    trace.id,
    source.chunk_id,
    source.chunkId,
  ]
    .map(textValue)
    .filter(Boolean);
  return candidates.includes(sourceId);
}

function retrievalReasonsFrom(source: Record<string, unknown>) {
  const metadata = recordValue(source.metadata);
  const reasons = stringArray(
    source.retrieval_reasons ??
      source.reasons ??
      source.reason ??
      metadata?.retrieval_reasons ??
      metadata?.reasons,
  );
  const score = numberValue(source.score);
  return score !== undefined ? [...reasons, `score ${score.toFixed(3)}`] : reasons;
}

function parserWarningsFrom(
  source: Record<string, unknown>,
  metadata: Record<string, unknown> | null | undefined,
) {
  const direct = stringArray(
    source.parser_quality_warning_codes ??
      source.parser_warnings ??
      metadata?.parser_quality_warning_codes ??
      metadata?.parser_warnings,
  );
  if (direct.length) {
    return direct;
  }
  const extractionQuality =
    recordValue(source.extraction_quality) ?? recordValue(metadata?.extraction_quality);
  const parserWarnings = extractionQuality?.parser_warnings;
  if (!Array.isArray(parserWarnings)) {
    return [];
  }
  return parserWarnings
    .map((warning) => {
      if (typeof warning === "string") {
        return warning;
      }
      const record = recordValue(warning);
      return textValue(record?.code) ?? textValue(record?.message);
    })
    .filter(Boolean) as string[];
}

function qualityStatusFrom(
  source: Record<string, unknown>,
  metadata: Record<string, unknown> | null | undefined,
) {
  const explicit =
    summarizePolicy(source.quality_action_policy) ??
    textValue(source.quality_status) ??
    summarizePolicy(metadata?.quality_action_policy) ??
    textValue(metadata?.quality_status);
  if (explicit) {
    return explicit;
  }
  const extractionQuality =
    recordValue(source.extraction_quality) ?? recordValue(metadata?.extraction_quality);
  const parserWarnings = extractionQuality?.parser_warnings;
  if (Array.isArray(parserWarnings) && parserWarnings.length > 0) {
    const actions = parserWarnings
      .map((warning) => textValue(recordValue(warning)?.quality_gate_action))
      .filter(Boolean);
    const actionSummary = actions.length ? `: ${Array.from(new Set(actions)).join(", ")}` : "";
    return `${parserWarnings.length} parser warning${parserWarnings.length === 1 ? "" : "s"}${actionSummary}`;
  }
  return null;
}

function summarizePolicy(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  const record = recordValue(value);
  if (!record) {
    return null;
  }
  const action =
    textValue(record.action) ??
    textValue(record.status) ??
    textValue(record.quality_gate_action) ??
    textValue(record.graph_confidence);
  return action ?? summarizeEvidenceValue(record);
}

function relationshipRefsFrom(
  source: Record<string, unknown>,
  metadata: Record<string, unknown> | null | undefined,
) {
  const direct = relationshipRefsValue(source.relationship_refs);
  if (direct.length) {
    return direct;
  }
  const explain = recordValue(metadata?.retrieval_explain);
  return relationshipRefsValue(explain?.relationship_refs);
}

function relationshipRefsValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries(value as Record<string, unknown>).map(
      ([key, item]) => `${key}: ${String(item)}`,
    );
  }
  return [];
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
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

function summarizeEvidenceValue(value: Record<string, unknown> | string) {
  if (typeof value === "string") {
    return value;
  }
  if (value.label) {
    return String(value.label);
  }
  return [
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
    .map(String)
    .join(" · ");
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
      {children}
    </span>
  );
}

function ArchitectureTraceSummary({ architecture }: { architecture: ThreePillarTraceSummary }) {
  const layoutCount = architecture.layout.candidateCount ?? 0;
  const contextCount = architecture.context.candidateCount ?? 0;
  return (
    <div className="mt-3 rounded-md border border-[#dce5e8] bg-[#f8fafb] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-[#1f2933]">Architecture trace</h4>
        <Badge>{architecture.route.domainProfileId}</Badge>
        <Badge>{architecture.route.materializationHint}</Badge>
        <Badge>layout {layoutCount}</Badge>
        <Badge>context {contextCount}</Badge>
        <Badge>{architecture.assembly.groundingStatus}</Badge>
      </div>
      <p className="text-xs leading-5 text-[#62717a]">
        {architecture.route.sourceOfTruth} / {architecture.layout.reason} / {architecture.context.reason}
      </p>
    </div>
  );
}

function RerankerSummary({ traces }: { traces: Record<string, unknown>[] }) {
  if (!traces.length) {
    return null;
  }

  const first = traces[0];
  const status = textValue(first.status) ?? "applied";
  const provider = textValue(first.provider);
  const model = textValue(first.model);
  const errorType = textValue(first.error_type);
  const rankCount = rerankerRankCount(traces, first);
  const detail = [provider, model, errorType, rankCount ? formatRankCount(rankCount) : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="mt-3 rounded-md border border-[#cfe3ea] bg-[#f5fafb] p-3 text-sm text-[#3a4a53]">
      <p className="font-semibold text-[#1f2933]">{rerankerStatusTitle(status)}</p>
      {detail ? <p className="mt-1 text-xs text-[#62717a]">{detail}</p> : null}
    </div>
  );
}

function rerankerStatusTitle(status: string) {
  switch (status) {
    case "failed":
      return "Reranker failed";
    case "blocked_endpoint":
      return "Reranker blocked";
    case "no_results":
    case "no_usable_results":
      return "Reranker returned no results";
    case "skipped":
      return "Reranker skipped";
    case "disabled":
      return "Reranker disabled";
    case "succeeded":
    case "applied":
    default:
      return "Reranker applied";
  }
}

function rerankerRankCount(traces: Record<string, unknown>[], first: Record<string, unknown>) {
  const explicitCount =
    numberValue(first.rank_count) ??
    numberValue(first.ranked_count) ??
    numberValue(first.result_count) ??
    numberValue(first.results_count);
  if (explicitCount !== undefined) {
    return explicitCount;
  }
  const rankedTraces = traces.filter(hasRankDetails);
  return rankedTraces.length || undefined;
}

function hasRankDetails(trace: Record<string, unknown>) {
  return numberValue(trace.rank) !== undefined || numberValue(trace.original_rank) !== undefined;
}

function formatRankCount(count: number) {
  return `${count} ${count === 1 ? "rank" : "ranks"}`;
}

function textValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function JsonPanel({
  title,
  items,
  compact = false,
}: {
  title: string;
  items: Record<string, unknown>[];
  compact?: boolean;
}) {
  return (
    <div className={compact ? "mt-3" : ""}>
      <h4 className="mb-2 text-xs font-semibold uppercase text-[#62717a]">{title}</h4>
      {items.length ? (
        <div className="max-h-64 space-y-2 overflow-auto rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
          {items.map((item, index) => (
            <pre key={`${title}-${index}`} className="whitespace-pre-wrap break-words text-xs leading-5 text-[#3a4a53]">
              {JSON.stringify(item, null, 2)}
            </pre>
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-3 text-sm text-[#62717a]">
          No {title.toLowerCase()} returned.
        </div>
      )}
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

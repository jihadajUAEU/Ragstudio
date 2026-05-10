import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckSquare,
  FileText,
  Loader2,
  MessageSquareText,
  PlayCircle,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { RunOut, VariantOut } from "../../api/generated";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { titleCase, toggleId } from "../../lib/utils";

const queryKeys = {
  documents: ["documents"],
  variants: ["variants"],
  runs: ["runs"],
} as const;

export function QueryPage() {
  const queryClient = useQueryClient();
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: apiClient.variants });
  const [queryText, setQueryText] = useState("");
  const [limit, setLimit] = useState(8);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);
  const [formError, setFormError] = useState("");

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
    if (selectedDocumentIds.length === 0) {
      setFormError("Select at least one document so the run is scoped.");
      return;
    }
    if (selectedVariantIds.length === 0) {
      setFormError("Select at least one variant.");
      return;
    }
    runQuery.mutate({
      query: queryText.trim(),
      document_ids: selectedDocumentIds,
      variant_ids: selectedVariantIds,
      limit,
    });
  };

  const variantById = useMemo(
    () => new Map((variantsQuery.data?.items ?? []).map((variant) => [variant.id, variant])),
    [variantsQuery.data?.items],
  );

  const isLoadingChoices = documentsQuery.isLoading || variantsQuery.isLoading;
  const choiceError = documentsQuery.error?.message ?? variantsQuery.error?.message;
  const canRun =
    !runQuery.isPending &&
    !isLoadingChoices &&
    queryText.trim().length > 0 &&
    selectedDocumentIds.length > 0 &&
    selectedVariantIds.length > 0;

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(340px,0.42fr)_minmax(0,0.58fr)]">
      <form onSubmit={submit} className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
        <div className="mb-5 flex items-center gap-2">
          <MessageSquareText className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Run RAG query</h2>
        </div>

        <label className="block min-w-0 text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Question</span>
          <textarea
            className="min-h-28 w-full resize-y rounded-md border border-[#cfd8dd] bg-white px-3 py-2 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20 disabled:bg-[#f4f7f8]"
            value={queryText}
            onChange={(event) => setQueryText(event.target.value)}
            disabled={runQuery.isPending}
            placeholder="Ask a focused question against selected documents."
          />
        </label>

        <div className="mt-4 grid gap-4">
          <ChoicePanel
            icon={FileText}
            title="Documents"
            isLoading={documentsQuery.isLoading}
            error={documentsQuery.error?.message}
            empty="Upload documents before querying."
          >
            {(documentsQuery.data?.items ?? []).map((document) => (
              <CheckboxRow
                key={document.id}
                label={document.filename}
                detail={`${titleCase(document.status)} · ${document.content_type}`}
                checked={selectedDocumentIds.includes(document.id)}
                onChange={(checked) =>
                  setSelectedDocumentIds((ids) => toggleId(ids, document.id, checked))
                }
              />
            ))}
          </ChoicePanel>

          <ChoicePanel
            icon={SlidersHorizontal}
            title="Variants"
            isLoading={variantsQuery.isLoading}
            error={variantsQuery.error?.message}
            empty="Create a variant before querying."
          >
            {(variantsQuery.data?.items ?? []).map((variant) => (
              <CheckboxRow
                key={variant.id}
                label={variant.name}
                detail={titleCase(variant.preset)}
                checked={selectedVariantIds.includes(variant.id)}
                onChange={(checked) =>
                  setSelectedVariantIds((ids) => toggleId(ids, variant.id, checked))
                }
              />
            ))}
          </ChoicePanel>
        </div>

        <div className="mt-4 flex items-end gap-3">
          <label className="min-w-0 flex-1 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block truncate">Chunk limit</span>
            <input
              type="number"
              min={0}
              max={50}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
              className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            />
          </label>
          <Button type="submit" disabled={!canRun}>
            {runQuery.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <PlayCircle className="h-4 w-4" aria-hidden="true" />
            )}
            Run
          </Button>
        </div>

        <p className="mt-4 min-h-5 text-sm text-[#62717a]" role="status">
          {formError || choiceError || runQuery.error?.message || (runQuery.isSuccess ? "Run complete" : "")}
        </p>
      </form>

      <section className="min-w-0">
        <div className="mb-3 flex items-center gap-2">
          <Search className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Answers and traces</h2>
        </div>
        {isLoadingChoices ? (
          <EmptyState icon={Loader2} title="Loading query controls" description="Fetching documents and variants." />
        ) : runQuery.isPending ? (
          <EmptyState icon={Loader2} title="Running query" description="Searching chunks and generating answers." />
        ) : runQuery.data?.runs.length ? (
          <div className="space-y-4">
            {runQuery.data.runs.map((run) => (
              <RunResult key={run.id} run={run} variant={variantById.get(run.variant_id)} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={CheckSquare}
            title="No run selected"
            description="Choose documents and variants, then run a scoped query."
          />
        )}
      </section>
    </div>
  );
}

function ChoicePanel({
  icon: Icon,
  title,
  isLoading,
  error,
  empty,
  children,
}: {
  icon: typeof FileText;
  title: string;
  isLoading: boolean;
  error?: string;
  empty: string;
  children: ReactNode;
}) {
  const rows = Array.isArray(children) ? children : [children];
  return (
    <fieldset className="min-w-0 rounded-md border border-[#e1e7ea] p-3">
      <legend className="flex items-center gap-2 px-1 text-sm font-semibold text-[#24313a]">
        <Icon className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        {title}
      </legend>
      <div className="mt-2 max-h-56 space-y-2 overflow-auto pr-1">
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
    <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-[#e1e7ea] bg-[#f8fafb] px-3 py-2 text-sm">
      <input
        type="checkbox"
        className="h-4 w-4 accent-[#176b87]"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0">
        <span className="block truncate font-medium text-[#24313a]">{label}</span>
        <span className="block truncate text-xs text-[#62717a]">{detail}</span>
      </span>
    </label>
  );
}

function RunResult({ run, variant }: { run: RunOut; variant?: VariantOut }) {
  return (
    <article className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="line-clamp-2 text-base font-semibold text-[#1f2933]">{run.query}</h3>
          <p className="mt-1 truncate text-xs text-[#62717a]">
            {variant?.name ?? run.variant_id} · {run.id}
          </p>
        </div>
        <StatusBadge status={run.status} className="shrink-0" />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge>profile {run.runtime_profile_id ?? "n/a"}</Badge>
        <Badge>documents {run.document_ids.length}</Badge>
        {run.error_type ? <Badge>{run.error_type}</Badge> : null}
      </div>

      {run.error ? (
        <p className="mt-3 rounded-md border border-[#e19a9a] bg-[#fff0f0] p-3 text-sm text-[#8c2525]">
          {run.error_type ? `${run.error_type}: ` : ""}
          {run.error}
        </p>
      ) : (
        <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-[#24313a]">{run.answer || "No answer returned."}</p>
      )}

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

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
      {children}
    </span>
  );
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

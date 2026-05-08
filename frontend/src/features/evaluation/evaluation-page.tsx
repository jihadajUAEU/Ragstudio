import { useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, ClipboardCheck, FileUp, Loader2, RefreshCcw, Upload } from "lucide-react";

import { apiClient } from "../../api/client";
import type { EvaluationCaseIn, EvaluationSetOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { formatCount } from "../../lib/utils";

const queryKeys = {
  evaluationSets: ["evaluation-sets"],
} as const;

export function EvaluationPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("Evaluation set");
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const evaluationSetsQuery = useQuery({
    queryKey: queryKeys.evaluationSets,
    queryFn: apiClient.evaluationSets,
  });

  const importEvaluationSet = useMutation({
    mutationFn: apiClient.importEvaluationSet,
    onSuccess: (evaluationSet) => {
      setFile(null);
      setSelectedSetId(evaluationSet.id);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.evaluationSets });
    },
  });

  const evaluationSets = evaluationSetsQuery.data?.items ?? [];
  const selectedSet =
    evaluationSets.find((evaluationSet) => evaluationSet.id === selectedSetId) ?? evaluationSets[0];

  const setColumns = useMemo<ColumnDef<EvaluationSetOut>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Set",
        cell: ({ row }) => (
          <button
            type="button"
            className="block max-w-full truncate text-left font-medium text-[#174657] hover:underline"
            onClick={() => setSelectedSetId(row.original.id)}
          >
            {row.original.name}
          </button>
        ),
      },
      {
        accessorKey: "cases",
        header: "Cases",
        cell: ({ row }) => <span>{formatCount(row.original.cases.length)}</span>,
      },
      {
        accessorKey: "id",
        header: "ID",
        cell: ({ row }) => <code className="block truncate text-xs text-[#62717a]">{row.original.id}</code>,
      },
    ],
    [],
  );

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Evaluation</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Evaluation sets and cases
          </h2>
        </div>
        <Button
          variant="secondary"
          onClick={() => void evaluationSetsQuery.refetch()}
          disabled={evaluationSetsQuery.isFetching}
        >
          {evaluationSetsQuery.isFetching ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      <section className="rounded-md border border-[#d6dde1] bg-white p-4">
        <form
          className="grid gap-3 lg:grid-cols-[minmax(180px,0.35fr)_minmax(220px,1fr)_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            if (file) {
              importEvaluationSet.mutate({ file, name: name.trim() || file.name });
            }
          }}
        >
          <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block truncate">Set name</span>
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
              disabled={importEvaluationSet.isPending}
            />
          </label>
          <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block truncate">Upload evaluation file</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.json,.yaml,.yml,.jsonl,application/json,text/csv"
              className="block w-full min-w-0 rounded-md border border-[#cfd8dd] bg-white text-sm text-[#1f2933] file:mr-3 file:h-10 file:border-0 file:bg-[#edf3f5] file:px-3 file:text-sm file:font-medium file:text-[#24313a]"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              disabled={importEvaluationSet.isPending}
            />
          </label>
          <Button type="submit" className="self-end" disabled={!file || importEvaluationSet.isPending}>
            {importEvaluationSet.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Upload className="h-4 w-4" aria-hidden="true" />
            )}
            Import
          </Button>
        </form>
        <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
          {importEvaluationSet.isSuccess ? "Imported evaluation set" : importEvaluationSet.error?.message}
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.45fr)_minmax(0,0.55fr)]">
        <Panel title="Sets" icon={FileUp}>
          {evaluationSetsQuery.isLoading ? (
            <EmptyState icon={Loader2} title="Loading evaluation sets" description="Fetching imported sets." />
          ) : evaluationSetsQuery.isError ? (
            <EmptyState
              icon={AlertCircle}
              title="Evaluation sets unavailable"
              description={evaluationSetsQuery.error.message}
              action={
                <Button variant="secondary" onClick={() => void evaluationSetsQuery.refetch()}>
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  Retry
                </Button>
              }
            />
          ) : (
            <DataTable
              columns={setColumns}
              data={evaluationSets}
              emptyTitle="No evaluation sets"
              emptyDescription="Imported CSV, JSON, YAML, or JSONL sets will appear here."
            />
          )}
        </Panel>

        <Panel title="Cases" icon={ClipboardCheck}>
          {selectedSet ? (
            <div className="space-y-3">
              <div className="rounded-md border border-[#d6dde1] bg-white p-4">
                <h3 className="truncate text-base font-semibold text-[#1f2933]">{selectedSet.name}</h3>
                <p className="mt-1 text-sm text-[#62717a]">{formatCount(selectedSet.cases.length)} cases</p>
              </div>
              {selectedSet.cases.map((evaluationCase) => (
                <CaseCard key={evaluationCase.id} evaluationCase={evaluationCase} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={ClipboardCheck}
              title="No cases selected"
              description="Import or select an evaluation set to inspect cases."
            />
          )}
        </Panel>
      </section>
    </div>
  );
}

function CaseCard({ evaluationCase }: { evaluationCase: EvaluationCaseIn }) {
  return (
    <article className="rounded-md border border-[#d6dde1] bg-white p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h4 className="line-clamp-2 text-sm font-semibold text-[#1f2933]">{evaluationCase.query}</h4>
          <code className="mt-1 block truncate text-xs text-[#62717a]">{evaluationCase.id}</code>
        </div>
        <span className="rounded-md border border-[#d6dde1] bg-[#f4f7f8] px-2 py-1 text-xs text-[#3a4a53]">
          {formatCount(evaluationCase.documents.length)} docs
        </span>
      </div>
      {evaluationCase.expected_answer ? (
        <p className="mt-3 line-clamp-3 text-sm leading-6 text-[#3a4a53]">{evaluationCase.expected_answer}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {evaluationCase.must_include.map((item) => (
          <span key={`include-${item}`} className="rounded-md bg-[#ecf8f0] px-2 py-1 text-[#24563a]">
            Include: {item}
          </span>
        ))}
        {evaluationCase.must_avoid.map((item) => (
          <span key={`avoid-${item}`} className="rounded-md bg-[#fff0f0] px-2 py-1 text-[#8c2525]">
            Avoid: {item}
          </span>
        ))}
      </div>
      <JsonDetails title="Details" value={evaluationCase} />
    </article>
  );
}

function JsonDetails({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="mt-3 rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
      <summary className="cursor-pointer text-xs font-semibold uppercase text-[#62717a]">{title}</summary>
      <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-[#3a4a53]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function Panel({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof FileUp;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        <h3 className="truncate text-base font-semibold text-[#1f2933]">{title}</h3>
      </div>
      {children}
    </section>
  );
}

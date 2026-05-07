import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  AlertCircle,
  ClipboardCheck,
  FileText,
  FlaskConical,
  Loader2,
  PlayCircle,
  RefreshCcw,
  SlidersHorizontal,
  Trophy,
} from "lucide-react";

import { apiClient } from "../../api/client";
import type { ExperimentScoreOut, RunOut } from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { formatCount, titleCase } from "../../lib/utils";

const queryKeys = {
  documents: ["documents"],
  variants: ["variants"],
  evaluationSets: ["evaluation-sets"],
  runs: ["runs"],
} as const;

export function ExperimentsPage() {
  const queryClient = useQueryClient();
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const variantsQuery = useQuery({ queryKey: queryKeys.variants, queryFn: apiClient.variants });
  const evaluationSetsQuery = useQuery({
    queryKey: queryKeys.evaluationSets,
    queryFn: apiClient.evaluationSets,
  });
  const [name, setName] = useState("Experiment");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [selectedVariantIds, setSelectedVariantIds] = useState<string[]>([]);
  const [evaluationSetId, setEvaluationSetId] = useState("");
  const [objectiveText, setObjectiveText] = useState("{\n  \"metric\": \"total\"\n}");
  const [formError, setFormError] = useState("");

  const createExperiment = useMutation({
    mutationFn: apiClient.createExperiment,
    onSuccess: () => {
      setFormError("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs });
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const objective = parseObject(objectiveText);
    if (!objective.ok) {
      setFormError(objective.message);
      return;
    }
    if (!evaluationSetId) {
      setFormError("Choose an evaluation set.");
      return;
    }
    if (selectedDocumentIds.length === 0) {
      setFormError("Choose at least one document.");
      return;
    }
    if (selectedVariantIds.length === 0) {
      setFormError("Choose at least one variant.");
      return;
    }
    createExperiment.mutate({
      name: name.trim() || "Experiment",
      document_ids: selectedDocumentIds,
      evaluation_set_id: evaluationSetId,
      variant_ids: selectedVariantIds,
      objective: objective.value,
    });
  };

  const scoreByRunId = useMemo(
    () => new Map((createExperiment.data?.scores ?? []).map((score) => [score.run_id, score])),
    [createExperiment.data?.scores],
  );

  const runColumns = useMemo<ColumnDef<RunOut>[]>(
    () => [
      {
        accessorKey: "query",
        header: "Case query",
        cell: ({ row }) => <span className="line-clamp-2">{row.original.query}</span>,
      },
      {
        accessorKey: "variant_id",
        header: "Variant",
        cell: ({ row }) => <code className="block truncate text-xs text-[#62717a]">{row.original.variant_id}</code>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "score",
        header: "Score",
        cell: ({ row }) => {
          const score = scoreByRunId.get(row.original.id);
          return <span className="font-medium">{score ? score.total : "n/a"}</span>;
        },
      },
    ],
    [scoreByRunId],
  );

  const scoreColumns = useMemo<ColumnDef<ExperimentScoreOut>[]>(
    () => [
      {
        accessorKey: "run_id",
        header: "Run",
        cell: ({ row }) => <code className="block truncate text-xs text-[#62717a]">{row.original.run_id}</code>,
      },
      {
        accessorKey: "total",
        header: "Total",
        cell: ({ row }) => <span className="font-medium">{row.original.total}</span>,
      },
      {
        accessorKey: "details",
        header: "Details",
        cell: ({ row }) => (
          <code className="block truncate text-xs text-[#62717a]">
            {Object.keys(row.original.details).join(", ") || "none"}
          </code>
        ),
      },
    ],
    [],
  );

  const isLoadingChoices =
    documentsQuery.isLoading || variantsQuery.isLoading || evaluationSetsQuery.isLoading;
  const choiceError =
    documentsQuery.error?.message ?? variantsQuery.error?.message ?? evaluationSetsQuery.error?.message;
  const canRun =
    !createExperiment.isPending &&
    !isLoadingChoices &&
    selectedDocumentIds.length > 0 &&
    selectedVariantIds.length > 0 &&
    Boolean(evaluationSetId);

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[minmax(340px,0.42fr)_minmax(0,0.58fr)]">
      <form onSubmit={submit} className="rounded-md border border-[#d6dde1] bg-white p-4 sm:p-5">
        <div className="mb-5 flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Run experiment</h2>
        </div>

        <label className="block text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Name</span>
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            disabled={createExperiment.isPending}
          />
        </label>

        <label className="mt-4 block text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Evaluation set</span>
          <select
            value={evaluationSetId}
            onChange={(event) => setEvaluationSetId(event.target.value)}
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            disabled={createExperiment.isPending}
          >
            <option value="">Choose set</option>
            {(evaluationSetsQuery.data?.items ?? []).map((evaluationSet) => (
              <option key={evaluationSet.id} value={evaluationSet.id}>
                {evaluationSet.name} ({evaluationSet.cases.length})
              </option>
            ))}
          </select>
        </label>

        <div className="mt-4 grid gap-4">
          <ChoicePanel
            icon={FileText}
            title="Documents"
            isLoading={documentsQuery.isLoading}
            error={documentsQuery.error?.message}
            empty="Upload documents before experimenting."
          >
            {(documentsQuery.data?.items ?? []).map((document) => (
              <CheckboxRow
                key={document.id}
                label={document.filename}
                detail={`${titleCase(document.status)} - ${document.content_type}`}
                checked={selectedDocumentIds.includes(document.id)}
                disabled={createExperiment.isPending}
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
            empty="Create variants before experimenting."
          >
            {(variantsQuery.data?.items ?? []).map((variant) => (
              <CheckboxRow
                key={variant.id}
                label={variant.name}
                detail={titleCase(variant.preset)}
                checked={selectedVariantIds.includes(variant.id)}
                disabled={createExperiment.isPending}
                onChange={(checked) =>
                  setSelectedVariantIds((ids) => toggleId(ids, variant.id, checked))
                }
              />
            ))}
          </ChoicePanel>
        </div>

        <label className="mt-4 block text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block truncate">Objective JSON</span>
          <textarea
            value={objectiveText}
            onChange={(event) => setObjectiveText(event.target.value)}
            className="min-h-24 w-full resize-y rounded-md border border-[#cfd8dd] bg-white px-3 py-2 font-mono text-xs text-[#1f2933] outline-none focus:border-[#176b87] focus:ring-2 focus:ring-[#176b87]/20"
            disabled={createExperiment.isPending}
          />
        </label>

        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="min-h-5 min-w-0 flex-1 truncate text-sm text-[#62717a]" role="status">
            {formError || choiceError || createExperiment.error?.message || (createExperiment.isSuccess ? "Experiment complete" : "")}
          </p>
          <Button type="submit" disabled={!canRun}>
            {createExperiment.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <PlayCircle className="h-4 w-4" aria-hidden="true" />
            )}
            Run
          </Button>
        </div>
      </form>

      <section className="min-w-0">
        <div className="mb-3 flex items-center gap-2">
          <Trophy className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
          <h2 className="truncate text-base font-semibold text-[#1f2933]">Runs and scores</h2>
        </div>
        {isLoadingChoices ? (
          <EmptyState icon={Loader2} title="Loading experiment inputs" description="Fetching documents, variants, and evaluation sets." />
        ) : createExperiment.isPending ? (
          <EmptyState icon={Loader2} title="Running experiment" description="Executing cases across selected variants." />
        ) : createExperiment.isError ? (
          <EmptyState
            icon={AlertCircle}
            title="Experiment failed"
            description={createExperiment.error.message}
            action={
              <Button variant="secondary" onClick={() => createExperiment.reset()}>
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                Clear
              </Button>
            }
          />
        ) : createExperiment.data ? (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <Metric label="Experiment" value={createExperiment.data.name} />
              <Metric label="Runs" value={formatCount(createExperiment.data.runs.length)} />
              <Metric label="Scores" value={formatCount(createExperiment.data.scores.length)} />
            </div>
            <DataTable
              columns={runColumns}
              data={createExperiment.data.runs}
              emptyTitle="No experiment runs"
              emptyDescription="Returned runs will appear here."
            />
            <DataTable
              columns={scoreColumns}
              data={createExperiment.data.scores}
              emptyTitle="No scores"
              emptyDescription="Score rows will appear after evaluation."
            />
          </div>
        ) : (
          <EmptyState
            icon={ClipboardCheck}
            title="No experiment run yet"
            description="Choose inputs and run an experiment to compare scored outputs."
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
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
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
        ) : hasRows ? (
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
  disabled = false,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-md border border-[#e1e7ea] bg-[#f8fafb] px-3 py-2 text-sm has-disabled:cursor-not-allowed has-disabled:opacity-65">
      <input
        type="checkbox"
        className="h-4 w-4 accent-[#176b87]"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0">
        <span className="block truncate font-medium text-[#24313a]">{label}</span>
        <span className="block truncate text-xs text-[#62717a]">{detail}</span>
      </span>
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-4">
      <p className="truncate text-xs font-semibold uppercase text-[#6f7f87]">{label}</p>
      <p className="mt-2 truncate text-lg font-semibold text-[#1f2933]">{value}</p>
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

function toggleId(ids: string[], id: string, checked: boolean) {
  if (checked) {
    return ids.includes(id) ? ids : [...ids, id];
  }
  return ids.filter((existingId) => existingId !== id);
}

function parseObject(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; message: string } {
  try {
    const parsed: unknown = JSON.parse(text || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, message: "Objective must be a JSON object." };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, message: "Objective JSON is malformed." };
  }
}

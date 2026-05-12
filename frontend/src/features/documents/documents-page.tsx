import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, FileUp, Loader2, RefreshCcw, Trash2, Upload, X } from "lucide-react";

import { apiClient, DEFAULT_PARSER_MODE } from "../../api/client";
import type {
  DocumentOut,
  IndexDocumentIn,
  JobOut,
  JobQualityWarningsOut,
  ParserQualityWarningOut,
} from "../../api/generated";
import { DataTable } from "../../components/data-table";
import { EmptyState } from "../../components/empty-state";
import { StatusBadge } from "../../components/status-badge";
import { Button } from "../../components/ui/button";
import { DomainMetadataPanel } from "../domain-metadata/domain-metadata-panel";
import { titleCase } from "../../lib/utils";

const queryKeys = {
  documents: ["documents"],
  jobs: ["jobs"],
} as const;

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hadActiveJobsRef = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [deletedFilename, setDeletedFilename] = useState("");
  const [reindexedFilename, setReindexedFilename] = useState("");
  const [selectedWarningJobId, setSelectedWarningJobId] = useState<string | null>(null);
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: DEFAULT_PARSER_MODE,
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const [metadataValid, setMetadataValid] = useState(true);
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: apiClient.jobs,
    refetchInterval: (query) => (hasActiveJobs(query.state.data?.items ?? []) ? 2000 : false),
  });
  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const activeJobs = hasActiveJobs(jobs);
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents,
    queryFn: apiClient.documents,
    refetchInterval: activeJobs ? 2000 : false,
  });
  const profilesQuery = useQuery({
    queryKey: ["domain-profiles"],
    queryFn: apiClient.domainProfiles,
  });

  const uploadDocument = useMutation({
    mutationFn: apiClient.uploadDocument,
    onSuccess: () => {
      setFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
    },
  });
  const deleteDocument = useMutation({
    mutationFn: apiClient.deleteDocument,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs }),
        queryClient.invalidateQueries({ queryKey: ["chunks"] }),
      ]);
    },
  });
  const reindexDocument = useMutation({
    mutationFn: ({ documentId, options }: { documentId: string; options: IndexDocumentIn }) =>
      apiClient.createDocumentReindexJob(documentId, options),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.documents }),
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs }),
        queryClient.invalidateQueries({ queryKey: ["chunks"] }),
      ]);
    },
  });

  const confirmAndDeleteDocument = useCallback(
    (document: DocumentOut) => {
      const confirmed = window.confirm(
        `Delete ${document.filename} and all indexed chunks? This cannot be undone.`,
      );
      if (!confirmed) {
        return;
      }
      setDeletedFilename(document.filename);
      deleteDocument.mutate(document.id);
    },
    [deleteDocument],
  );
  const reindexExistingDocument = useCallback(
    (document: DocumentOut) => {
      setReindexedFilename(document.filename);
      reindexDocument.mutate({
        documentId: document.id,
        options: document.latest_index_options ?? indexOptions,
      });
    },
    [indexOptions, reindexDocument],
  );

  const refresh = () => {
    void documentsQuery.refetch();
    void jobsQuery.refetch();
  };
  const documentsById = useMemo(
    () => new Map((documentsQuery.data?.items ?? []).map((document) => [document.id, document])),
    [documentsQuery.data?.items],
  );
  const selectedWarningJob = useMemo(
    () => jobs.find((job) => job.id === selectedWarningJobId) ?? null,
    [jobs, selectedWarningJobId],
  );
  const selectedWarningDocument = selectedWarningJob?.target_id
    ? documentsById.get(selectedWarningJob.target_id)
    : undefined;
  const warningDetailsQuery = useQuery({
    queryKey: ["jobs", selectedWarningJobId, "quality-warnings"],
    queryFn: () => apiClient.jobQualityWarnings(selectedWarningJobId ?? ""),
    enabled: selectedWarningJobId !== null,
  });

  const refetchDocuments = documentsQuery.refetch;

  useEffect(() => {
    const hadActiveJobs = hadActiveJobsRef.current;
    hadActiveJobsRef.current = activeJobs;
    if (hadActiveJobs && !activeJobs) {
      void refetchDocuments();
    }
  }, [activeJobs, jobsQuery.dataUpdatedAt, refetchDocuments]);

  const documentColumns = useMemo<ColumnDef<DocumentOut>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "Document",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{row.original.filename}</p>
            <p className="truncate text-xs text-[#6f7f87]">{row.original.content_type}</p>
          </div>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const document = row.original;
          const isDeleting = deleteDocument.isPending && deleteDocument.variables === document.id;
          const isReindexing =
            reindexDocument.isPending && reindexDocument.variables?.documentId === document.id;
          const canUseStoredIndexOptions = document.latest_index_options != null;
          const canReindex = canUseStoredIndexOptions || metadataValid;

          return (
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => reindexExistingDocument(document)}
                disabled={!canReindex || reindexDocument.isPending}
                aria-label={`Reindex ${document.filename}`}
              >
                {isReindexing ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                )}
                Reindex
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => confirmAndDeleteDocument(document)}
                disabled={isDeleting}
                aria-label={`Delete ${document.filename}`}
              >
                {isDeleting ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                )}
                Delete
              </Button>
            </div>
          );
        },
      },
    ],
    [
      confirmAndDeleteDocument,
      deleteDocument.isPending,
      deleteDocument.variables,
      metadataValid,
      reindexDocument.isPending,
      reindexDocument.variables,
      reindexExistingDocument,
    ],
  );

  const jobColumns = useMemo<ColumnDef<JobOut>[]>(
    () => [
      {
        accessorKey: "type",
        header: "Job",
        cell: ({ row }) => {
          const document = row.original.target_id
            ? documentsById.get(row.original.target_id)
            : undefined;

          return (
            <div className="min-w-0">
              <p className="truncate font-medium">{formatJobName(row.original, document)}</p>
              <code className="block truncate text-xs text-[#62717a]">
                {document
                  ? `${formatJobType(row.original.type)} · ${row.original.id}`
                  : row.original.target_id ?? "workspace"}
              </code>
            </div>
          );
        },
      },
      {
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => {
          const progress = getJobProgress(row.original);
          const mineruStatus = getMinerUStatus(row.original.result);

          return (
            <div className="min-w-32 space-y-1">
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#e6ecef]">
                  <div
                    className="h-full rounded-full bg-[#176b87]"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <span className="w-9 text-right text-xs text-[#62717a]">{progress}%</span>
              </div>
              {mineruStatus?.status ? (
                <p className="truncate text-xs text-[#62717a]">MinerU {mineruStatus.status}</p>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "logs",
        header: "Latest log",
        cell: ({ row }) => {
          const mineruStatus = formatMinerUResult(row.original);
          const stageText = jobStageText(row.original);
          const warnings = jobWarnings(row.original);
          const parserQualityGroups = jobParserQualityGroups(row.original);
          const canInspectWarnings = hasInspectableQualityWarnings(row.original);

          return (
            <div className="min-w-0 space-y-1 text-xs text-[#62717a]">
              {mineruStatus ? (
                <p className="truncate font-medium text-[#3a4a53]">MinerU: {mineruStatus}</p>
              ) : null}
              {stageText ? <p className="line-clamp-2 text-[#3a4a53]">{stageText}</p> : null}
              {warnings.map((warning) => (
                <p key={warning} className="line-clamp-2 text-[#8a5a00]">
                  {warning}
                </p>
              ))}
              {parserQualityGroups.length ? (
                <ParserQualityDetails groups={parserQualityGroups} />
              ) : null}
              <p className="line-clamp-2">{row.original.logs.at(-1) ?? "No logs"}</p>
              {canInspectWarnings ? (
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  className="mt-1"
                  onClick={() => setSelectedWarningJobId(row.original.id)}
                  aria-label={`Inspect warning details for ${formatJobName(
                    row.original,
                    row.original.target_id ? documentsById.get(row.original.target_id) : undefined,
                  )}`}
                >
                  <AlertCircle className="h-4 w-4" aria-hidden="true" />
                  Inspect warnings
                </Button>
              ) : null}
            </div>
          );
        },
      },
    ],
    [documentsById],
  );

  const isRefreshing = documentsQuery.isFetching || jobsQuery.isFetching;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-medium text-[#176b87]">Documents</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-normal text-[#1f2933]">
            Source files and ingestion jobs
          </h2>
        </div>
        <Button variant="secondary" onClick={refresh} disabled={isRefreshing}>
          {isRefreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          )}
          Refresh
        </Button>
      </section>

      <section className="rounded-md border border-[#d6dde1] bg-white p-4">
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (file) {
              uploadDocument.mutate({ file, options: indexOptions });
            }
          }}
        >
          <div className="grid gap-3">
            <label className="min-w-0 text-sm font-medium text-[#3a4a53]">
              <span className="mb-1.5 block truncate">Upload file</span>
              <input
                ref={fileInputRef}
                type="file"
                className="block h-10 w-full min-w-0 rounded-md border border-[#cfd8dd] bg-white text-sm text-[#1f2933] file:mr-3 file:h-full file:border-0 file:bg-[#edf3f5] file:px-3 file:text-sm file:font-medium file:text-[#24313a]"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                disabled={uploadDocument.isPending}
              />
            </label>
          </div>
          <div className="min-w-0">
            <DomainMetadataPanel
              profiles={profilesQuery.data?.items ?? []}
              value={indexOptions}
              onChange={setIndexOptions}
              disabled={uploadDocument.isPending}
              onValidityChange={setMetadataValid}
              suggestContext={
                file
                  ? {
                      filename: file.name,
                      content_type: file.type || "application/octet-stream",
                      file,
                    }
                  : undefined
              }
            />
          </div>
          <div className="flex justify-end">
            <Button type="submit" disabled={!file || !metadataValid || uploadDocument.isPending}>
              {uploadDocument.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Upload className="h-4 w-4" aria-hidden="true" />
              )}
              Upload
            </Button>
          </div>
        </form>
        <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
          {uploadDocument.isSuccess ? "Uploaded" : uploadDocument.error?.message}
        </p>
      </section>

      <section className="grid gap-4">
        <Panel title="Documents" icon={FileUp}>
          <div className="space-y-3">
            {documentsQuery.isLoading ? (
              <EmptyState
                icon={Loader2}
                title="Loading documents"
                description="Fetching uploaded files."
              />
            ) : documentsQuery.isError ? (
              <EmptyState
                icon={AlertCircle}
                title="Documents unavailable"
                description={documentsQuery.error.message}
                action={
                  <Button variant="secondary" onClick={() => void documentsQuery.refetch()}>
                    <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                    Retry
                  </Button>
                }
              />
            ) : (
              <DataTable
                columns={documentColumns}
                data={documentsQuery.data?.items ?? []}
                emptyTitle="No documents"
                emptyDescription="Uploaded files will appear here."
              />
            )}
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {deleteDocument.isSuccess
                ? `Deleted ${deletedFilename}`
                : deleteDocument.error?.message}
            </p>
            <p className="min-h-5 text-sm text-[#62717a]" role="status">
              {reindexDocument.isSuccess
                ? `Reindex queued for ${reindexedFilename}`
                : reindexDocument.error?.message}
            </p>
          </div>
        </Panel>

        <Panel title="Jobs" icon={RefreshCcw}>
          {jobsQuery.isLoading ? (
            <EmptyState icon={Loader2} title="Loading jobs" description="Fetching job status." />
          ) : jobsQuery.isError ? (
            <EmptyState
              icon={AlertCircle}
              title="Jobs unavailable"
              description={jobsQuery.error.message}
              action={
                <Button variant="secondary" onClick={() => void jobsQuery.refetch()}>
                  <RefreshCcw className="h-4 w-4" aria-hidden="true" />
                  Retry
                </Button>
              }
            />
          ) : (
            <DataTable
              columns={jobColumns}
              data={jobs}
              emptyTitle="No jobs"
              emptyDescription="Upload and indexing jobs will appear here."
            />
          )}
          {selectedWarningJobId ? (
            <QualityWarningsPanel
              jobName={
                selectedWarningJob
                  ? formatJobName(selectedWarningJob, selectedWarningDocument)
                  : selectedWarningJobId
              }
              details={warningDetailsQuery.data}
              isLoading={warningDetailsQuery.isLoading}
              error={warningDetailsQuery.error}
              onClose={() => setSelectedWarningJobId(null)}
            />
          ) : null}
        </Panel>
      </section>
    </div>
  );
}

function hasActiveJobs(jobs: JobOut[]): boolean {
  return jobs.some((job) => job.status === "ready" || job.status === "running");
}

function formatJobName(job: JobOut, document: DocumentOut | undefined): string {
  if (document && job.type === "index_document") {
    return `Index ${document.filename}`;
  }
  if (document) {
    return `${formatJobType(job.type)} ${document.filename}`;
  }
  return formatJobType(job.type);
}

function formatJobType(type: string): string {
  return titleCase(type.replaceAll("_", " "));
}

function getJobProgress(job: JobOut): number {
  const mineru = getMinerUStatus(job.result);
  const stageProgress = getIndexingStageProgress(job.result);
  const progress =
    job.status === "running"
      ? (stageProgress ?? mineru?.progress ?? job.progress)
      : (job.progress ?? stageProgress ?? mineru?.progress);
  const rounded = Math.max(0, Math.min(Math.round(progress), 100));

  if (job.status === "running") {
    return Math.min(rounded, 99);
  }
  return rounded;
}

function getIndexingStageProgress(result: Record<string, unknown>): number | null {
  const stage = result.indexing_stage;
  if (!isRecord(stage) || typeof stage.progress !== "number") {
    return null;
  }
  return stage.progress;
}

function formatMinerUResult(job: JobOut): string | null {
  const mineru = getMinerUStatus(job.result);
  if (!mineru) {
    return null;
  }

  if (job.status === "running" && mineru.status === "Ready") {
    return "Ready · Finalizing index";
  }

  const progress =
    job.status === "running" && typeof mineru.progress === "number"
      ? `${Math.min(Math.round(mineru.progress), job.status === "running" ? 99 : 100)}%`
      : null;

  return [mineru.status, progress, mineru.detail].filter(Boolean).join(" · ") || null;
}

function jobStageText(job: JobOut | undefined): string | null {
  const stage = job?.result?.indexing_stage;
  if (!isRecord(stage)) {
    return null;
  }

  const label = typeof stage.label === "string" ? stage.label : null;
  const detail = typeof stage.detail === "string" ? stage.detail : null;
  const chunkCount = typeof stage.chunk_count === "number" ? stage.chunk_count : null;
  const parts = [label, detail].filter(Boolean);
  if (chunkCount !== null) {
    parts.push(`${chunkCount} chunks`);
  }
  return parts.length ? parts.join(" · ") : null;
}

function jobWarnings(job: JobOut | undefined): string[] {
  const warnings = job?.result?.warnings;
  if (!Array.isArray(warnings)) {
    return [];
  }
  return warnings.filter((warning): warning is string => typeof warning === "string");
}

function hasInspectableQualityWarnings(job: JobOut): boolean {
  if (warningCountEntries(parserQualityWarningCounts(job.result)).length > 0) {
    return true;
  }
  if (jobParserQualityGroups(job).length > 0) {
    return true;
  }
  const indexQuality = job.result.index_quality_report;
  if (isRecord(indexQuality) && typeof indexQuality.status === "string") {
    const status = indexQuality.status.toLowerCase();
    if (status.includes("warning") || status.includes("missing") || status.includes("failed")) {
      return true;
    }
  }
  if (
    jobWarnings(job).some((warning) => {
      const normalized = warning.toLowerCase();
      return normalized.includes("parser") || normalized.includes("quality");
    })
  ) {
    return true;
  }
  return job.logs.some((log) => log.toLowerCase().includes("parser quality warnings"));
}

function parserQualityWarningCounts(result: Record<string, unknown>): Record<string, number> {
  const parserQuality = result.parser_quality;
  if (!isRecord(parserQuality)) {
    return {};
  }
  const warningCounts = parserQuality.warning_counts;
  if (!isRecord(warningCounts)) {
    return {};
  }
  return numericRecord(warningCounts);
}

function warningCountEntries(counts: Record<string, number>): [string, number][] {
  return Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
}

interface ParserQualityGroup {
  code: string;
  chunkCount: number;
  warningCount: number;
  message: string | null;
  blockTypes: Record<string, number>;
  expectedScripts: Record<string, number>;
  actions: Record<string, number>;
  pages: Array<string | number>;
  references: string[];
  examples: ParserQualityExample[];
}

interface ParserQualityExample {
  chunkId: string | null;
  page: string | number | null;
  reference: string | null;
  blockType: string | null;
  expectedScript: string | null;
  action: string | null;
  message: string | null;
  textPreview: string;
}

function ParserQualityDetails({ groups }: { groups: ParserQualityGroup[] }) {
  const totalChunks = groups.reduce((total, group) => total + group.chunkCount, 0);

  return (
    <details className="rounded-md border border-[#ead9a7] bg-[#fffaf0] p-2 text-[#5f4600]">
      <summary className="cursor-pointer font-medium">
        Parser warning details · {groups.length} types · {totalChunks} chunks
      </summary>
      <div className="mt-2 max-h-72 space-y-3 overflow-auto pr-1">
        {groups.map((group) => (
          <div key={group.code} className="space-y-1 border-t border-[#ead9a7] pt-2 first:border-t-0 first:pt-0">
            <p className="font-medium text-[#3a2f12]">
              {group.code} · {group.chunkCount} chunks · {group.warningCount} warnings
            </p>
            {group.message ? <p>{group.message}</p> : null}
            <ParserQualityBreakdown label="Block types" values={group.blockTypes} />
            <ParserQualityBreakdown label="Expected scripts" values={group.expectedScripts} />
            <ParserQualityBreakdown label="Actions" values={group.actions} />
            {group.pages.length ? <p>Pages: {group.pages.join(", ")}</p> : null}
            {group.references.length ? <p>References: {group.references.join(", ")}</p> : null}
            {group.examples.length ? (
              <div className="space-y-1">
                {group.examples.map((example, index) => (
                  <div
                    key={`${group.code}-${example.chunkId ?? "chunk"}-${index}`}
                    className="rounded border border-[#ead9a7] bg-white p-2"
                  >
                    <p className="font-medium text-[#3a2f12]">
                      {[example.reference, example.page ? `page ${example.page}` : null]
                        .filter(Boolean)
                        .join(" · ") || example.chunkId || "Sample"}
                    </p>
                    <p className="break-words">{example.textPreview || example.message}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </details>
  );
}

function ParserQualityBreakdown({
  label,
  values,
}: {
  label: string;
  values: Record<string, number>;
}) {
  const entries = Object.entries(values);
  if (!entries.length) {
    return null;
  }
  return (
    <p>
      {label}: {entries.map(([name, count]) => `${name}=${count}`).join(", ")}
    </p>
  );
}

function QualityWarningsPanel({
  jobName,
  details,
  isLoading,
  error,
  onClose,
}: {
  jobName: string;
  details: JobQualityWarningsOut | undefined;
  isLoading: boolean;
  error: Error | null;
  onClose: () => void;
}) {
  const countEntries = warningCountEntries(details?.warning_counts ?? {});
  const indexQuality = details ? indexQualitySummary(details) : null;

  return (
    <div className="mt-4 rounded-md border border-[#d6dde1] bg-[#fbfcfd] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-semibold text-[#1f2933]">Warning details</h4>
          <p className="truncate text-xs text-[#62717a]">{jobName}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClose}
          aria-label="Close warning details"
        >
          <X className="h-4 w-4" aria-hidden="true" />
          Close
        </Button>
      </div>

      {isLoading ? (
        <p className="mt-4 text-sm text-[#62717a]">Loading warning details.</p>
      ) : error ? (
        <p className="mt-4 text-sm text-[#8a1f11]">{error.message}</p>
      ) : details ? (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2 text-xs">
            {countEntries.length ? (
              countEntries.map(([code, count]) => (
                <span
                  key={code}
                  className="rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-[#705000]"
                >
                  {code}={count}
                </span>
              ))
            ) : (
              <span className="text-[#62717a]">No parser warning rows found.</span>
            )}
            <span className="rounded-md border border-[#d6dde1] bg-white px-2 py-1 text-[#3a4a53]">
              affected_chunks={details.affected_chunks}
            </span>
            {details.truncated ? (
              <span className="rounded-md border border-[#d6dde1] bg-white px-2 py-1 text-[#3a4a53]">
                showing={details.items.length}/{details.total}
              </span>
            ) : null}
          </div>
          {indexQuality ? <p className="text-xs font-medium text-[#3a4a53]">{indexQuality}</p> : null}
          {details.job_warnings.length ? (
            <ul className="space-y-1 text-xs text-[#8a5a00]">
              {details.job_warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          {details.items.length ? (
            <ol className="max-h-96 space-y-2 overflow-auto pr-1">
              {details.items.map((item, index) => (
                <QualityWarningItem key={`${item.chunk_id}-${index}`} item={item} />
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function QualityWarningItem({ item }: { item: ParserQualityWarningOut }) {
  const metadataLine = [
    item.page != null ? `Page ${item.page}` : null,
    item.block_type,
    warningReferences(item),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="rounded-md border border-[#edf1f3] bg-white p-3 text-sm text-[#24313a]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-[#fff8df] px-2 py-1 text-xs font-medium text-[#705000]">
          {item.code ?? "parser_warning"}
        </span>
        {metadataLine ? <span className="text-xs text-[#62717a]">{metadataLine}</span> : null}
      </div>
      {item.message ? <p className="mt-2 text-sm text-[#3a4a53]">{item.message}</p> : null}
      {item.chunk_preview ? (
        <p className="mt-2 line-clamp-2 text-xs text-[#62717a]">{item.chunk_preview}</p>
      ) : null}
      <dl className="mt-2 grid gap-1 text-xs text-[#62717a] md:grid-cols-2">
        <div className="min-w-0">
          <dt className="font-medium text-[#3a4a53]">Chunk</dt>
          <dd className="truncate">{item.chunk_id}</dd>
        </div>
        <div className="min-w-0">
          <dt className="font-medium text-[#3a4a53]">Source</dt>
          <dd className="truncate">{formatRecord(item.source_location)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="font-medium text-[#3a4a53]">Parser</dt>
          <dd className="truncate">{formatRecord(item.parser_metadata)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="font-medium text-[#3a4a53]">Warning</dt>
          <dd className="truncate">{formatRecord(item.warning)}</dd>
        </div>
      </dl>
    </li>
  );
}

function jobParserQualityGroups(job: JobOut | undefined): ParserQualityGroup[] {
  const details = job?.result?.parser_quality_details;
  if (!isRecord(details) || !Array.isArray(details.groups)) {
    return [];
  }
  return details.groups
    .map((group): ParserQualityGroup | null => {
      if (!isRecord(group) || typeof group.code !== "string") {
        return null;
      }
      return {
        code: group.code,
        chunkCount: numberValue(group.chunk_count),
        warningCount: numberValue(group.warning_count),
        message: stringValue(group.message),
        blockTypes: numericRecord(group.block_types),
        expectedScripts: numericRecord(group.expected_scripts),
        actions: numericRecord(group.actions),
        pages: stringOrNumberList(group.pages),
        references: stringList(group.references),
        examples: parserQualityExamples(group.examples),
      };
    })
    .filter((group): group is ParserQualityGroup => group !== null);
}

function parserQualityExamples(value: unknown): ParserQualityExample[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((example): ParserQualityExample | null => {
      if (!isRecord(example)) {
        return null;
      }
      return {
        chunkId: stringValue(example.chunk_id),
        page: stringOrNumberValue(example.page),
        reference: stringValue(example.reference),
        blockType: stringValue(example.block_type),
        expectedScript: stringValue(example.expected_script),
        action: stringValue(example.action),
        message: stringValue(example.message),
        textPreview: stringValue(example.text_preview) ?? "",
      };
    })
    .filter((example): example is ParserQualityExample => example !== null);
}

function getMinerUStatus(result: Record<string, unknown>): {
  status: string | null;
  progress: number | null;
  detail: string | null;
} | null {
  const mineru = result.mineru;
  if (!isRecord(mineru)) {
    return null;
  }

  return {
    status: typeof mineru.status === "string" ? titleCase(mineru.status) : null,
    progress: typeof mineru.progress === "number" ? mineru.progress : null,
    detail: typeof mineru.detail === "string" && mineru.detail.length > 0 ? mineru.detail : null,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberValue(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringOrNumberValue(value: unknown): string | number | null {
  return typeof value === "string" || typeof value === "number" ? value : null;
}

function numericRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] => typeof entry[1] === "number"),
  );
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function stringOrNumberList(value: unknown): Array<string | number> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item): item is string | number => typeof item === "string" || typeof item === "number",
  );
}

function indexQualitySummary(details: JobQualityWarningsOut): string | null {
  const report = details.index_quality_report;
  if (!isRecord(report)) {
    return null;
  }
  const summary = isRecord(report.summary) ? report.summary : {};
  const parts = [
    typeof report.status === "string"
      ? `Index quality: ${titleCase(report.status.replaceAll("_", " "))}`
      : null,
    numericSummary(summary, "reference_units_missing_expected_script", "missing expected script"),
    numericSummary(summary, "reference_unit_unresolved_count", "unresolved references"),
    numericSummary(summary, "materialization_blocked_reference_count", "blocked references"),
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

function numericSummary(
  summary: Record<string, unknown>,
  key: string,
  label: string,
): string | null {
  const value = summary[key];
  if (typeof value !== "number" || value === 0) {
    return null;
  }
  return `${value} ${label}`;
}

function warningReferences(item: ParserQualityWarningOut): string | null {
  const references = item.reference_metadata?.references;
  if (!Array.isArray(references)) {
    return null;
  }
  const values = references.filter((reference): reference is string => typeof reference === "string");
  return values.length ? values.join(", ") : null;
}

function formatRecord(record: Record<string, unknown>): string {
  if (!Object.keys(record).length) {
    return "None";
  }
  return JSON.stringify(record);
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

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, FileUp, Loader2, RefreshCcw, Search, Trash2, Upload, X } from "lucide-react";

import { apiClient, DEFAULT_PARSER_MODE } from "../../api/client";
import type {
  DocumentOut,
  IndexDocumentIn,
  JobOut,
  JobQualityWarningsOut,
  MinerUParseOptionsIn,
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

type DocumentsTab = "documents" | "jobs";
const WARNING_VISIBLE_ROW_LIMIT = 200;
const DEFAULT_MINERU_PARSE_OPTIONS: MinerUParseOptionsIn = {
  parse_method: "auto",
  backend: "pipeline",
  device: "cuda:0",
  formula: true,
  table: true,
  max_concurrent_files: 1,
};
type LiveJobEventsById = Record<string, LiveJobEventSnapshot>;

interface LiveJobEventSnapshot {
  progress: number | null;
  stage: LiveJobStage | null;
  mineru: LiveMinerUStatus | null;
  logs: string[];
  warnings: string[];
  status: string | null;
  updatedAt: number;
}

interface LiveJobStage {
  label: string | null;
  detail: string | null;
  progress: number | null;
  chunkCount: number | null;
}

interface LiveMinerUStatus {
  status: string | null;
  progress: number | null;
  detail: string | null;
}

export function DocumentsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hadActiveJobsRef = useRef(false);
  const documentsPanelRef = useRef<HTMLDivElement>(null);
  const jobsPanelRef = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [deletedFilename, setDeletedFilename] = useState("");
  const [reindexedFilename, setReindexedFilename] = useState("");
  const [selectedWarningJobId, setSelectedWarningJobId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DocumentsTab>("documents");
  const [documentSearch, setDocumentSearch] = useState("");
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [liveJobEventsById, setLiveJobEventsById] = useState<LiveJobEventsById>({});
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: DEFAULT_PARSER_MODE,
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const [metadataValid, setMetadataValid] = useState(true);
  const setMineruParseOptions = useCallback(
    (mineru_parse_options: MinerUParseOptionsIn | null) => {
      setIndexOptions((current) => ({ ...current, mineru_parse_options }));
    },
    [],
  );
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: apiClient.jobs,
    refetchInterval: (query) => (hasActiveJobs(query.state.data?.items ?? []) ? 2000 : false),
  });
  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const activeJobs = hasActiveJobs(jobs);
  const activeJobIds = useMemo(() => jobs.filter(isActiveJob).map((job) => job.id), [jobs]);
  const activeJobIdsKey = activeJobIds.join("|");
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents,
    queryFn: apiClient.documents,
    refetchInterval: activeJobs ? 2000 : false,
  });
  const documents = useMemo(
    () => documentsQuery.data?.items ?? [],
    [documentsQuery.data?.items],
  );
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
      setActiveTab("jobs");
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
      setActiveTab("documents");
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
      setActiveTab("jobs");
    },
  });
  const fixQualityWarnings = useMutation({
    mutationFn: (jobId: string) => apiClient.fixJobQualityWarnings(jobId),
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
      const baseOptions = document.latest_index_options ?? indexOptions;
      reindexDocument.mutate({
        documentId: document.id,
        options: indexOptions.mineru_parse_options
          ? { ...baseOptions, mineru_parse_options: indexOptions.mineru_parse_options }
          : baseOptions,
      });
    },
    [indexOptions, reindexDocument],
  );
  const openDocumentEvidence = useCallback((document: DocumentOut) => {
    const target = `/document-evidence?documentId=${encodeURIComponent(document.id)}`;
    window.history.pushState(null, "", target);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  const activateTab = useCallback((tab: DocumentsTab, focusPanel = false) => {
    setActiveTab(tab);
    if (focusPanel) {
      window.requestAnimationFrame(() => {
        const panel = tab === "documents" ? documentsPanelRef.current : jobsPanelRef.current;
        panel?.focus();
      });
    }
  }, []);

  const handleTabKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, tab: DocumentsTab) => {
      const nextTab = tab === "documents" ? "jobs" : "documents";
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        activateTab(nextTab, true);
      }
      if (event.key === "Home") {
        event.preventDefault();
        activateTab("documents", true);
      }
      if (event.key === "End") {
        event.preventDefault();
        activateTab("jobs", true);
      }
    },
    [activateTab],
  );

  const refresh = () => {
    void documentsQuery.refetch();
    void jobsQuery.refetch();
  };
  const documentsById = useMemo(
    () => new Map(documents.map((document) => [document.id, document])),
    [documents],
  );
  const filteredDocuments = useMemo(
    () => filterDocuments(documents, documentSearch),
    [documentSearch, documents],
  );
  const jobStatusOptions = useMemo(
    () => Array.from(new Set(jobs.map((job) => job.status))).sort(),
    [jobs],
  );
  const activeJobCount = useMemo(() => jobs.filter(isActiveJob).length, [jobs]);
  const warningJobCount = useMemo(
    () => jobs.filter(hasInspectableQualityWarnings).length,
    [jobs],
  );
  const filteredJobs = useMemo(
    () => filterJobs(jobs, documentsById, jobSearch, jobStatusFilter, liveJobEventsById),
    [documentsById, jobSearch, jobStatusFilter, jobs, liveJobEventsById],
  );
  const selectedWarningJob = useMemo(
    () => jobs.find((job) => job.id === selectedWarningJobId) ?? null,
    [jobs, selectedWarningJobId],
  );
  const selectedWarningDocument = selectedWarningJob?.target_id
    ? documentsById.get(selectedWarningJob.target_id)
    : undefined;
  const latestWarningJob = useMemo(
    () => jobs.find(hasInspectableQualityWarnings) ?? null,
    [jobs],
  );
  const latestWarningDocument = latestWarningJob?.target_id
    ? documentsById.get(latestWarningJob.target_id)
    : undefined;
  const canFixSelectedWarnings = Boolean(
    selectedWarningJobId &&
      selectedWarningJob?.type === "index_document" &&
      selectedWarningJob.status === "succeeded",
  );
  const selectedWarningRepairPending = Boolean(
    selectedWarningJobId &&
      fixQualityWarnings.isPending &&
      fixQualityWarnings.variables === selectedWarningJobId,
  );
  const selectedWarningRepairQueued = Boolean(
    selectedWarningJobId &&
      fixQualityWarnings.isSuccess &&
      fixQualityWarnings.variables === selectedWarningJobId,
  );
  const warningDetailsQuery = useQuery({
    queryKey: ["jobs", selectedWarningJobId, "quality-warnings"],
    queryFn: () => apiClient.jobQualityWarnings(selectedWarningJobId ?? ""),
    enabled: selectedWarningJobId !== null,
  });
  const fixSelectedWarningJob = useCallback(() => {
    if (!selectedWarningJobId) {
      return;
    }
    fixQualityWarnings.mutate(selectedWarningJobId);
  }, [fixQualityWarnings, selectedWarningJobId]);

  const refetchDocuments = documentsQuery.refetch;

  useEffect(() => {
    const hadActiveJobs = hadActiveJobsRef.current;
    hadActiveJobsRef.current = activeJobs;
    if (hadActiveJobs && !activeJobs) {
      void refetchDocuments();
    }
  }, [activeJobs, jobsQuery.dataUpdatedAt, refetchDocuments]);

  useEffect(() => {
    const jobIds = activeJobIdsKey ? activeJobIdsKey.split("|") : [];
    if (!jobIds.length || typeof apiClient.createJobEventSource !== "function") {
      return;
    }

    const sources = jobIds.map((jobId) => {
      const source = apiClient.createJobEventSource(jobId);
      const handleEvent = (event: Event) => {
        const payload = parseJobEventPayload(event);
        if (!payload) {
          return;
        }
        setLiveJobEventsById((current) => ({
          ...current,
          [jobId]: mergeLiveJobEvent(current[jobId], payload),
        }));
        if (isTerminalJobEvent(payload, event.type)) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
          void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
        }
      };

      source.onmessage = handleEvent;
      ["stage", "progress", "log", "status"].forEach((eventName) => {
        source.addEventListener(eventName, handleEvent);
      });
      return source;
    });

    return () => {
      sources.forEach((source) => source.close());
    };
  }, [activeJobIdsKey, queryClient]);

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
                onClick={() => openDocumentEvidence(document)}
                aria-label={`Open parse evidence for ${document.filename}`}
              >
                Evidence
              </Button>
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
      openDocumentEvidence,
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
          const liveEvent = liveJobEventsById[row.original.id];
          const progress = getJobProgress(row.original, liveEvent);
          const mineruStatus = getMinerUStatus(row.original.result, liveEvent);

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
          const liveEvent = liveJobEventsById[row.original.id];
          const mineruStatus = formatMinerUResult(row.original, liveEvent);
          const stageText = jobStageText(row.original, liveEvent);
          const warnings = jobWarnings(row.original, liveEvent);
          const parserQualityGroups = jobParserQualityGroups(row.original);
          const canInspectWarnings = hasInspectableQualityWarnings(row.original);
          const latestLog = liveEvent?.logs.at(-1) ?? row.original.logs.at(-1) ?? "No logs";

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
              <p className="line-clamp-2">{latestLog}</p>
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
    [documentsById, liveJobEventsById],
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
          <details className="min-w-0 rounded-md border border-[#d6dde1] bg-[#fbfcfd] p-3">
            <summary className="cursor-pointer text-sm font-medium text-[#3a4a53]">
              Index options
              <span className="ml-2 text-xs font-normal text-[#62717a]">
                Default parser selected
              </span>
            </summary>
            <div className="mt-3 min-w-0">
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
              <MinerUParseOptionsControls
                value={indexOptions.mineru_parse_options ?? null}
                disabled={uploadDocument.isPending}
                onChange={setMineruParseOptions}
              />
            </div>
          </details>
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

      <OperationsStatusStrip
        documentsCount={documents.length}
        activeJobCount={activeJobCount}
        warningJobCount={warningJobCount}
        latestWarningLabel={
          latestWarningJob ? formatJobName(latestWarningJob, latestWarningDocument) : null
        }
        onViewJobs={() => activateTab("jobs", true)}
      />

      <div className="grid gap-1">
        <p className="min-h-5 text-sm text-[#62717a]" role="status">
          {deleteDocument.isSuccess ? `Deleted ${deletedFilename}` : deleteDocument.error?.message}
        </p>
        <p className="min-h-5 text-sm text-[#62717a]" role="status">
          {reindexDocument.isSuccess
            ? `Reindex queued for ${reindexedFilename}`
            : reindexDocument.error?.message}
        </p>
      </div>

      <section
        className="grid min-w-0 max-w-full gap-4 overflow-hidden"
        aria-label="Documents workspace"
      >
        <div
          role="tablist"
          aria-label="Document workspace sections"
          className="scroll-mt-24 flex min-w-0 max-w-full flex-wrap gap-2 overflow-hidden border-b border-[#d6dde1]"
        >
          <TabButton
            id="documents-tab"
            controls="documents-panel"
            selected={activeTab === "documents"}
            onSelect={() => activateTab("documents")}
            onKeyDown={(event) => handleTabKeyDown(event, "documents")}
            label="Documents"
            count={documents.length}
          />
          <TabButton
            id="jobs-tab"
            controls="jobs-panel"
            selected={activeTab === "jobs"}
            onSelect={() => activateTab("jobs")}
            onKeyDown={(event) => handleTabKeyDown(event, "jobs")}
            label="Jobs & Warnings"
            count={jobs.length}
          />
        </div>

        <div
          id="documents-panel"
          ref={documentsPanelRef}
          role="tabpanel"
          aria-labelledby="documents-tab"
          tabIndex={-1}
          hidden={activeTab !== "documents"}
          className="min-w-0 max-w-full overflow-hidden"
        >
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
              <>
                <TableToolbar
                  searchLabel="Search documents"
                  searchValue={documentSearch}
                  searchPlaceholder="Filename, type, or status"
                  onSearchChange={setDocumentSearch}
                  filteredCount={filteredDocuments.length}
                  totalCount={documents.length}
                  hasActiveFilters={Boolean(documentSearch.trim())}
                  onClearFilters={() => setDocumentSearch("")}
                />
                <DataTable
                  ariaLabel="Documents table"
                  columns={documentColumns}
                  data={filteredDocuments}
                  emptyTitle={documents.length ? "No matching documents" : "No documents"}
                  emptyDescription={
                    documents.length
                      ? "Clear the search to see every uploaded file."
                      : "Uploaded files will appear here."
                  }
                />
              </>
            )}
          </div>
          </Panel>
        </div>

        <div
          id="jobs-panel"
          ref={jobsPanelRef}
          role="tabpanel"
          aria-labelledby="jobs-tab"
          tabIndex={-1}
          hidden={activeTab !== "jobs"}
          className="min-w-0 max-w-full overflow-hidden"
        >
          <Panel title="Jobs & Warnings" icon={RefreshCcw}>
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
            <>
              <TableToolbar
                searchLabel="Search jobs"
                searchValue={jobSearch}
                searchPlaceholder="Filename, warning, job id, or log"
                onSearchChange={setJobSearch}
                filteredCount={filteredJobs.length}
                totalCount={jobs.length}
                statusLabel="Job status"
                statusValue={jobStatusFilter}
                statusOptions={jobStatusOptions}
                statusPlaceholder="All statuses"
                onStatusChange={setJobStatusFilter}
                hasActiveFilters={Boolean(jobSearch.trim() || jobStatusFilter)}
                onClearFilters={() => {
                  setJobSearch("");
                  setJobStatusFilter("");
                }}
              />
              <DataTable
                ariaLabel="Jobs table"
                columns={jobColumns}
                data={filteredJobs}
                emptyTitle={jobs.length ? "No matching jobs" : "No jobs"}
                emptyDescription={
                  jobs.length
                    ? "Clear the search or status filter to see every job."
                    : "Upload and indexing jobs will appear here."
                }
              />
            </>
          )}
          {selectedWarningJobId ? (
            <QualityWarningsPanel
              key={selectedWarningJobId}
              jobName={
                selectedWarningJob
                  ? formatJobName(selectedWarningJob, selectedWarningDocument)
                  : selectedWarningJobId
              }
              details={warningDetailsQuery.data}
              isLoading={warningDetailsQuery.isLoading}
              error={warningDetailsQuery.error}
              canFixWarnings={canFixSelectedWarnings}
              isFixingWarnings={selectedWarningRepairPending}
              fixStatus={
                selectedWarningRepairQueued && fixQualityWarnings.data
                  ? `Repair job queued: ${fixQualityWarnings.data.queued_job_id}`
                  : null
              }
              fixError={
                selectedWarningJobId && fixQualityWarnings.variables === selectedWarningJobId
                  ? fixQualityWarnings.error
                  : null
              }
              repairPlan={
                selectedWarningRepairQueued && fixQualityWarnings.data
                  ? fixQualityWarnings.data.repair_plan
                  : null
              }
              onFixWarnings={fixSelectedWarningJob}
              onClose={() => setSelectedWarningJobId(null)}
            />
          ) : null}
          </Panel>
        </div>
      </section>
    </div>
  );
}

function isActiveJob(job: JobOut): boolean {
  return job.status === "ready" || job.status === "running";
}

function hasActiveJobs(jobs: JobOut[]): boolean {
  return jobs.some(isActiveJob);
}

function parseJobEventPayload(event: Event): Record<string, unknown> | null {
  const data = (event as MessageEvent).data;
  if (typeof data !== "string" || !data.trim()) {
    return null;
  }
  try {
    const parsed = JSON.parse(data);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function mergeLiveJobEvent(
  current: LiveJobEventSnapshot | undefined,
  payload: Record<string, unknown>,
): LiveJobEventSnapshot {
  const stage = liveStageFromPayload(payload);
  const mineru = liveMinerUFromPayload(payload);
  const log = liveLogFromPayload(payload);
  const warnings = liveWarningsFromPayload(payload);
  return {
    progress: numberFromPayload(payload.progress) ?? stage?.progress ?? current?.progress ?? null,
    stage: stage ?? current?.stage ?? null,
    mineru: mineru ?? current?.mineru ?? null,
    logs: log ? [...(current?.logs ?? []), log].slice(-20) : (current?.logs ?? []),
    warnings: warnings.length ? warnings : (current?.warnings ?? []),
    status: stringValue(payload.status) ?? stringValue(payload.job_status) ?? current?.status ?? null,
    updatedAt: Date.now(),
  };
}

function liveStageFromPayload(payload: Record<string, unknown>): LiveJobStage | null {
  const result = isRecord(payload.result) ? payload.result : {};
  const directStage =
    recordValue(payload.indexing_stage) ??
    recordValue(payload.parser_stage) ??
    recordValue(payload.canonical_stage) ??
    recordValue(result.indexing_stage) ??
    recordValue(result.parser_stage) ??
    recordValue(result.canonical_stage) ??
    recordValue(payload.stage);

  if (directStage) {
    return {
      label:
        stringValue(directStage.label) ??
        stringValue(directStage.name) ??
        stringValue(directStage.stage) ??
        null,
      detail:
        stringValue(directStage.detail) ??
        stringValue(directStage.message) ??
        stringValue(payload.detail) ??
        stringValue(payload.message) ??
        null,
      progress: numberFromPayload(directStage.progress) ?? numberFromPayload(payload.progress),
      chunkCount:
        numberFromPayload(directStage.chunk_count) ??
        numberFromPayload(directStage.chunkCount) ??
        null,
    };
  }

  const stageName = stringValue(payload.stage) ?? stringValue(payload.stage_name);
  if (!stageName) {
    return null;
  }
  return {
    label: titleCase(stageName.replaceAll("_", " ")),
    detail: stringValue(payload.detail) ?? stringValue(payload.message),
    progress: numberFromPayload(payload.progress),
    chunkCount: numberFromPayload(payload.chunk_count) ?? numberFromPayload(payload.chunkCount),
  };
}

function liveMinerUFromPayload(payload: Record<string, unknown>): LiveMinerUStatus | null {
  const result = isRecord(payload.result) ? payload.result : {};
  const mineru = recordValue(payload.mineru) ?? recordValue(result.mineru);
  if (!mineru) {
    return null;
  }
  return {
    status: stringValue(mineru.status) ? titleCase(String(mineru.status)) : null,
    progress: numberFromPayload(mineru.progress),
    detail: stringValue(mineru.detail) ?? stringValue(mineru.message),
  };
}

function liveLogFromPayload(payload: Record<string, unknown>): string | null {
  return (
    stringValue(payload.log) ??
    stringValue(payload.message) ??
    stringValue(payload.detail) ??
    null
  );
}

function liveWarningsFromPayload(payload: Record<string, unknown>): string[] {
  const warnings = payload.warnings;
  return Array.isArray(warnings)
    ? warnings.filter((warning): warning is string => typeof warning === "string")
    : [];
}

function isTerminalJobEvent(payload: Record<string, unknown>, eventType: string): boolean {
  const status = stringValue(payload.status) ?? stringValue(payload.job_status) ?? eventType;
  return ["succeeded", "failed", "cancelled", "canceled", "complete", "completed"].includes(
    status.toLowerCase(),
  );
}

function OperationsStatusStrip({
  documentsCount,
  activeJobCount,
  warningJobCount,
  latestWarningLabel,
  onViewJobs,
}: {
  documentsCount: number;
  activeJobCount: number;
  warningJobCount: number;
  latestWarningLabel: string | null;
  onViewJobs: () => void;
}) {
  return (
    <section
      aria-label="Document indexing status"
      className="flex flex-col gap-3 rounded-md border border-[#d6dde1] bg-white p-3 lg:flex-row lg:items-center lg:justify-between"
    >
      <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-3">
        <StatusSummaryItem label="Documents" value={documentsCount} />
        <StatusSummaryItem label="Active jobs" value={activeJobCount} tone={activeJobCount ? "active" : "neutral"} />
        <StatusSummaryItem label="Warning jobs" value={warningJobCount} tone={warningJobCount ? "warning" : "neutral"} />
      </div>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
        {latestWarningLabel ? (
          <p className="min-w-0 truncate text-xs text-[#62717a]">
            Latest warning: <span className="font-medium text-[#3a4a53]">{latestWarningLabel}</span>
          </p>
        ) : null}
        <Button type="button" variant="secondary" size="sm" onClick={onViewJobs}>
          <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          View jobs
        </Button>
      </div>
    </section>
  );
}

function MinerUParseOptionsControls({
  value,
  disabled,
  onChange,
}: {
  value: MinerUParseOptionsIn | null;
  disabled: boolean;
  onChange: (value: MinerUParseOptionsIn | null) => void;
}) {
  const enabled = value !== null;
  const options = value ?? DEFAULT_MINERU_PARSE_OPTIONS;
  const updateOption = <K extends keyof MinerUParseOptionsIn>(
    key: K,
    nextValue: MinerUParseOptionsIn[K],
  ) => {
    onChange(compactMinerUParseOptions({ ...options, [key]: nextValue }));
  };

  return (
    <section className="mt-3 grid gap-3 border-t border-[#d6dde1] pt-3">
      <label className="flex h-10 items-center gap-2 text-sm font-medium text-[#3a4a53]">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled}
          onChange={(event) =>
            onChange(event.target.checked ? DEFAULT_MINERU_PARSE_OPTIONS : null)
          }
        />
        Override MinerU parser options
      </label>
      {enabled ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block">MinerU parse method</span>
            <select
              aria-label="MinerU parse method"
              value={options.parse_method ?? "auto"}
              disabled={disabled}
              onChange={(event) => updateOption("parse_method", event.target.value)}
              className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            >
              <option value="auto">auto</option>
              <option value="ocr">ocr</option>
              <option value="txt">txt</option>
            </select>
          </label>
          <MinerUTextOption
            label="MinerU backend"
            value={options.backend ?? ""}
            disabled={disabled}
            onChange={(backend) => updateOption("backend", backend)}
          />
          <MinerUTextOption
            label="MinerU device"
            value={options.device ?? ""}
            disabled={disabled}
            onChange={(device) => updateOption("device", device)}
          />
          <MinerUTextOption
            label="MinerU language"
            value={options.lang ?? ""}
            disabled={disabled}
            onChange={(lang) => updateOption("lang", lang)}
          />
          <label className="flex h-10 items-center gap-2 self-end text-sm font-medium text-[#3a4a53]">
            <input
              type="checkbox"
              checked={options.formula ?? true}
              disabled={disabled}
              onChange={(event) => updateOption("formula", event.target.checked)}
            />
            Parse formulas for this document
          </label>
          <label className="flex h-10 items-center gap-2 self-end text-sm font-medium text-[#3a4a53]">
            <input
              type="checkbox"
              checked={options.table ?? true}
              disabled={disabled}
              onChange={(event) => updateOption("table", event.target.checked)}
            />
            Parse tables for this document
          </label>
          <MinerUTextOption
            label="MinerU source"
            value={options.source ?? ""}
            disabled={disabled}
            onChange={(source) => updateOption("source", source)}
          />
          <label className="text-sm font-medium text-[#3a4a53]">
            <span className="mb-1.5 block">MinerU max concurrent files</span>
            <input
              aria-label="MinerU max concurrent files"
              type="number"
              min={1}
              max={8}
              value={options.max_concurrent_files ?? 1}
              disabled={disabled}
              onChange={(event) =>
                updateOption(
                  "max_concurrent_files",
                  Math.max(1, Math.min(Number(event.target.value || 1), 8)),
                )
              }
              className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            />
          </label>
        </div>
      ) : null}
    </section>
  );
}

function MinerUTextOption({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  return (
    <label className="text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block">{label}</span>
      <input
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value.trim() || null)}
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
      />
    </label>
  );
}

function compactMinerUParseOptions(options: MinerUParseOptionsIn): MinerUParseOptionsIn {
  return {
    parse_method: options.parse_method || undefined,
    backend: options.backend || undefined,
    device: options.device || undefined,
    lang: options.lang || undefined,
    formula: options.formula,
    table: options.table,
    source: options.source || undefined,
    max_concurrent_files: options.max_concurrent_files ?? undefined,
  };
}

function StatusSummaryItem({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "active" | "warning";
}) {
  const valueClass =
    tone === "active"
      ? "text-[#176b87]"
      : tone === "warning"
        ? "text-[#8a5a00]"
        : "text-[#1f2933]";

  return (
    <div className="min-w-0">
      <p className="truncate text-xs font-medium uppercase text-[#62717a]">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${valueClass}`}>{value}</p>
    </div>
  );
}

function TabButton({
  id,
  controls,
  selected,
  onSelect,
  onKeyDown,
  label,
  count,
}: {
  id: string;
  controls: string;
  selected: boolean;
  onSelect: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  label: string;
  count: number;
}) {
  return (
    <button
      id={id}
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={controls}
      tabIndex={selected ? 0 : -1}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      className={
        selected
          ? "flex h-11 items-center gap-2 border-b-2 border-[#176b87] px-3 text-sm font-semibold text-[#176b87] outline-none focus:ring-2 focus:ring-[#176b87]"
          : "flex h-11 items-center gap-2 border-b-2 border-transparent px-3 text-sm font-medium text-[#62717a] outline-none hover:text-[#24313a] focus:ring-2 focus:ring-[#176b87]"
      }
    >
      <span>{label}</span>
      <span
        className={
          selected
            ? "rounded-md bg-[#e5f1f5] px-2 py-0.5 text-xs text-[#164f63]"
            : "rounded-md bg-[#edf1f3] px-2 py-0.5 text-xs text-[#62717a]"
        }
      >
        {count}
      </span>
    </button>
  );
}

function TableToolbar({
  searchLabel,
  searchValue,
  searchPlaceholder,
  onSearchChange,
  filteredCount,
  totalCount,
  statusLabel,
  statusValue,
  statusOptions,
  statusPlaceholder = "All",
  onStatusChange,
  hasActiveFilters = false,
  onClearFilters,
}: {
  searchLabel: string;
  searchValue: string;
  searchPlaceholder: string;
  onSearchChange: (value: string) => void;
  filteredCount: number;
  totalCount: number;
  statusLabel?: string;
  statusValue?: string;
  statusOptions?: string[];
  statusPlaceholder?: string;
  onStatusChange?: (value: string) => void;
  hasActiveFilters?: boolean;
  onClearFilters?: () => void;
}) {
  return (
    <div className="flex min-w-0 max-w-full flex-col gap-3 overflow-hidden rounded-md border border-[#d6dde1] bg-white p-3 lg:flex-row lg:items-end lg:justify-between">
      <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row sm:items-end">
        <label className="min-w-0 flex-1 text-sm font-medium text-[#3a4a53]">
          {searchLabel}
          <div className="mt-1 flex h-10 items-center gap-2 rounded-md border border-[#d6dde1] bg-white px-3 focus-within:ring-2 focus-within:ring-[#176b87]">
            <Search className="h-4 w-4 shrink-0 text-[#6f7f87]" aria-hidden="true" />
            <input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder}
              className="min-w-0 flex-1 bg-transparent text-sm text-[#24313a] outline-none placeholder:text-[#8c9aa1]"
            />
          </div>
        </label>
        {statusLabel && statusOptions && onStatusChange ? (
          <label className="min-w-0 text-sm font-medium text-[#3a4a53] sm:w-48">
            {statusLabel}
            <select
              value={statusValue}
              onChange={(event) => onStatusChange(event.target.value)}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dde1] bg-white px-3 text-sm text-[#24313a] outline-none focus:ring-2 focus:ring-[#176b87]"
            >
              <option value="">{statusPlaceholder}</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {titleCase(status)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {onClearFilters ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClearFilters}
            disabled={!hasActiveFilters}
          >
            Clear filters
          </Button>
        ) : null}
        <p className="text-xs font-medium text-[#62717a]" aria-live="polite">
          {filteredCount} of {totalCount}
        </p>
      </div>
    </div>
  );
}

function filterDocuments(documents: DocumentOut[], query: string): DocumentOut[] {
  const normalizedQuery = normalizeSearch(query);
  if (!normalizedQuery) {
    return documents;
  }
  return documents.filter((document) =>
    searchTextMatches(
      [document.filename, document.content_type, document.status, document.id],
      normalizedQuery,
    ),
  );
}

function filterJobs(
  jobs: JobOut[],
  documentsById: Map<string, DocumentOut>,
  query: string,
  status: string,
  liveJobEventsById: LiveJobEventsById = {},
): JobOut[] {
  const normalizedQuery = normalizeSearch(query);
  return jobs.filter((job) => {
    if (status && job.status !== status) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    const document = job.target_id ? documentsById.get(job.target_id) : undefined;
    const parserGroups = jobParserQualityGroups(job);
    const liveEvent = liveJobEventsById[job.id];
    return searchTextMatches(
      [
        job.id,
        job.target_id,
        job.type,
        job.status,
        formatJobName(job, document),
        formatJobType(job.type),
        document?.filename,
        formatMinerUResult(job, liveEvent),
        jobStageText(job, liveEvent),
        ...jobWarnings(job, liveEvent),
        ...(liveEvent?.logs ?? []),
        ...job.logs,
        ...parserGroups.flatMap((group) => [
          group.code,
          group.message,
          ...Object.keys(group.blockTypes),
          ...Object.keys(group.expectedScripts),
          ...Object.keys(group.actions),
          ...group.references,
        ]),
      ],
      normalizedQuery,
    );
  });
}

function filterWarningItems(
  items: ParserQualityWarningOut[],
  query: string,
  codeFilter: string,
): ParserQualityWarningOut[] {
  const normalizedQuery = normalizeSearch(query);
  return items.filter((item) => {
    const code = item.code ?? "parser_warning";
    if (codeFilter && code !== codeFilter) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return searchTextMatches(
      [
        item.chunk_id,
        item.chunk_preview,
        item.code,
        item.message,
        item.block_type,
        item.page,
        warningReferences(item),
        item.source_location,
        item.parser_metadata,
        item.reference_metadata,
        item.warning,
      ],
      normalizedQuery,
    );
  });
}

function normalizeSearch(value: string): string {
  return value.trim().toLowerCase();
}

function searchTextMatches(values: unknown[], normalizedQuery: string): boolean {
  return values.some((value) => stringifySearchValue(value).includes(normalizedQuery));
}

function stringifySearchValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value).toLowerCase();
  }
  try {
    return JSON.stringify(value).toLowerCase();
  } catch {
    return String(value).toLowerCase();
  }
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

function getJobProgress(job: JobOut, liveEvent?: LiveJobEventSnapshot): number {
  const mineru = getMinerUStatus(job.result, liveEvent);
  const stageProgress = getIndexingStageProgress(job.result, liveEvent);
  const progress =
    job.status === "running"
      ? (liveEvent?.progress ?? stageProgress ?? mineru?.progress ?? job.progress)
      : (job.progress ?? stageProgress ?? mineru?.progress);
  const rounded = Math.max(0, Math.min(Math.round(progress), 100));

  if (job.status === "running") {
    return Math.min(rounded, 99);
  }
  return rounded;
}

function getIndexingStageProgress(
  result: Record<string, unknown>,
  liveEvent?: LiveJobEventSnapshot,
): number | null {
  if (liveEvent?.stage?.progress !== null && liveEvent?.stage?.progress !== undefined) {
    return liveEvent.stage.progress;
  }
  const stage = result.indexing_stage;
  if (!isRecord(stage) || typeof stage.progress !== "number") {
    return null;
  }
  return stage.progress;
}

function formatMinerUResult(job: JobOut, liveEvent?: LiveJobEventSnapshot): string | null {
  const mineru = getMinerUStatus(job.result, liveEvent);
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

function jobStageText(job: JobOut | undefined, liveEvent?: LiveJobEventSnapshot): string | null {
  if (liveEvent?.stage) {
    const parts = [liveEvent.stage.label, liveEvent.stage.detail].filter(Boolean);
    if (liveEvent.stage.chunkCount !== null) {
      parts.push(`${liveEvent.stage.chunkCount} chunks`);
    }
    return parts.length ? parts.join(" · ") : null;
  }
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

function jobWarnings(job: JobOut | undefined, liveEvent?: LiveJobEventSnapshot): string[] {
  if (liveEvent?.warnings.length) {
    return liveEvent.warnings;
  }
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
  const totalWarnings = groups.reduce((total, group) => total + group.warningCount, 0);

  return (
    <details className="rounded-md border border-[#ead9a7] bg-[#fffaf0] p-2 text-[#5f4600]">
      <summary className="cursor-pointer font-medium">
        Parser warning details · {groups.length} types · {totalWarnings} grouped warnings
      </summary>
      <div className="mt-2 max-h-72 space-y-3 overflow-auto pr-1">
        {groups.map((group) => (
          <div key={group.code} className="space-y-1 border-t border-[#ead9a7] pt-2 first:border-t-0 first:pt-0">
            <p className="font-medium text-[#3a2f12]">
              {group.code} · {group.chunkCount} grouped chunk rows · {group.warningCount} warnings
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
  canFixWarnings,
  isFixingWarnings,
  fixStatus,
  fixError,
  repairPlan,
  onFixWarnings,
  onClose,
}: {
  jobName: string;
  details: JobQualityWarningsOut | undefined;
  isLoading: boolean;
  error: Error | null;
  canFixWarnings: boolean;
  isFixingWarnings: boolean;
  fixStatus: string | null;
  fixError: Error | null;
  repairPlan: Record<string, unknown> | null;
  onFixWarnings: () => void;
  onClose: () => void;
}) {
  const warningHeadingRef = useRef<HTMLHeadingElement>(null);
  const [warningSearch, setWarningSearch] = useState("");
  const [warningCodeFilter, setWarningCodeFilter] = useState("");
  const countEntries = warningCountEntries(details?.warning_counts ?? {});
  const indexQuality = details ? indexQualitySummary(details) : null;
  const warningItems = useMemo(() => details?.items ?? [], [details?.items]);
  const warningCodeOptions = useMemo(
    () =>
      Array.from(new Set(warningItems.map((item) => item.code ?? "parser_warning"))).sort((left, right) =>
        left.localeCompare(right),
      ),
    [warningItems],
  );
  const filteredWarningItems = useMemo(
    () => filterWarningItems(warningItems, warningSearch, warningCodeFilter),
    [warningCodeFilter, warningItems, warningSearch],
  );
  const visibleWarningItems = useMemo(
    () => filteredWarningItems.slice(0, WARNING_VISIBLE_ROW_LIMIT),
    [filteredWarningItems],
  );
  const hiddenWarningCount = Math.max(filteredWarningItems.length - visibleWarningItems.length, 0);
  const warningColumns = useMemo<ColumnDef<ParserQualityWarningOut>[]>(
    () => [
      {
        accessorKey: "code",
        header: "Warning",
        cell: ({ row }) => {
          const tone = warningDisplayTone(row.original);

          return (
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone.className}`}
                >
                  {warningDisplayLabel(row.original)}
                </span>
                <span
                  className={`rounded-md border px-2 py-1 text-xs font-semibold ${tone.className}`}
                >
                  {tone.label}
                </span>
              </div>
              {row.original.message ? (
                <p className="break-words text-sm text-[#1f2933]">{row.original.message}</p>
              ) : null}
              {tone.note ? <p className="text-xs text-[#235c2f]">{tone.note}</p> : null}
            </div>
          );
        },
      },
      {
        accessorKey: "page",
        header: "Location",
        cell: ({ row }) => {
          const metadataLine = [
            row.original.page != null ? `Page ${row.original.page}` : null,
            row.original.block_type,
            warningReferences(row.original),
          ]
            .filter(Boolean)
            .join(" · ");

          return (
            <div className="min-w-0 space-y-1 text-xs text-[#62717a]">
              <p className="truncate font-medium text-[#3a4a53]">
                {metadataLine || "No location metadata"}
              </p>
              <p className="truncate">{row.original.chunk_id}</p>
            </div>
          );
        },
      },
      {
        accessorKey: "chunk_preview",
        header: "Preview",
        cell: ({ row }) => (
          <p className="line-clamp-3 text-xs leading-5 text-[#62717a]">
            {row.original.chunk_preview || "No preview available."}
          </p>
        ),
      },
      {
        id: "metadata",
        header: "Metadata",
        cell: ({ row }) => <WarningMetadataCell item={row.original} />,
      },
    ],
    [],
  );

  useEffect(() => {
    warningHeadingRef.current?.focus();
  }, []);

  return (
    <div
      className="mt-4 min-w-0 max-w-full overflow-hidden rounded-md border border-[#d6dde1] bg-[#fbfcfd] p-4"
      role="region"
      aria-labelledby="warning-details-title"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h4
            id="warning-details-title"
            ref={warningHeadingRef}
            tabIndex={-1}
            className="truncate text-sm font-semibold text-[#1f2933] outline-none"
          >
            Warning details
          </h4>
          <p className="truncate text-xs text-[#62717a]">{jobName}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onFixWarnings}
            disabled={!canFixWarnings || isFixingWarnings}
            aria-label={`Fix warnings for ${jobName}`}
          >
            {isFixingWarnings ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            )}
            Fix warnings
          </Button>
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
      </div>

      {isLoading ? (
        <p className="mt-4 text-sm text-[#62717a]" role="status" aria-live="polite">
          Loading warning details.
        </p>
      ) : error ? (
        <p className="mt-4 text-sm text-[#8a1f11]">{error.message}</p>
      ) : details ? (
        <div className="mt-4 min-w-0 space-y-4">
          <div className="flex flex-wrap gap-2 text-xs">
            {countEntries.length ? (
              countEntries.map(([code, count]) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setWarningCodeFilter(code)}
                  aria-pressed={warningCodeFilter === code}
                  aria-label={`Filter warnings by ${code}`}
                  className={
                    warningCodeFilter === code
                      ? "rounded-md border border-[#176b87] bg-[#e5f1f5] px-2 py-1 text-[#164f63] outline-none focus:ring-2 focus:ring-[#176b87]"
                      : "rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-[#705000] outline-none hover:border-[#d1a837] focus:ring-2 focus:ring-[#176b87]"
                  }
                >
                  {code}={count}
                </button>
              ))
            ) : (
              <span className="text-[#62717a]">No counted parser warnings.</span>
            )}
            <span className="rounded-md border border-[#d6dde1] bg-white px-2 py-1 text-[#3a4a53]">
              counted_affected_chunks={details.affected_chunks}
            </span>
            <span className="rounded-md border border-[#d6dde1] bg-white px-2 py-1 text-[#3a4a53]">
              display_rows={details.total}
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
          {warningItems.length ? (
            <div className="space-y-3">
              <TableToolbar
                searchLabel="Search warning details"
                searchValue={warningSearch}
                searchPlaceholder="Chunk, preview, page, reference, or metadata"
                onSearchChange={setWarningSearch}
                filteredCount={filteredWarningItems.length}
                totalCount={warningItems.length}
                statusLabel="Warning type"
                statusValue={warningCodeFilter}
                statusOptions={warningCodeOptions}
                statusPlaceholder="All warning types"
                onStatusChange={setWarningCodeFilter}
                hasActiveFilters={Boolean(warningSearch.trim() || warningCodeFilter)}
                onClearFilters={() => {
                  setWarningSearch("");
                  setWarningCodeFilter("");
                }}
              />
              <DataTable
                ariaLabel="Warning detail table"
                columns={warningColumns}
                data={visibleWarningItems}
                emptyTitle="No matching warnings"
                emptyDescription="Clear the search or warning type filter to see every warning."
                className="max-h-96 min-w-0 max-w-full overflow-auto"
              />
              {hiddenWarningCount ? (
                <p className="text-xs text-[#62717a]" role="status">
                  Showing first {visibleWarningItems.length} of {filteredWarningItems.length} matching warnings. Refine search or warning type to narrow the list.
                </p>
              ) : null}
            </div>
          ) : null}
          <p className="min-h-5 text-sm text-[#62717a]" role="status">
            {fixStatus ?? fixError?.message}
          </p>
          {repairPlan ? <RepairPlanSummary plan={repairPlan} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function isAcceptedRecoveryWarning(item: ParserQualityWarningOut) {
  const warningRecord = item.warning as Record<string, unknown> | null | undefined;

  return (
    item.code === "recovered_text_from_disallowed_block" ||
    warningRecord?.quality_gate_action === "accepted_recovery" ||
    warningRecord?.suppressed_from_counts === true
  );
}

function warningDisplayLabel(item: ParserQualityWarningOut) {
  return isAcceptedRecoveryWarning(item) ? "Recovered text" : (item.code ?? "parser_warning");
}

function warningDisplayTone(item: ParserQualityWarningOut) {
  return isAcceptedRecoveryWarning(item)
    ? {
        label: "Accepted recovery",
        className: "border-[#5ca66b] bg-[#ecf8ee] text-[#235c2f]",
        note: "This row is audit evidence, not a counted parser warning.",
      }
    : {
        label: "Parser warning",
        className: "border-[#e2c46b] bg-[#fff8df] text-[#705000]",
        note: "",
      };
}

function WarningMetadataCell({ item }: { item: ParserQualityWarningOut }) {
  const sourcePreview = compactRecordPreview(item.source_location, ["page", "artifact", "artifact_ref"]);
  const parserPreview = compactRecordPreview(item.parser_metadata, [
    "chunk_index",
    "artifact_ref",
    "block_type",
  ]);
  const warningPreview = compactRecordPreview(item.warning, ["code", "action", "expected_script"]);

  return (
    <div className="min-w-0 space-y-1 text-xs text-[#62717a]">
      <MetadataPreviewLine label="Source" value={sourcePreview} />
      <MetadataPreviewLine label="Parser" value={parserPreview} />
      <MetadataPreviewLine label="Warning" value={warningPreview} />
      <details className="mt-1">
        <summary className="cursor-pointer text-[#176b87]">Details</summary>
        <dl className="mt-2 max-h-40 space-y-2 overflow-auto rounded-md border border-[#edf1f3] bg-[#fbfcfd] p-2">
          <MetadataDetail label="Source" value={item.source_location} />
          <MetadataDetail label="Parser" value={item.parser_metadata} />
          <MetadataDetail label="Reference" value={item.reference_metadata} />
          <MetadataDetail label="Warning" value={item.warning} />
        </dl>
      </details>
    </div>
  );
}

function MetadataPreviewLine({ label, value }: { label: string; value: string }) {
  return (
    <p className="min-w-0 truncate">
      <span className="font-medium text-[#3a4a53]">{label}</span> {value || "None"}
    </p>
  );
}

function MetadataDetail({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <dt className="font-medium text-[#3a4a53]">{label}</dt>
      <dd className="break-words font-mono text-[11px] leading-5 text-[#62717a]">
        {formatRecordValue(value)}
      </dd>
    </div>
  );
}

function compactRecordPreview(record: Record<string, unknown> | null, preferredKeys: string[]): string {
  if (!record || !Object.keys(record).length) {
    return "None";
  }
  const entries = preferredKeys
    .map((key) => [key, record[key]] as const)
    .filter((entry): entry is readonly [string, string | number | boolean] =>
      typeof entry[1] === "string" || typeof entry[1] === "number" || typeof entry[1] === "boolean",
    );
  const fallbackEntries = Object.entries(record).filter(
    (entry): entry is [string, string | number | boolean] =>
      typeof entry[1] === "string" || typeof entry[1] === "number" || typeof entry[1] === "boolean",
  );
  const previewEntries = (entries.length ? entries : fallbackEntries).slice(0, 2);
  return previewEntries.map(([key, value]) => `${key}=${String(value)}`).join(", ") || "Available";
}

function RepairPlanSummary({ plan }: { plan: Record<string, unknown> }) {
  const summary = stringValue(plan.summary);
  const steps = repairPlanSteps(plan.steps);
  const aiSuggestion = repairPlanAiSuggestion(plan.ai_suggestion);

  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-3 text-sm text-[#24313a]">
      <p className="font-medium">Repair plan</p>
      {summary ? <p className="mt-1 text-xs text-[#62717a]">{summary}</p> : null}
      {steps.length ? (
        <ul className="mt-3 space-y-2 text-xs text-[#3a4a53]">
          {steps.map((step) => (
            <li key={step.code} className="rounded-md border border-[#edf1f3] p-2">
              <p className="font-medium text-[#1f2933]">
                {step.code} · {step.count} · {step.action}
              </p>
              <p className="mt-1">{step.reason}</p>
              <p className="mt-1 text-[#62717a]">{step.expectedEffect}</p>
            </li>
          ))}
        </ul>
      ) : null}
      {aiSuggestion ? <p className="mt-3 text-xs text-[#62717a]">{aiSuggestion}</p> : null}
    </div>
  );
}

function repairPlanSteps(value: unknown): Array<{
  code: string;
  count: number;
  action: string;
  reason: string;
  expectedEffect: string;
}> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const code = stringValue(item.code);
      if (!code) {
        return null;
      }
      return {
        code,
        count: numberValue(item.count),
        action: stringValue(item.action) ?? "repair",
        reason: stringValue(item.reason) ?? "",
        expectedEffect: stringValue(item.expected_effect) ?? "",
      };
    })
    .filter((item): item is {
      code: string;
      count: number;
      action: string;
      reason: string;
      expectedEffect: string;
    } => item !== null);
}

function repairPlanAiSuggestion(value: unknown): string | null {
  if (!isRecord(value)) {
    return null;
  }
  const status = stringValue(value.status);
  if (!status) {
    return null;
  }
  if (status === "succeeded") {
    const suggestion = isRecord(value.suggestion) ? value.suggestion : {};
    const summary = stringValue(suggestion.summary);
    return summary ? `AI suggestion: ${summary}` : "AI suggestion received.";
  }
  const reason = stringValue(value.reason);
  return reason ? `AI suggestion ${status}: ${reason}` : `AI suggestion ${status}.`;
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

function getMinerUStatus(result: Record<string, unknown>, liveEvent?: LiveJobEventSnapshot): {
  status: string | null;
  progress: number | null;
  detail: string | null;
} | null {
  if (liveEvent?.mineru) {
    return liveEvent.mineru;
  }
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

function numberFromPayload(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
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

function formatRecordValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value) && value.length === 0) {
    return "None";
  }
  if (isRecord(value) && !Object.keys(value).length) {
    return "None";
  }
  return JSON.stringify(value);
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
    <section className="min-w-0 max-w-full overflow-hidden">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-[#176b87]" aria-hidden="true" />
        <h3 className="truncate text-base font-semibold text-[#1f2933]">{title}</h3>
      </div>
      {children}
    </section>
  );
}

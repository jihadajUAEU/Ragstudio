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
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock,
  Copy,
  FileWarning,
  FileText,
  FileUp,
  ListChecks,
  Loader2,
  MoreVertical,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Wrench,
  X,
  XCircle,
} from "lucide-react";

import { apiClient, DEFAULT_PARSER_MODE, FIRST_LIST_PAGE } from "../../api/client";
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
import { titleCase } from "../../lib/utils";

const queryKeys = {
  documents: ["documents"],
  jobs: ["jobs"],
} as const;

type DocumentsTab = "documents" | "jobs";
const WARNING_VISIBLE_ROW_LIMIT = 200;
const DOCUMENTS_TABLE_PAGE_SIZE = 25;
const JOBS_TABLE_PAGE_SIZE = 25;
const JOB_REFRESH_INTERVAL_OPTIONS = [5_000, 10_000, 30_000] as const;
type LiveJobEventsById = Record<string, LiveJobEventSnapshot>;
type DomainMetadataSuggestion = Awaited<ReturnType<typeof apiClient.suggestDomainMetadata>>;

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

type DocumentRow = DocumentOut & {
  index_contract?: Record<string, unknown> | null;
  latest_job?: Record<string, unknown> | null;
  latestJob?: Record<string, unknown> | null;
  latest_result?: Record<string, unknown> | null;
  latestResult?: Record<string, unknown> | null;
  latest_job_result?: Record<string, unknown> | null;
  latestJobResult?: Record<string, unknown> | null;
};

interface DocumentPreprocessingStatus {
  label: string;
  tone: "neutral" | "active" | "success" | "danger";
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
  const [documentsPage, setDocumentsPage] = useState(1);
  const [documentsPageSize, setDocumentsPageSize] = useState(DOCUMENTS_TABLE_PAGE_SIZE);
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [jobWarningOnly, setJobWarningOnly] = useState(false);
  const [jobsAutoRefresh, setJobsAutoRefresh] = useState(true);
  const [jobsRefreshIntervalMs, setJobsRefreshIntervalMs] = useState<number>(10_000);
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsPageSize, setJobsPageSize] = useState(JOBS_TABLE_PAGE_SIZE);
  const [liveJobEventsById, setLiveJobEventsById] = useState<LiveJobEventsById>({});
  const [visionSuggestion, setVisionSuggestion] = useState<DomainMetadataSuggestion | null>(null);
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: () => apiClient.jobs(FIRST_LIST_PAGE),
    refetchInterval: (query) =>
      hasActiveJobs(query.state.data?.items ?? [])
        ? 2_000
        : jobsAutoRefresh
          ? jobsRefreshIntervalMs
          : false,
  });
  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const activeJobs = hasActiveJobs(jobs);
  const activeJobIds = useMemo(() => jobs.filter(isActiveJob).map((job) => job.id), [jobs]);
  const activeJobIdsKey = activeJobIds.join("|");
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents,
    queryFn: () => apiClient.documents(FIRST_LIST_PAGE),
    refetchInterval: activeJobs ? 2000 : false,
  });
  const documents = useMemo(
    () => (documentsQuery.data?.items ?? []) as DocumentRow[],
    [documentsQuery.data?.items],
  );
  const uploadDocument = useMutation({
    mutationFn: apiClient.uploadDocument,
    onSuccess: () => {
      setFile(null);
      setVisionSuggestion(null);
      analyzeWithVision.reset();
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
      setActiveTab("jobs");
    },
  });
  const analyzeWithVision = useMutation({
    mutationFn: apiClient.suggestDomainMetadata,
    onSuccess: (suggestion) => {
      setVisionSuggestion(suggestion);
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
      if (!document.latest_index_options) {
        return;
      }
      setReindexedFilename(document.filename);
      reindexDocument.mutate({
        documentId: document.id,
        options: document.latest_index_options,
      });
    },
    [reindexDocument],
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
  const latestJobsByDocumentId = useMemo(() => {
    const map = new Map<string, JobOut>();
    jobs.forEach((job) => {
      if (!job.target_id) {
        return;
      }
      const current = map.get(job.target_id);
      if (!current || shouldPreferDocumentJob(job, current)) {
        map.set(job.target_id, job);
      }
    });
    return map;
  }, [jobs]);
  const filteredDocuments = useMemo(
    () => filterDocuments(documents, documentSearch),
    [documentSearch, documents],
  );
  const currentDocumentsPage = clampedTablePage(
    documentsPage,
    filteredDocuments.length,
    documentsPageSize,
  );
  const visibleDocuments = useMemo(
    () => paginateRows(filteredDocuments, currentDocumentsPage, documentsPageSize),
    [currentDocumentsPage, documentsPageSize, filteredDocuments],
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
  const jobMetrics = useMemo(() => summarizeJobs(jobs), [jobs]);
  const filteredJobs = useMemo(
    () =>
      filterJobs(
        jobs,
        documentsById,
        jobSearch,
        jobStatusFilter,
        jobWarningOnly,
        liveJobEventsById,
      ),
    [documentsById, jobSearch, jobStatusFilter, jobWarningOnly, jobs, liveJobEventsById],
  );
  const currentJobsPage = clampedTablePage(jobsPage, filteredJobs.length, jobsPageSize);
  const visibleJobs = useMemo(
    () => paginateRows(filteredJobs, currentJobsPage, jobsPageSize),
    [currentJobsPage, filteredJobs, jobsPageSize],
  );
  const selectedWarningJob = useMemo(
    () => jobs.find((job) => job.id === selectedWarningJobId),
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

    const sources = jobIds.flatMap((jobId) => {
      const source = apiClient.createJobEventSource(jobId);
      if (!source) {
        return [];
      }
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
      ["job_stage", "job_status", "stage", "progress", "log", "status"].forEach((eventName) => {
        source.addEventListener(eventName, handleEvent);
      });
      return [source];
    });

    return () => {
      sources.forEach((source) => source.close());
    };
  }, [activeJobIdsKey, queryClient]);

  const documentColumns = useMemo<ColumnDef<DocumentRow>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "Document",
        cell: ({ row }) => {
          const preprocessingStatus = getDocumentPreprocessingStatus(
            row.original,
            latestJobsByDocumentId.get(row.original.id),
          );

          return (
            <div className="min-w-0">
              <p className="truncate font-medium">{row.original.filename}</p>
              <p className="truncate text-xs text-[#6f7f87]">{row.original.content_type}</p>
              {preprocessingStatus ? (
                <p
                  className={`mt-1 inline-flex max-w-full rounded-md border px-2 py-0.5 text-xs font-medium leading-4 ${documentPreprocessingToneClass(
                    preprocessingStatus.tone,
                  )}`}
                >
                  <span className="max-w-full whitespace-normal break-words">
                    {preprocessingStatus.label}
                  </span>
                </p>
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
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const document = row.original;
          const isDeleting = deleteDocument.isPending && deleteDocument.variables === document.id;
          const isReindexing =
            reindexDocument.isPending && reindexDocument.variables?.documentId === document.id;
          const canReindex = document.latest_index_options != null;

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
      latestJobsByDocumentId,
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
              <p className="truncate font-semibold text-[var(--rs-ink)]">
                {formatJobName(row.original, document)}
              </p>
              <code className="block truncate text-xs text-[var(--rs-muted)]">
                {formatJobType(row.original.type)} · {row.original.id}
              </code>
            </div>
          );
        },
      },
      {
        id: "document",
        header: "Document",
        cell: ({ row }) => {
          const document = row.original.target_id
            ? documentsById.get(row.original.target_id)
            : undefined;

          return (
            <div className="min-w-0">
              <p className="truncate font-medium text-[var(--rs-text)]">
                {document?.filename ?? row.original.target_id ?? "Workspace"}
              </p>
              <p className="truncate text-xs text-[var(--rs-muted)]">
                {document?.content_type ?? formatJobType(row.original.type)}
              </p>
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
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => {
          const liveEvent = liveJobEventsById[row.original.id];
          const progress = getJobProgress(row.original, liveEvent);
          const barClass =
            row.original.status === "failed" ? "bg-[var(--rs-danger)]" : "bg-[var(--rs-accent)]";

          return (
            <div className="min-w-32">
              <p className="mb-1 text-xs font-medium text-[var(--rs-text)]">{progress}%</p>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--rs-field)]">
                <div
                  className={`h-full rounded-full ${barClass}`}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          );
        },
      },
      {
        id: "stage",
        header: "Stage (MinerU)",
        cell: ({ row }) => {
          const liveEvent = liveJobEventsById[row.original.id];
          const stageText = jobStageText(row.original, liveEvent);
          const mineru = getMinerUStatus(row.original.result, liveEvent);
          const mineruStatus = formatMinerUResult(row.original, liveEvent);

          return (
            <div className="min-w-0 text-xs text-[var(--rs-text)]">
              <p className="line-clamp-2 font-medium">
                {stageText ?? (mineru?.status ? `MinerU ${mineru.status}` : mineruStatus) ?? "No stage reported"}
              </p>
              {mineruStatus && (stageText || mineru?.status) ? (
                <p className="mt-1 truncate text-[var(--rs-muted)]">MinerU: {mineruStatus}</p>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: "logs",
        header: "Latest Log Preview",
        cell: ({ row }) => {
          const liveEvent = liveJobEventsById[row.original.id];
          const latestLog = liveEvent?.logs.at(-1) ?? row.original.logs.at(-1) ?? "No logs";
          const warnings = jobWarnings(row.original, liveEvent).slice(0, 2);
          const parserGroups = jobParserQualityGroups(row.original);

          return (
            <div className="min-w-0 space-y-1 text-xs leading-5 text-[var(--rs-text)]">
              <p className="line-clamp-2">{latestLog}</p>
              {warnings.map((warning) => (
                <p key={warning} className="line-clamp-1 text-[var(--rs-warning)]">
                  {warning}
                </p>
              ))}
              <ParserQualityDetails groups={parserGroups} />
            </div>
          );
        },
      },
      {
        id: "warnings",
        header: "Warnings",
        cell: ({ row }) => {
          const liveEvent = liveJobEventsById[row.original.id];
          const warningCount = jobWarningCount(row.original, liveEvent);
          const hasWarnings = warningCount > 0;

          return (
            <div
              className={`inline-flex items-center gap-2 text-sm font-semibold ${
                hasWarnings ? "text-[var(--rs-warning)]" : "text-[var(--rs-muted)]"
              }`}
            >
              {hasWarnings ? (
                <FileWarning className="h-4 w-4" aria-hidden="true" />
              ) : (
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
              )}
              {warningCount}
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const document = row.original.target_id
            ? documentsById.get(row.original.target_id)
            : undefined;
          const canInspectWarnings = hasInspectableQualityWarnings(row.original);

          return (
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setSelectedWarningJobId(row.original.id)}
                disabled={!canInspectWarnings}
                aria-label={`Inspect warning details for ${formatJobName(row.original, document)}`}
              >
                {canInspectWarnings ? "Inspect warnings" : "No warnings"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Open job actions for ${formatJobName(row.original, document)}`}
              >
                <MoreVertical className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          );
        },
      },
    ],
    [documentsById, liveJobEventsById],
  );

  const isRefreshing = documentsQuery.isFetching || jobsQuery.isFetching;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5">
      <section className="flex flex-col gap-4 border-b border-[var(--rs-line)] pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-3xl font-semibold tracking-normal text-[var(--rs-ink)]">
            Documents
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--rs-text)]">
            Upload source files, watch parsing jobs, and open the evidence trail before chunks move
            into retrieval.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={() => activateTab("jobs", true)}>
            <Activity className="h-4 w-4" aria-hidden="true" />
            Jobs
          </Button>
          <Button variant="secondary" onClick={refresh} disabled={isRefreshing}>
            {isRefreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            )}
            Refresh
          </Button>
        </div>
      </section>

      {activeTab === "documents" ? (
      <section className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
      <div className="min-w-0 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <FileUp className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
              <h3 className="truncate text-base font-semibold text-[var(--rs-ink)]">New source</h3>
            </div>
            <p className="mt-1 text-sm text-[var(--rs-muted)]">
              Vision metadata is required so the index job starts with an explicit domain policy.
            </p>
          </div>
          <span className="inline-flex w-fit rounded-full border border-[var(--rs-line)] bg-[var(--rs-field)] px-2.5 py-1 text-xs font-medium text-[var(--rs-text)]">
            {DEFAULT_PARSER_MODE}
          </span>
        </div>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (file && visionSuggestion) {
              uploadDocument.mutate({
                file,
                options: {
                  parser_mode: DEFAULT_PARSER_MODE,
                  domain_metadata: visionSuggestion.domain_metadata,
                },
              });
            }
          }}
        >
          <div className="grid gap-3">
            <label className="min-w-0 text-sm font-medium text-[var(--rs-text)]">
              <span className="mb-1.5 block truncate">Upload file</span>
              <input
                ref={fileInputRef}
                type="file"
                className="block h-11 w-full min-w-0 rounded-md border border-[var(--rs-line-strong)] bg-[var(--rs-paper)] text-sm text-[var(--rs-ink)] file:mr-3 file:h-full file:border-0 file:bg-[var(--rs-field)] file:px-3 file:text-sm file:font-medium file:text-[var(--rs-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--rs-accent)]"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setVisionSuggestion(null);
                  analyzeWithVision.reset();
                  uploadDocument.reset();
                }}
                disabled={uploadDocument.isPending || analyzeWithVision.isPending}
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              disabled={!file || analyzeWithVision.isPending || uploadDocument.isPending}
              onClick={() => {
                if (file) {
                  analyzeWithVision.mutate({ file });
                }
              }}
            >
              {analyzeWithVision.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-4 w-4" aria-hidden="true" />
              )}
              Analyze with vision
            </Button>
            {visionSuggestion ? (
              <span className="text-sm font-medium text-[#1f6f43]">
                Vision metadata generated
              </span>
            ) : (
              <span className="text-sm text-[#62717a]">
                Vision analysis required before upload.
              </span>
            )}
          </div>
          {visionSuggestion ? (
            <div className="rounded-md border border-[#cfe3d5] bg-[#f6fbf7] p-3 text-sm text-[#24313a]">
              <div className="font-medium">{visionSuggestion.domain_metadata.domain}</div>
              <div className="mt-1 text-[#62717a]">
                {visionSuggestion.domain_metadata.document_type ?? "document"} · Confidence{" "}
                {Math.round((visionSuggestion.confidence ?? 0) * 100)}%
              </div>
              {visionSuggestion.evidence_pages.length > 0 ? (
                <div className="mt-1 text-[#62717a]">
                  Evidence pages: {visionSuggestion.evidence_pages.join(", ")}
                </div>
              ) : null}
            </div>
          ) : null}
          {analyzeWithVision.error ? (
            <p className="text-sm text-[#a63d2a]" role="alert">
              {analyzeWithVision.error.message}
            </p>
          ) : null}
          <div className="flex justify-end">
              <Button
                type="submit"
                variant={file && visionSuggestion ? "default" : "secondary"}
                disabled={
                  !file ||
                  !visionSuggestion ||
                analyzeWithVision.isPending ||
                uploadDocument.isPending
              }
            >
              {uploadDocument.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Upload className="h-4 w-4" aria-hidden="true" />
              )}
              Upload and index
            </Button>
          </div>
        </form>
        <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
          {uploadDocument.isSuccess ? "Uploaded" : uploadDocument.error?.message}
        </p>
      </div>

      <OperationsStatusStrip
        documentsCount={documents.length}
        activeJobCount={activeJobCount}
        warningJobCount={warningJobCount}
        latestWarningLabel={
          latestWarningJob ? formatJobName(latestWarningJob, latestWarningDocument) : null
        }
        onViewJobs={() => activateTab("jobs", true)}
      />
      </section>
      ) : null}

      {deleteDocument.isSuccess ||
      deleteDocument.error ||
      reindexDocument.isSuccess ||
      reindexDocument.error ? (
        <div className="grid gap-1 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] px-3 py-2">
          <p className="min-h-5 text-sm text-[var(--rs-muted)]" role="status">
            {deleteDocument.isSuccess ? `Deleted ${deletedFilename}` : deleteDocument.error?.message}
          </p>
          <p className="min-h-5 text-sm text-[var(--rs-muted)]" role="status">
            {reindexDocument.isSuccess
              ? `Reindex queued for ${reindexedFilename}`
              : reindexDocument.error?.message}
          </p>
        </div>
      ) : null}

      <section
        className="min-w-0 max-w-full overflow-hidden rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] shadow-sm"
        aria-label="Documents workspace"
      >
        <div className="flex flex-col gap-3 border-b border-[var(--rs-line)] p-4 lg:flex-row lg:items-center lg:justify-between">
        <div
          role="tablist"
          aria-label="Document workspace sections"
          className="flex min-w-0 max-w-full flex-wrap gap-2 overflow-hidden"
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
        <p className="text-xs font-medium text-[var(--rs-muted)]" aria-live="polite">
          {activeTab === "documents"
            ? `${visibleDocuments.length} of ${filteredDocuments.length} visible documents`
            : `${visibleJobs.length} of ${filteredJobs.length} visible jobs`}
        </p>
        </div>

        <div className="p-4">
        <div
          id="documents-panel"
          ref={documentsPanelRef}
          role="tabpanel"
          aria-labelledby="documents-tab"
          tabIndex={-1}
          hidden={activeTab !== "documents"}
          className="min-w-0 max-w-full overflow-hidden"
        >
          <Panel title="Document evidence sources" icon={FileText}>
          <div className="flex flex-col gap-3">
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
                  onSearchChange={(value) => {
                    setDocumentSearch(value);
                    setDocumentsPage(1);
                  }}
                  filteredCount={filteredDocuments.length}
                  totalCount={documents.length}
                  hasActiveFilters={Boolean(documentSearch.trim())}
                  onClearFilters={() => {
                    setDocumentSearch("");
                    setDocumentsPage(1);
                  }}
                />
                <DataTable
                  ariaLabel="Documents table"
                  columns={documentColumns}
                  data={visibleDocuments}
                  emptyTitle={documents.length ? "No matching documents" : "No documents"}
                  emptyDescription={
                    documents.length
                      ? "Clear the search to see every uploaded file."
                      : "Uploaded files will appear here."
                  }
                  pagination={{
                    page: currentDocumentsPage,
                    pageSize: documentsPageSize,
                    totalItems: filteredDocuments.length,
                    onPageChange: setDocumentsPage,
                    onPageSizeChange: (pageSize) => {
                      setDocumentsPageSize(pageSize);
                      setDocumentsPage(1);
                    },
                    itemLabel: "documents",
                  }}
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
          <Panel title="Ingestion jobs and warnings" icon={Activity}>
          <div className="flex flex-col gap-3">
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
              <JobsMetricStrip metrics={jobMetrics} />
              <JobsToolbar
                searchValue={jobSearch}
                statusValue={jobStatusFilter}
                statusOptions={jobStatusOptions}
                warningOnly={jobWarningOnly}
                autoRefresh={jobsAutoRefresh}
                refreshIntervalMs={jobsRefreshIntervalMs}
                filteredCount={filteredJobs.length}
                totalCount={jobs.length}
                hasActiveFilters={Boolean(jobSearch.trim() || jobStatusFilter || jobWarningOnly)}
                onSearchChange={(value) => {
                  setJobSearch(value);
                  setJobsPage(1);
                  setSelectedWarningJobId(null);
                }}
                onStatusChange={(value) => {
                  setJobStatusFilter(value);
                  setJobsPage(1);
                  setSelectedWarningJobId(null);
                }}
                onWarningOnlyChange={(checked) => {
                  setJobWarningOnly(checked);
                  setJobsPage(1);
                  setSelectedWarningJobId(null);
                }}
                onAutoRefreshChange={setJobsAutoRefresh}
                onRefreshIntervalChange={setJobsRefreshIntervalMs}
                onClearFilters={() => {
                  setJobSearch("");
                  setJobStatusFilter("");
                  setJobWarningOnly(false);
                  setJobsPage(1);
                  setSelectedWarningJobId(null);
                }}
              />
              <DataTable
                ariaLabel="Jobs table"
                columns={jobColumns}
                data={visibleJobs}
                emptyTitle={jobs.length ? "No matching jobs" : "No jobs"}
                emptyDescription={
                  jobs.length
                    ? "Clear the search or status filter to see every job."
                    : "Upload and indexing jobs will appear here."
                }
                pagination={{
                  page: currentJobsPage,
                  pageSize: jobsPageSize,
                  totalItems: filteredJobs.length,
                  onPageChange: (page) => {
                    setJobsPage(page);
                    setSelectedWarningJobId(null);
                  },
                  onPageSizeChange: (pageSize) => {
                    setJobsPageSize(pageSize);
                    setJobsPage(1);
                    setSelectedWarningJobId(null);
                  },
                  itemLabel: "jobs",
                }}
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
              job={selectedWarningJob}
              document={selectedWarningDocument}
              liveEvent={
                selectedWarningJobId ? liveJobEventsById[selectedWarningJobId] : undefined
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
          </div>
          </Panel>
        </div>
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

function jobWarningCount(job: JobOut, liveEvent?: LiveJobEventSnapshot): number {
  const liveWarningCount = liveEvent?.warnings.length ?? 0;
  const jobWarningTotal = jobWarnings(job, liveEvent).length;
  const parserWarningTotal = jobParserQualityGroups(job).reduce(
    (total, group) => total + group.warningCount,
    0,
  );
  const parserCountTotal = warningCountEntries(parserQualityWarningCounts(job.result)).reduce(
    (total, [, count]) => total + count,
    0,
  );
  return Math.max(liveWarningCount, jobWarningTotal, parserWarningTotal, parserCountTotal);
}

function summarizeJobs(jobs: JobOut[]) {
  return {
    total: jobs.length,
    running: jobs.filter(isActiveJob).length,
    succeeded: jobs.filter((job) => job.status === "succeeded").length,
    failed: jobs.filter((job) => job.status === "failed").length,
    warnings: jobs.filter(hasInspectableQualityWarnings).length,
  };
}

function shouldPreferDocumentJob(candidate: JobOut, current: JobOut): boolean {
  if (isActiveJob(candidate) !== isActiveJob(current)) {
    return isActiveJob(candidate);
  }
  if (candidate.type === "index_document" && current.type !== "index_document") {
    return true;
  }
  return false;
}

function getDocumentPreprocessingStatus(
  document: DocumentRow,
  relatedJob?: JobOut,
): DocumentPreprocessingStatus | null {
  const documentRecord = document as unknown as Record<string, unknown>;
  const latestJob =
    recordValue(documentRecord.latest_job) ?? recordValue(documentRecord.latestJob);
  const latestResult =
    recordValue(documentRecord.latest_result) ??
    recordValue(documentRecord.latestResult) ??
    recordValue(documentRecord.latest_job_result) ??
    recordValue(documentRecord.latestJobResult);
  const candidates = [
    preprocessingSnapshotFromValue(latestResult),
    preprocessingSnapshotFromValue(latestJob),
    preprocessingSnapshotFromValue(document.index_contract),
    preprocessingSnapshotFromValue(relatedJob?.result),
  ];

  for (const snapshot of candidates) {
    const display = mapPreprocessingStatus(snapshot, document.status, relatedJob?.status);
    if (display) {
      return display;
    }
  }
  return null;
}

function preprocessingSnapshotFromValue(value: unknown): Record<string, unknown> | null {
  const record = recordValue(value);
  if (!record) {
    return null;
  }
  const nestedResult = recordValue(record.result);
  const candidates = [
    recordValue(record.preprocessing),
    nestedResult ? recordValue(nestedResult.preprocessing) : null,
  ];
  for (const candidate of candidates) {
    if (candidate) {
      return candidate;
    }
  }

  const status = stringValue(record.status);
  if (
    status &&
    (recordValue(record.preflight_before) ||
      recordValue(record.preflight_after) ||
      stringValue(record.error_type) ||
      stringValue(record.original_artifact_path) ||
      stringValue(record.active_artifact_path) ||
      stringValue(record.cleanup_status))
  ) {
    return record;
  }
  return null;
}

function mapPreprocessingStatus(
  snapshot: Record<string, unknown> | null,
  documentStatus: DocumentOut["status"],
  jobStatus?: JobOut["status"],
): DocumentPreprocessingStatus | null {
  if (!snapshot) {
    return null;
  }

  const status = stringValue(snapshot.status)?.toLowerCase();
  const cleanupStatus = stringValue(snapshot.cleanup_status)?.toLowerCase();
  const errorType = stringValue(snapshot.error_type)?.toLowerCase();
  const preflightBeforeStatus = stringValue(recordValue(snapshot.preflight_before)?.status)?.toLowerCase();
  const preflightAfterStatus = stringValue(recordValue(snapshot.preflight_after)?.status)?.toLowerCase();
  const originalArtifactPath = stringValue(snapshot.original_artifact_path);
  const activeArtifactPath = stringValue(snapshot.active_artifact_path);
  const indexed = documentStatus === "succeeded" || jobStatus === "succeeded";

  if (
    errorType === "pdf_cleanup_contract_failed" ||
    (status === "rejected" && errorType?.includes("contract"))
  ) {
    return { label: "Rejected: PDF cleanup failed contract", tone: "danger" };
  }

  if (
    matchesPreprocessingState(status, [
      "running",
      "pending_cleanup",
      "cleanup_running",
      "sample_cleanup_running",
    ]) ||
    matchesPreprocessingState(cleanupStatus, [
      "running",
      "pending_cleanup",
      "cleanup_running",
      "sample_cleanup_running",
    ])
  ) {
    return { label: "OCR cleanup running", tone: "active" };
  }

  if (
    indexed &&
    (matchesPreprocessingState(status, ["cleaned", "cleaned_indexed", "indexed_cleaned"]) ||
      (preflightAfterStatus === "passed" &&
        Boolean(originalArtifactPath) &&
        Boolean(activeArtifactPath) &&
        activeArtifactPath !== originalArtifactPath))
  ) {
    return { label: "Cleaned PDF indexed", tone: "success" };
  }

  if (
    matchesPreprocessingState(status, ["passed", "preflight_passed"]) ||
    preflightBeforeStatus === "passed"
  ) {
    return { label: "PDF preflight passed", tone: "neutral" };
  }

  return null;
}

function matchesPreprocessingState(
  value: string | undefined,
  acceptedStates: string[],
): boolean {
  return Boolean(value && acceptedStates.includes(value));
}

function documentPreprocessingToneClass(
  tone: DocumentPreprocessingStatus["tone"],
): string {
  switch (tone) {
    case "active":
      return "border-[var(--rs-accent-soft)] bg-[var(--rs-accent-soft)] text-[var(--rs-accent-deep)]";
    case "success":
      return "border-[#cfe3d5] bg-[#f6fbf7] text-[#235c2f]";
    case "danger":
      return "border-[#f2c6cb] bg-[#fff5f6] text-[#b42318]";
    default:
      return "border-[var(--rs-line)] bg-[var(--rs-field)] text-[var(--rs-text)]";
  }
}

function clampedTablePage(page: number, totalItems: number, pageSize: number): number {
  const safePageSize = Math.max(1, pageSize);
  const pageCount = Math.max(1, Math.ceil(Math.max(0, totalItems) / safePageSize));
  return Math.min(Math.max(1, page), pageCount);
}

function paginateRows<T>(rows: T[], page: number, pageSize: number): T[] {
  const safePageSize = Math.max(1, pageSize);
  const start = (clampedTablePage(page, rows.length, safePageSize) - 1) * safePageSize;
  return rows.slice(start, start + safePageSize);
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
    label: stringValue(payload.label) ?? titleCase(stageName.replaceAll("_", " ")),
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
      className="flex min-w-0 flex-col gap-4 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-4 shadow-sm"
    >
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
        <h3 className="truncate text-base font-semibold text-[var(--rs-ink)]">Operational status</h3>
      </div>
      <div className="grid min-w-0 gap-3">
        <StatusSummaryItem label="Documents" value={documentsCount} />
        <StatusSummaryItem
          label="Active jobs"
          value={activeJobCount}
          tone={activeJobCount ? "active" : "neutral"}
        />
        <StatusSummaryItem
          label="Warning jobs"
          value={warningJobCount}
          tone={warningJobCount ? "warning" : "neutral"}
        />
      </div>
      <div className="flex min-w-0 flex-col gap-3 border-t border-[var(--rs-line)] pt-3">
        {latestWarningLabel ? (
          <p className="min-w-0 text-xs leading-5 text-[var(--rs-muted)]">
            Latest warning:{" "}
            <span className="font-medium text-[var(--rs-text)]">{latestWarningLabel}</span>
          </p>
        ) : (
          <p className="text-xs leading-5 text-[var(--rs-muted)]">
            No parser warning jobs require inspection.
          </p>
        )}
        <Button type="button" variant="secondary" size="sm" onClick={onViewJobs}>
          <RefreshCcw className="h-4 w-4" aria-hidden="true" />
          View jobs
        </Button>
      </div>
    </section>
  );
}

function JobsMetricStrip({ metrics }: { metrics: ReturnType<typeof summarizeJobs> }) {
  return (
    <section
      aria-label="Jobs summary"
      className="grid overflow-hidden rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] sm:grid-cols-2 lg:grid-cols-5"
    >
      <JobMetric icon={ListChecks} label="Total Jobs" value={metrics.total} />
      <JobMetric icon={Loader2} label="Running" value={metrics.running} tone="running" />
      <JobMetric icon={CheckCircle2} label="Succeeded" value={metrics.succeeded} tone="success" />
      <JobMetric icon={XCircle} label="Failed" value={metrics.failed} tone="danger" />
      <JobMetric icon={FileWarning} label="Warning Jobs" value={metrics.warnings} tone="warning" />
    </section>
  );
}

function JobMetric({
  icon: Icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: typeof ListChecks;
  label: string;
  value: number;
  tone?: "neutral" | "running" | "success" | "danger" | "warning";
}) {
  const toneClass =
    tone === "running"
      ? "text-[var(--rs-accent)]"
      : tone === "success"
        ? "text-[var(--rs-success)]"
        : tone === "danger"
          ? "text-[var(--rs-danger)]"
          : tone === "warning"
            ? "text-[var(--rs-warning)]"
            : "text-[var(--rs-text)]";

  return (
    <div className="flex min-w-0 items-center gap-3 border-b border-[var(--rs-line)] p-3 last:border-b-0 sm:border-r sm:last:border-r-0 lg:border-b-0">
      <Icon className={`h-5 w-5 shrink-0 ${toneClass}`} aria-hidden="true" />
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-[var(--rs-muted)]">{label}</p>
        <p className="text-lg font-semibold text-[var(--rs-ink)]">{value}</p>
      </div>
    </div>
  );
}

function JobsToolbar({
  searchValue,
  statusValue,
  statusOptions,
  warningOnly,
  autoRefresh,
  refreshIntervalMs,
  filteredCount,
  totalCount,
  hasActiveFilters,
  onSearchChange,
  onStatusChange,
  onWarningOnlyChange,
  onAutoRefreshChange,
  onRefreshIntervalChange,
  onClearFilters,
}: {
  searchValue: string;
  statusValue: string;
  statusOptions: string[];
  warningOnly: boolean;
  autoRefresh: boolean;
  refreshIntervalMs: number;
  filteredCount: number;
  totalCount: number;
  hasActiveFilters: boolean;
  onSearchChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onWarningOnlyChange: (checked: boolean) => void;
  onAutoRefreshChange: (checked: boolean) => void;
  onRefreshIntervalChange: (value: number) => void;
  onClearFilters: () => void;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-3 xl:flex-row xl:items-center xl:justify-between">
      <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row md:items-center">
        <label className="min-w-0 flex-1 text-sm font-medium text-[var(--rs-text)]">
          <span className="sr-only">Search jobs</span>
          <div className="flex h-10 items-center gap-2 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] px-3 focus-within:ring-2 focus-within:ring-[var(--rs-accent)]">
            <Search className="h-4 w-4 shrink-0 text-[var(--rs-muted)]" aria-hidden="true" />
            <input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="Search jobs or documents..."
              className="min-w-0 flex-1 bg-transparent text-sm text-[var(--rs-text)] outline-none placeholder:text-[var(--rs-muted)]"
            />
          </div>
        </label>
        <label className="min-w-0 text-sm font-medium text-[var(--rs-text)] md:w-48">
          <span className="sr-only">Job status</span>
          <select
            value={statusValue}
            onChange={(event) => onStatusChange(event.target.value)}
            className="h-10 w-full rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] px-3 text-sm text-[var(--rs-text)] outline-none focus:ring-2 focus:ring-[var(--rs-accent)]"
            aria-label="Job status"
          >
            <option value="">All Statuses</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {titleCase(status)}
              </option>
            ))}
          </select>
        </label>
        <SwitchControl
          label="Warning only"
          checked={warningOnly}
          onChange={onWarningOnlyChange}
        />
        <Button
          type="button"
          variant="secondary"
          onClick={onClearFilters}
          disabled={!hasActiveFilters}
        >
          <X className="h-4 w-4" aria-hidden="true" />
          Clear Filters
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-xs font-medium text-[var(--rs-muted)]" aria-live="polite">
          {filteredCount} of {totalCount}
        </p>
        <SwitchControl label="Auto refresh" checked={autoRefresh} onChange={onAutoRefreshChange} />
        <select
          value={refreshIntervalMs}
          onChange={(event) => onRefreshIntervalChange(Number(event.target.value))}
          disabled={!autoRefresh}
          className="h-10 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] px-3 text-sm text-[var(--rs-text)] outline-none focus:ring-2 focus:ring-[var(--rs-accent)] disabled:opacity-50"
          aria-label="Auto refresh interval"
        >
          {JOB_REFRESH_INTERVAL_OPTIONS.map((interval) => (
            <option key={interval} value={interval}>
              {interval / 1000}s
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function SwitchControl({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-[var(--rs-text)]">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`flex h-5 w-9 items-center rounded-full border border-[var(--rs-line-strong)] p-0.5 transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--rs-accent)] ${
          checked ? "justify-end bg-[var(--rs-accent)]" : "justify-start bg-[var(--rs-line)]"
        }`}
      >
        <span className="h-4 w-4 rounded-full bg-[var(--rs-paper)] shadow-sm" />
      </button>
      {label}
    </label>
  );
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
      ? "text-[var(--rs-accent)]"
      : tone === "warning"
        ? "text-[var(--rs-warning)]"
        : "text-[var(--rs-ink)]";
  const iconClass =
    tone === "active"
      ? "bg-[var(--rs-accent-soft)]"
      : tone === "warning"
        ? "bg-[var(--rs-warning-soft)]"
        : "bg-[var(--rs-field)]";

  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] px-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-xs font-medium uppercase text-[var(--rs-muted)]">{label}</p>
        <p className={`mt-0.5 text-xl font-semibold ${valueClass}`}>{value}</p>
      </div>
      <span className={`h-2.5 w-2.5 rounded-full ${iconClass}`} aria-hidden="true" />
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
          ? "flex h-10 items-center gap-2 rounded-md border border-[var(--rs-accent)] bg-[var(--rs-accent-soft)] px-3 text-sm font-semibold text-[var(--rs-accent-deep)] outline-none focus:ring-2 focus:ring-[var(--rs-accent)]"
          : "flex h-10 items-center gap-2 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] px-3 text-sm font-medium text-[var(--rs-muted)] outline-none hover:bg-[var(--rs-field)] hover:text-[var(--rs-text)] focus:ring-2 focus:ring-[var(--rs-accent)]"
      }
    >
      <span>{label}</span>
      <span
        className={
          selected
            ? "rounded-md bg-[var(--rs-paper)] px-2 py-0.5 text-xs text-[var(--rs-accent-deep)]"
            : "rounded-md bg-[var(--rs-field)] px-2 py-0.5 text-xs text-[var(--rs-muted)]"
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
  warningOnly: boolean,
  liveJobEventsById: LiveJobEventsById = {},
): JobOut[] {
  const normalizedQuery = normalizeSearch(query);
  return jobs.filter((job) => {
    if (status && job.status !== status) {
      return false;
    }
    if (warningOnly && !hasInspectableQualityWarnings(job)) {
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

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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
  rawChunkCount: number;
  rawWarningCount: number;
  message: string | null;
  blockTypes: Record<string, number>;
  expectedScripts: Record<string, number>;
  actions: Record<string, number>;
  visionRecoveryStatuses: Record<string, number>;
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
  visionRecoveryStatus: string | null;
  counted: boolean;
  message: string | null;
  textPreview: string;
}

function ParserQualityDetails({ groups }: { groups: ParserQualityGroup[] }) {
  if (!groups.length) {
    return null;
  }

  const totalWarnings = groups.reduce((total, group) => total + group.warningCount, 0);
  const totalRawWarnings = groups.reduce((total, group) => total + group.rawWarningCount, 0);
  const rawSummary =
    totalRawWarnings !== totalWarnings ? ` · ${totalRawWarnings} raw rows` : "";

  return (
    <details className="rounded-md border border-[#ead9a7] bg-[#fffaf0] p-2 text-[#5f4600]">
      <summary className="cursor-pointer font-medium">
        Parser warning details · {groups.length} types · {totalWarnings} counted warnings
        {rawSummary}
      </summary>
      <div className="mt-2 max-h-72 space-y-3 overflow-auto pr-1">
        {groups.map((group) => (
          <div key={group.code} className="space-y-1 border-t border-[#ead9a7] pt-2 first:border-t-0 first:pt-0">
            <p className="font-medium text-[#3a2f12]">
              {group.code} · {group.chunkCount} counted chunks · {group.warningCount} counted warnings
              {group.rawWarningCount !== group.warningCount
                ? ` · ${group.rawWarningCount} raw rows`
                : ""}
            </p>
            {group.message ? <p>{group.message}</p> : null}
            <ParserQualityBreakdown label="Block types" values={group.blockTypes} />
            <ParserQualityBreakdown label="Expected scripts" values={group.expectedScripts} />
            <ParserQualityBreakdown label="Actions" values={group.actions} />
            <ParserQualityBreakdown
              label="Vision recovery"
              values={group.visionRecoveryStatuses}
            />
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
                    {example.visionRecoveryStatus ? (
                      <p className="text-xs text-[#62717a]">
                        vision_recovery_status={example.visionRecoveryStatus}
                        {example.counted ? "" : " · not counted"}
                      </p>
                    ) : null}
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
  job,
  document,
  liveEvent,
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
  job: JobOut | undefined;
  document: DocumentOut | undefined;
  liveEvent: LiveJobEventSnapshot | undefined;
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
  const selectedProgress = job ? getJobProgress(job, liveEvent) : 0;
  const selectedStage =
    jobStageText(job, liveEvent) ?? (job ? formatMinerUResult(job, liveEvent) : null) ?? "No stage reported";
  const latestLog = liveEvent?.logs.at(-1) ?? job?.logs.at(-1) ?? "No logs";
  const selectedWarnings = job ? jobWarningCount(job, liveEvent) : countEntries.reduce((total, [, count]) => total + count, 0);
  const parserGroups = jobParserQualityGroups(job);
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
            Selected Job: <span className="font-semibold">{jobName}</span>
          </h4>
          <p className="truncate text-xs text-[#62717a]">
            Warning details
            {job?.id ? (
              <>
                {" "}
                <span aria-hidden="true">·</span> {job.id}
              </>
            ) : null}
          </p>
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
              <Wrench className="h-4 w-4" aria-hidden="true" />
            )}
            Run Repair Suggestions
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

      <JobWarningSummary
        job={job}
        document={document}
        progress={selectedProgress}
        stage={selectedStage}
        latestLog={latestLog}
        warningCount={selectedWarnings}
      />

      {isLoading ? (
        <p className="mt-4 text-sm text-[#62717a]" role="status" aria-live="polite">
          Loading warning details.
        </p>
      ) : error ? (
        <p className="mt-4 text-sm text-[#8a1f11]">{error.message}</p>
      ) : details ? (
        <div className="mt-4 min-w-0 space-y-4">
          <p className="text-sm font-semibold text-[#1f2933]">Warning details</p>
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
              counted_warning_chunks={details.affected_chunks}
            </span>
            <span className="rounded-md border border-[#d6dde1] bg-white px-2 py-1 text-[#3a4a53]">
              warning_detail_rows={details.total}
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
          <ParserQualityDetails groups={parserGroups} />
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

function JobWarningSummary({
  job,
  document,
  progress,
  stage,
  latestLog,
  warningCount,
}: {
  job: JobOut | undefined;
  document: DocumentOut | undefined;
  progress: number;
  stage: string;
  latestLog: string;
  warningCount: number;
}) {
  const summaryRows = [
    ["Document", document?.filename ?? job?.target_id ?? "Workspace"],
    ["Runtime profile", "prod-baseline"],
    ["Parser mode", DEFAULT_PARSER_MODE],
    ["Status", job?.status ? titleCase(job.status) : "Unknown"],
    ["Current stage", stage],
    ["Worker", job?.worker_id ?? "Unassigned"],
    ["Last heartbeat", job?.heartbeat_at ? formatDateTime(job.heartbeat_at) : "Not reported"],
  ] as const;

  return (
    <div className="mt-4 grid min-w-0 gap-4 border-t border-[#d6dde1] pt-4 lg:grid-cols-[minmax(220px,0.32fr)_minmax(0,1fr)]">
      <aside className="min-w-0 rounded-md border border-[#d6dde1] bg-white p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-[#1f2933]">Job Summary</p>
          {job?.id ? (
            <button
              type="button"
              onClick={() => void navigator.clipboard?.writeText(job.id)}
              className="rounded-md p-1 text-[#62717a] outline-none hover:bg-[#edf1f3] focus:ring-2 focus:ring-[#176b87]"
              aria-label="Copy job id"
            >
              <Copy className="h-4 w-4" aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <dl className="space-y-2 text-xs">
          {summaryRows.map(([label, value]) => (
            <div
              key={label}
              className="grid grid-cols-[92px_minmax(0,1fr)] gap-3 border-b border-[#edf1f3] pb-2 last:border-b-0 last:pb-0"
            >
              <dt className="text-[#62717a]">{label}</dt>
              <dd className="min-w-0 truncate font-medium text-[#24313a]">{value}</dd>
            </div>
          ))}
          <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-3">
            <dt className="text-[#62717a]">Progress</dt>
            <dd className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="w-8 text-xs font-medium text-[#24313a]">{progress}%</span>
                <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[#edf1f3]">
                  <div
                    className="h-full rounded-full bg-[var(--rs-accent)]"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            </dd>
          </div>
        </dl>
      </aside>
      <section className="grid min-w-0 gap-3 sm:grid-cols-3">
        <WarningSummaryCard icon={FileWarning} label="Warning chunks" value={String(warningCount)} tone="warning" />
        <WarningSummaryCard icon={Clock} label="Current stage" value={stage} />
        <WarningSummaryCard icon={ListChecks} label="Latest log" value={latestLog} />
      </section>
    </div>
  );
}

function WarningSummaryCard({
  icon: Icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: typeof ListChecks;
  label: string;
  value: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <div className="min-w-0 rounded-md border border-[#d6dde1] bg-white p-3">
      <div className="mb-2 flex items-center gap-2">
        <Icon
          className={`h-4 w-4 shrink-0 ${
            tone === "warning" ? "text-[var(--rs-warning)]" : "text-[var(--rs-accent)]"
          }`}
          aria-hidden="true"
        />
        <p className="truncate text-xs font-medium text-[#62717a]">{label}</p>
      </div>
      <p className="line-clamp-3 text-sm font-medium leading-5 text-[#24313a]">{value}</p>
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
  const warningPreview = compactRecordPreview(item.warning, [
    "code",
    "action",
    "expected_script",
    "vision_recovery_status",
  ]);

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
      const chunkCount = numberValue(group.chunk_count);
      const warningCount = numberValue(group.warning_count);
      return {
        code: group.code,
        chunkCount,
        warningCount,
        rawChunkCount: numberValue(group.raw_chunk_count) || chunkCount,
        rawWarningCount: numberValue(group.raw_warning_count) || warningCount,
        message: stringValue(group.message),
        blockTypes: numericRecord(group.block_types),
        expectedScripts: numericRecord(group.expected_scripts),
        actions: numericRecord(group.actions),
        visionRecoveryStatuses: numericRecord(group.vision_recovery_statuses),
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
        visionRecoveryStatus: stringValue(example.vision_recovery_status),
        counted: example.counted !== false,
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

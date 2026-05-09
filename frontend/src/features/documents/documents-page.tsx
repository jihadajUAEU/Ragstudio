import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, FileUp, Loader2, RefreshCcw, Trash2, Upload } from "lucide-react";

import { apiClient } from "../../api/client";
import type { DocumentOut, IndexDocumentIn, JobOut } from "../../api/generated";
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
  const [indexOptions, setIndexOptions] = useState<IndexDocumentIn>({
    parser_mode: "local_fallback",
    domain_metadata: { domain: "generic", document_type: "document", tags: [] },
  });
  const [metadataValid, setMetadataValid] = useState(true);
  const documentsQuery = useQuery({ queryKey: queryKeys.documents, queryFn: apiClient.documents });
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: apiClient.jobs,
    refetchInterval: (query) => (hasActiveJobs(query.state.data?.items ?? []) ? 2000 : false),
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
      apiClient.reindexDocument(documentId, options),
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
      reindexDocument.mutate({ documentId: document.id, options: indexOptions });
    },
    [indexOptions, reindexDocument],
  );

  const refresh = () => {
    void documentsQuery.refetch();
    void jobsQuery.refetch();
  };
  const jobs = jobsQuery.data?.items ?? [];
  const activeJobs = hasActiveJobs(jobs);
  const documentsById = useMemo(
    () => new Map((documentsQuery.data?.items ?? []).map((document) => [document.id, document])),
    [documentsQuery.data?.items],
  );

  const refetchDocuments = documentsQuery.refetch;

  useEffect(() => {
    const shouldSyncDocuments = activeJobs || hadActiveJobsRef.current;
    hadActiveJobsRef.current = activeJobs;
    if (!shouldSyncDocuments) {
      return;
    }
    void refetchDocuments();
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

          return (
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => reindexExistingDocument(document)}
                disabled={!metadataValid || reindexDocument.isPending}
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
          const mineruStatus = formatMinerUResult(row.original.result);

          return (
            <div className="min-w-0 space-y-1 text-xs text-[#62717a]">
              {mineruStatus ? (
                <p className="truncate font-medium text-[#3a4a53]">MinerU: {mineruStatus}</p>
              ) : null}
              <p className="line-clamp-2">{row.original.logs.at(-1) ?? "No logs"}</p>
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
  const progress = mineru?.progress ?? job.progress;

  return Math.max(0, Math.min(Math.round(progress), 100));
}

function formatMinerUResult(result: Record<string, unknown>): string | null {
  const mineru = getMinerUStatus(result);
  if (!mineru) {
    return null;
  }

  const progress = typeof mineru.progress === "number" ? `${Math.round(mineru.progress)}%` : null;

  return [mineru.status, progress, mineru.detail].filter(Boolean).join(" · ") || null;
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

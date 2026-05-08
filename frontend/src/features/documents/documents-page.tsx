import { useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { AlertCircle, FileUp, Loader2, RefreshCcw, Upload } from "lucide-react";

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
  const [file, setFile] = useState<File | null>(null);
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

  const refresh = () => {
    void documentsQuery.refetch();
    void jobsQuery.refetch();
  };

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
        accessorKey: "sha256",
        header: "SHA-256",
        cell: ({ row }) => (
          <code className="block truncate text-xs text-[#62717a]">{row.original.sha256}</code>
        ),
      },
    ],
    [],
  );

  const jobColumns = useMemo<ColumnDef<JobOut>[]>(
    () => [
      {
        accessorKey: "type",
        header: "Job",
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate font-medium">{titleCase(row.original.type)}</p>
            <code className="block truncate text-xs text-[#62717a]">
              {row.original.target_id ?? "workspace"}
            </code>
          </div>
        ),
      },
      {
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => (
          <div className="flex min-w-28 items-center gap-2">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[#e6ecef]">
              <div
                className="h-full rounded-full bg-[#176b87]"
                style={{ width: `${Math.min(row.original.progress, 100)}%` }}
              />
            </div>
            <span className="w-9 text-right text-xs text-[#62717a]">{row.original.progress}%</span>
          </div>
        ),
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
    [],
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
          <div className="grid gap-3 lg:grid-cols-[minmax(280px,1fr)_auto] lg:items-end">
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
            <Button type="submit" disabled={!file || !metadataValid || uploadDocument.isPending}>
              {uploadDocument.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Upload className="h-4 w-4" aria-hidden="true" />
              )}
              Upload
            </Button>
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
                    }
                  : undefined
              }
            />
          </div>
        </form>
        <p className="mt-3 min-h-5 text-sm text-[#62717a]" role="status">
          {uploadDocument.isSuccess ? "Uploaded" : uploadDocument.error?.message}
        </p>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(360px,0.7fr)]">
        <Panel title="Documents" icon={FileUp}>
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
              data={jobsQuery.data?.items ?? []}
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

function formatMinerUResult(result: Record<string, unknown>): string | null {
  const mineru = result.mineru;
  if (!isRecord(mineru)) {
    return null;
  }

  const status = typeof mineru.status === "string" ? titleCase(mineru.status) : null;
  const progress = typeof mineru.progress === "number" ? `${mineru.progress}%` : null;
  const detail = typeof mineru.detail === "string" && mineru.detail.length > 0 ? mineru.detail : null;

  return [status, progress, detail].filter(Boolean).join(" · ") || null;
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

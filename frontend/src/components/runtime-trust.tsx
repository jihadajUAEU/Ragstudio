import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCcw,
  TestTube2,
  X,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { apiClient } from "../api/client";
import type {
  DiagnosticsOut,
  EmbeddingConnectionTestOut,
  LlmConnectionTestOut,
  MinerUConnectionTestOut,
  RerankerConnectionTestOut,
  RuntimeHealthCheck,
  SettingsProfileOut,
} from "../api/generated";
import { cn } from "../lib/utils";
import { FocusTrapDialog } from "./focus-trap-dialog";
import { Button } from "./ui/button";

type RuntimeTrustLabel =
  | "Ready"
  | "Degraded"
  | "Blocked"
  | "Indexing"
  | "Graph pending"
  | "Provider issue";

type RuntimeTrustTone = "success" | "warning" | "danger";
type SectionStatus = "ready" | "warning" | "blocked" | "unknown";
type ProviderTestKind = "llm" | "embeddings" | "reranker" | "mineru";
type ProviderTestResult = { ok: boolean; message: string };
type ProviderResults = Partial<Record<ProviderTestKind, ProviderTestResult>>;
type PendingProviders = Partial<Record<ProviderTestKind, boolean>>;
type ProviderConnectionResult =
  | LlmConnectionTestOut
  | EmbeddingConnectionTestOut
  | RerankerConnectionTestOut
  | MinerUConnectionTestOut;

export interface RuntimeTrustState {
  label: RuntimeTrustLabel;
  detail: string;
  tone: RuntimeTrustTone;
}

export const runtimeTrustQueryKey = ["diagnostics", "runtime-trust"] as const;

export function RuntimeTrust({ onNavigate }: { onNavigate: (path: string) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  const [providerResults, setProviderResults] = useState<ProviderResults>({});
  const [pendingProviders, setPendingProviders] = useState<PendingProviders>({});
  const diagnosticsQuery = useQuery({
    queryKey: runtimeTrustQueryKey,
    queryFn: apiClient.diagnostics,
    refetchInterval: 30000,
  });
  const trust = deriveRuntimeTrustStatus({
    diagnostics: diagnosticsQuery.data,
    isError: diagnosticsQuery.isError,
    error: diagnosticsQuery.error,
  });
  const sections = buildRuntimeSections(diagnosticsQuery.data);

  const closePanel = () => {
    setIsOpen(false);
    setProviderResults({});
    setPendingProviders({});
  };

  const runProviderTest = async (kind: ProviderTestKind) => {
    setProviderResults((current) => {
      const next = { ...current };
      delete next[kind];
      return next;
    });
    setPendingProviders((current) => ({ ...current, [kind]: true }));

    try {
      const settings = await apiClient.defaultSettings();
      const result = await providerTests[kind].test(settings);
      setProviderResults((current) => ({
        ...current,
        [kind]: { ok: result.ok, message: formatProviderResult(result) },
      }));
    } catch (error) {
      setProviderResults((current) => ({
        ...current,
        [kind]: {
          ok: false,
          message: error instanceof Error ? error.message : "Provider test failed",
        },
      }));
    } finally {
      setPendingProviders((current) => ({ ...current, [kind]: false }));
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn(
          "min-h-8 shrink-0 border px-2.5",
          trust.tone === "success" &&
            "border-[#b9dfc3] bg-[#e9f6eb] text-[#256a3b] hover:bg-[#ddf0e2]",
          trust.tone === "warning" &&
            "border-[#efd186] bg-[#fff4d7] text-[#8a5a00] hover:bg-[#ffeab5]",
          trust.tone === "danger" &&
            "border-[#efc0c0] bg-[#fff0f0] text-[#8c2525] hover:bg-[#ffe1e1]",
        )}
        aria-label={`Runtime trust status: ${trust.label}. ${trust.detail}`}
        onClick={() => setIsOpen(true)}
      >
        {diagnosticsQuery.isFetching ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : trust.tone === "success" ? (
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
        ) : trust.tone === "warning" ? (
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        <span>{trust.label}</span>
      </Button>

      <FocusTrapDialog
        open={isOpen}
        title="Runtime trust"
        overlayLabel="Close runtime trust"
        onClose={closePanel}
        overlayClassName="z-30"
        className="fixed inset-0 z-40 flex max-h-screen flex-col overflow-hidden bg-white sm:inset-y-0 sm:left-auto sm:right-0 sm:w-full sm:max-w-xl sm:border-l sm:border-[#d6dde1]"
      >
        <div className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-[#d6dde1] px-4 sm:px-5">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#176b87]">Runtime trust</p>
            <p className="truncate text-xs text-[#62717a]">{trust.detail}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close runtime trust"
            onClick={closePanel}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
          <div
            className={cn(
              "mb-4 rounded-md border p-3 text-sm",
              trust.tone === "success" && "border-[#b9dfc3] bg-[#e9f6eb] text-[#256a3b]",
              trust.tone === "warning" && "border-[#efd186] bg-[#fff4d7] text-[#8a5a00]",
              trust.tone === "danger" && "border-[#efc0c0] bg-[#fff0f0] text-[#8c2525]",
            )}
          >
            <div className="flex items-center gap-2 font-semibold">
              <TrustIcon tone={trust.tone} />
              {trust.label}
            </div>
            <p className="mt-1 break-words">{trust.detail}</p>
          </div>

          <div className="mb-4 flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => void diagnosticsQuery.refetch()}
              disabled={diagnosticsQuery.isFetching}
            >
              {diagnosticsQuery.isFetching ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              )}
              Refresh status
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => {
                closePanel();
                onNavigate("/diagnostics");
              }}
            >
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              Open Diagnostics
            </Button>
          </div>

          <section className="space-y-2" aria-label="Runtime readiness">
            {sections.map((section) => (
              <ReadinessSection key={section.label} section={section} />
            ))}
          </section>

          <section className="mt-5 border-t border-[#d6dde1] pt-4">
            <h3 className="text-sm font-semibold text-[#1f2933]">Provider tests</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {(Object.keys(providerTests) as ProviderTestKind[]).map((kind) => {
                const test = providerTests[kind];
                const result = providerResults[kind];
                const pending = Boolean(pendingProviders[kind]);
                return (
                  <div key={kind} className="rounded-md border border-[#d6dde1] bg-[#fbfcfd] p-3">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="w-full justify-center"
                      disabled={pending}
                      onClick={() => void runProviderTest(kind)}
                    >
                      {pending ? (
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <TestTube2 className="h-4 w-4" aria-hidden="true" />
                      )}
                      {test.label}
                    </Button>
                    <p
                      className={cn(
                        "mt-2 min-h-5 break-words text-xs",
                        result?.ok === true && "text-[#256a3b]",
                        result?.ok === false && "text-[#8c2525]",
                        !result && "text-[#62717a]",
                      )}
                      role="status"
                      aria-live="polite"
                    >
                      {pending ? "Testing..." : result?.message ?? ""}
                    </p>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </FocusTrapDialog>
    </>
  );
}

export function deriveRuntimeTrustStatus({
  diagnostics,
  isError,
  error,
}: {
  diagnostics?: DiagnosticsOut;
  isError?: boolean;
  error?: Error | null;
}): RuntimeTrustState {
  if (isError) {
    return {
      label: "Blocked",
      detail: error?.message ? `Diagnostics unavailable: ${error.message}` : "Diagnostics unavailable",
      tone: "danger",
    };
  }

  if (!diagnostics) {
    return {
      label: "Degraded",
      detail: "Loading diagnostics",
      tone: "warning",
    };
  }

  const checks = diagnostics.checks ?? [];
  const dependencyStatus = diagnostics.dependency_status ?? {};
  const warnings = diagnostics.warnings ?? [];
  const blockingCheck = checks.find(
    (check) =>
      !isProviderCheck(check) &&
      (check.severity === "blocking" || check.status === "failed"),
  );
  if (diagnostics.overall_status === "failed" || blockingCheck) {
    return {
      label: "Blocked",
      detail: blockingCheck?.detail || "Runtime failure reported",
      tone: "danger",
    };
  }

  const providerCheck = checks.find(
    (check) =>
      isProviderCheck(check) && (check.status === "failed" || check.severity === "blocking"),
  );
  if (providerCheck) {
    return {
      label: "Provider issue",
      detail: providerCheck.detail || `${humanize(providerCheck.name)} failed`,
      tone: "danger",
    };
  }

  const readyIndexJobs = numberValue(dependencyStatus.ready_index_jobs);
  const runningIndexJobs = numberValue(dependencyStatus.running_index_jobs);
  const indexingWarning = warnings.find((warning) =>
    /indexing|running job|stale.*job|job.*stale/i.test(warning),
  );
  if ((readyIndexJobs ?? 0) > 0 || (runningIndexJobs ?? 0) > 0 || indexingWarning) {
    return {
      label: "Indexing",
      detail:
        indexingWarning ||
        `${readyIndexJobs ?? runningIndexJobs ?? 1} indexing job${(readyIndexJobs ?? runningIndexJobs ?? 1) === 1 ? "" : "s"} active`,
      tone: "warning",
    };
  }

  const graphProjection = stringValue(dependencyStatus.graph_projection);
  const graphWarning = warnings.find((warning) => /graph|projection/i.test(warning));
  if (graphProjection === "pending" || (graphWarning && /pending/i.test(graphWarning))) {
    return {
      label: "Graph pending",
      detail: graphWarning || "Graph projection is pending",
      tone: "warning",
    };
  }

  const warningCheck = checks.find((check) => check.status === "warning" || check.status === "skipped");
  if (diagnostics.overall_status === "degraded" || warnings.length > 0 || warningCheck) {
    return {
      label: "Degraded",
      detail: warnings[0] || warningCheck?.detail || "Runtime diagnostics reported degraded status",
      tone: "warning",
    };
  }

  return {
    label: "Ready",
    detail: "Runtime diagnostics ready",
    tone: "success",
  };
}

function isProviderCheck(check: RuntimeHealthCheck) {
  return /llm|embedding|rerank|mineru|provider|model|vision/i.test(check.name);
}

const providerTests: Record<
  ProviderTestKind,
  {
    label: string;
    test: (settings: SettingsProfileOut) => Promise<ProviderConnectionResult>;
  }
> = {
  llm: {
    label: "Test LLM",
    test: apiClient.testLlmSettings,
  },
  embeddings: {
    label: "Test embeddings",
    test: apiClient.testEmbeddingSettings,
  },
  reranker: {
    label: "Test reranker",
    test: apiClient.testRerankerSettings,
  },
  mineru: {
    label: "Test MinerU",
    test: apiClient.testMinerUSettings,
  },
};

interface RuntimeSection {
  label: string;
  status: SectionStatus;
  detail: string;
}

function buildRuntimeSections(diagnostics?: DiagnosticsOut): RuntimeSection[] {
  return [
    sectionFromCheck(
      "Backend/API",
      diagnostics,
      ["backend", "api", "health"],
      "Backend/API status not recorded",
    ),
    sectionFromJobs(diagnostics),
    sectionFromCheck(
      "Postgres/PGVector",
      diagnostics,
      ["postgres", "pgvector", "database"],
      "Postgres/PGVector status not recorded",
    ),
    sectionFromGraph(diagnostics),
    sectionFromCheck(
      "MinerU/parser",
      diagnostics,
      ["mineru", "parser"],
      "MinerU/parser status not recorded",
    ),
    sectionFromCheck("LLM", diagnostics, ["llm"], "LLM status not recorded"),
    sectionFromCheck(
      "Embeddings",
      diagnostics,
      ["embedding", "embeddings"],
      "Embeddings status not recorded",
    ),
    sectionFromCheck(
      "Reranker",
      diagnostics,
      ["reranker", "rerank"],
      "Reranker status not recorded",
    ),
  ];
}

function sectionFromCheck(
  label: string,
  diagnostics: DiagnosticsOut | undefined,
  needles: string[],
  fallback: string,
): RuntimeSection {
  const check = diagnostics?.checks.find((candidate) =>
    needles.some((needle) => candidate.name.toLowerCase().includes(needle)),
  );
  if (!diagnostics) {
    return { label, status: "unknown", detail: fallback };
  }
  if (!check) {
    return { label, status: "unknown", detail: fallback };
  }
  return {
    label,
    status: statusFromCheck(check),
    detail: check.detail || humanize(check.name),
  };
}

function sectionFromJobs(diagnostics?: DiagnosticsOut): RuntimeSection {
  if (!diagnostics) {
    return { label: "Worker/jobs", status: "unknown", detail: "Worker/job status not recorded" };
  }
  const readyJobs = numberValue(diagnostics.dependency_status.ready_index_jobs) ?? 0;
  const runningJobs = numberValue(diagnostics.dependency_status.running_index_jobs) ?? 0;
  const staleWarning = diagnostics.warnings.find((warning) =>
    /running job|stale.*job|job.*stale/i.test(warning),
  );
  if (staleWarning) {
    return { label: "Worker/jobs", status: "warning", detail: staleWarning };
  }
  if (readyJobs > 0 || runningJobs > 0) {
    return {
      label: "Worker/jobs",
      status: "warning",
      detail: `${readyJobs || runningJobs} indexing job${(readyJobs || runningJobs) === 1 ? "" : "s"} active`,
    };
  }
  return {
    label: "Worker/jobs",
    status: "ready",
    detail: "No indexing jobs blocking runtime trust",
  };
}

function sectionFromGraph(diagnostics?: DiagnosticsOut): RuntimeSection {
  if (!diagnostics) {
    return {
      label: "Neo4j/graph projection",
      status: "unknown",
      detail: "Neo4j/graph projection status not recorded",
    };
  }
  const graphProjection = stringValue(diagnostics.dependency_status.graph_projection);
  const graphWarning = diagnostics.warnings.find((warning) => /graph|projection/i.test(warning));
  if (graphProjection === "pending" || (graphWarning && /pending/i.test(graphWarning))) {
    return {
      label: "Neo4j/graph projection",
      status: "warning",
      detail: graphWarning || "Graph projection is pending",
    };
  }
  if (graphProjection === "failed") {
    return {
      label: "Neo4j/graph projection",
      status: "blocked",
      detail: graphWarning || "Graph projection failed",
    };
  }
  return {
    label: "Neo4j/graph projection",
    status: "ready",
    detail: graphProjection ? `Graph projection ${graphProjection}` : "Graph projection ready",
  };
}

function statusFromCheck(check: RuntimeHealthCheck): SectionStatus {
  if (check.status === "ok") {
    return "ready";
  }
  if (check.status === "failed" || check.severity === "blocking") {
    return "blocked";
  }
  return "warning";
}

function ReadinessSection({ section }: { section: RuntimeSection }) {
  return (
    <div className="rounded-md border border-[#d6dde1] bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-[#1f2933]">{section.label}</h3>
          <p className="mt-1 break-words text-xs leading-5 text-[#62717a]">{section.detail}</p>
        </div>
        <SectionBadge status={section.status} />
      </div>
    </div>
  );
}

function SectionBadge({ status }: { status: SectionStatus }) {
  const label =
    status === "ready"
      ? "Ready"
      : status === "blocked"
        ? "Blocked"
        : status === "warning"
          ? "Degraded"
          : "Not recorded";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium",
        status === "ready" && "bg-[#e9f6eb] text-[#256a3b]",
        status === "warning" && "bg-[#fff4d7] text-[#8a5a00]",
        status === "blocked" && "bg-[#fff0f0] text-[#8c2525]",
        status === "unknown" && "bg-[#f8fafb] text-[#3a4a53]",
      )}
    >
      {status === "ready" ? (
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
      ) : status === "blocked" ? (
        <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {label}
    </span>
  );
}

function TrustIcon({ tone }: { tone: RuntimeTrustTone }) {
  if (tone === "success") {
    return <CheckCircle2 className="h-4 w-4" aria-hidden="true" />;
  }
  if (tone === "warning") {
    return <AlertTriangle className="h-4 w-4" aria-hidden="true" />;
  }
  return <XCircle className="h-4 w-4" aria-hidden="true" />;
}

function formatProviderResult(result: ProviderConnectionResult) {
  const prefix = result.ok ? "Connected" : "Failed";
  const dimensions =
    "dimensions" in result && result.dimensions ? ` (${result.dimensions} dims)` : "";
  return `${prefix}: ${result.detail}${dimensions}`;
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.toLowerCase() : null;
}

function humanize(value: string) {
  return value.replace(/[_-]+/g, " ");
}

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { apiClient } from "../api/client";
import type { DiagnosticsOut, RuntimeHealthCheck } from "../api/generated";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";

type RuntimeTrustLabel =
  | "Ready"
  | "Degraded"
  | "Blocked"
  | "Indexing"
  | "Graph pending"
  | "Provider issue";

type RuntimeTrustTone = "success" | "warning" | "danger";

export interface RuntimeTrustState {
  label: RuntimeTrustLabel;
  detail: string;
  tone: RuntimeTrustTone;
}

export const runtimeTrustQueryKey = ["diagnostics", "runtime-trust"] as const;

export function RuntimeTrust({ onNavigate }: { onNavigate: (path: string) => void }) {
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

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={cn(
        "min-h-8 shrink-0 border px-2.5",
        trust.tone === "success" && "border-[#b9dfc3] bg-[#e9f6eb] text-[#256a3b] hover:bg-[#ddf0e2]",
        trust.tone === "warning" && "border-[#efd186] bg-[#fff4d7] text-[#8a5a00] hover:bg-[#ffeab5]",
        trust.tone === "danger" && "border-[#efc0c0] bg-[#fff0f0] text-[#8c2525] hover:bg-[#ffe1e1]",
      )}
      aria-label={`Runtime trust status: ${trust.label}. ${trust.detail}`}
      onClick={() => onNavigate("/diagnostics")}
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

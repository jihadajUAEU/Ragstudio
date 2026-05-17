import { X } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import type { PathwayDiagnosticOut, RunOut } from "../../api/generated";
import { FocusTrapDialog } from "../../components/focus-trap-dialog";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

type StepStatus = "success" | "warning" | "failed" | "skipped" | "unknown";

interface PathwayStep {
  step: string;
  diagnostic: PathwayDiagnosticOut;
}

export function QueryPathwayViewer({
  run,
  open,
  onClose,
}: {
  run: RunOut | null;
  open: boolean;
  onClose: () => void;
}) {
  const isOpen = open && run !== null;
  const pathway = useMemo(() => (run ? buildPathway(run) : null), [run]);

  return (
    <FocusTrapDialog
      open={isOpen}
      title="Query pathway"
      overlayLabel="Close query pathway"
      onClose={onClose}
      overlayClassName="z-30"
      className="fixed inset-0 z-40 flex max-h-screen flex-col overflow-hidden bg-white sm:inset-y-0 sm:left-auto sm:right-0 sm:w-full sm:max-w-3xl sm:border-l sm:border-[#d6dde1]"
    >
      {run && pathway ? (
        <>
          <div className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-[#d6dde1] px-4 sm:px-5">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-[#176b87]">Query pathway</p>
              <p className="truncate text-xs text-[#62717a]">{run.id}</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close query pathway"
              onClick={onClose}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 sm:px-5">
            <PathwaySection title="Summary" defaultOpen>
              <SummaryGrid run={run} pathway={pathway} />
            </PathwaySection>
            <PathwaySection title="Timeline" defaultOpen>
              <Timeline steps={pathway.steps} />
            </PathwaySection>
            <PathwaySection title="Raw">
              <JsonBlock
                value={{
                  timings: run.timings,
                  chunk_traces: run.chunk_traces,
                  token_metadata: run.token_metadata,
                }}
              />
            </PathwaySection>
          </div>
        </>
      ) : null}
    </FocusTrapDialog>
  );
}

function SummaryGrid({ run, pathway }: { run: RunOut; pathway: ReturnType<typeof buildPathway> }) {
  return (
    <div className="grid gap-2 text-sm sm:col-span-2 sm:grid-cols-2">
      <KeyValue label="Run status" value={run.status} />
      <KeyValue label="Total time" value={formatMs(numberValue(run.timings.total_ms))} />
      <KeyValue label="Answer mode" value={textValue(run.token_metadata.answer_mode) ?? "not recorded"} />
      <KeyValue label="Top reference" value={pathway.topReference} />
      <KeyValue label="Top source" value={pathway.topSource} />
      <KeyValue label="Error" value={run.error_type ?? run.error ?? "none"} />
    </div>
  );
}

function Timeline({ steps }: { steps: PathwayStep[] }) {
  return (
    <ol className="space-y-2 sm:col-span-2">
      {steps.map((step) => (
        <li key={step.step} className="rounded-md border border-[#e1e7ea] bg-white p-3">
          <div className="grid gap-2 sm:grid-cols-[2.25rem_minmax(8rem,1fr)_auto_auto] sm:items-center">
            <span className="font-mono text-xs text-[#62717a]">{step.step}</span>
            <p className="font-medium text-[#1f2933]">{step.diagnostic.label}</p>
            <div>
              <p className="sr-only">Status</p>
              <StatusPill
                status={step.diagnostic.status}
                kind={statusKind(step.diagnostic.status)}
              />
            </div>
            <div className="font-mono text-xs text-[#3a4a53]">
              <span className="sr-only">Time </span>
              {formatMs(step.diagnostic.time_ms ?? undefined)}
              {step.diagnostic.budget_ms ? ` / ${formatMs(step.diagnostic.budget_ms)}` : ""}
            </div>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <DiagnosticValue label="Input" value={step.diagnostic.input} />
            <DiagnosticValue label="Action" value={step.diagnostic.action} />
            <DiagnosticValue label="Output" value={step.diagnostic.output} />
            <DiagnosticValue label="Diagnosis" value={step.diagnostic.diagnosis} />
            <DiagnosticValue
              label="Suggested action"
              value={step.diagnostic.suggested_action}
              className="sm:col-span-2"
            />
          </div>
        </li>
      ))}
    </ol>
  );
}

function PathwaySection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="rounded-md border border-[#d6dde1] bg-white px-3 py-2">
      <summary className="cursor-pointer py-1 text-sm font-semibold text-[#1f2933]">
        {title}
      </summary>
      <div className="mt-2 grid gap-2 border-t border-[#e1e7ea] pt-3 sm:grid-cols-2">
        {children}
      </div>
    </details>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-[#f8fafb] px-3 py-2">
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <p className="mt-1 break-words text-sm text-[#24313a]">{value}</p>
    </div>
  );
}

function DiagnosticValue({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 rounded-md bg-[#f8fafb] px-3 py-2", className)}>
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <p className="mt-1 break-words text-sm text-[#3a4a53]">{value || "not recorded"}</p>
    </div>
  );
}

function StatusPill({ status, kind }: { status: string; kind: StepStatus }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center rounded-md px-2 text-xs font-semibold",
        kind === "success" && "bg-[#e7f6ed] text-[#1f6b3a]",
        kind === "warning" && "bg-[#fff4d7] text-[#8a5a00]",
        kind === "failed" && "bg-[#fff0f0] text-[#8c2525]",
        kind === "skipped" && "bg-[#eef4f6] text-[#62717a]",
        kind === "unknown" && "bg-[#f8fafb] text-[#3a4a53]",
      )}
    >
      {status}
    </span>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3 text-xs leading-5 text-[#3a4a53] sm:col-span-2">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function buildPathway(run: RunOut) {
  const traces = run.chunk_traces;
  const plannerTrace = traceByStage(traces, "planner");
  const hypothesisTrace = traceByStage(traces, "query_hypothesis");
  const retrievalTrace = traceByStage(traces, "retrieval");
  const seedFusionTrace = traceByStage(traces, "seed_fusion");
  const graphTrace = traceByStage(traces, "graph_expansion");
  const graphHydrationTrace = traceByStage(traces, "graph_hydration");
  const finalFusionTrace = traceByStage(traces, "final_fusion");
  const verificationTrace = traceByStage(traces, "hypothesis_verification");
  const contextTrace = traceByStage(traces, "context_assembly");
  const groundingTrace = traceByStage(traces, "grounding_validation");
  const metadataTrace = recordValue(retrievalTrace?.metadata_trace);
  const metadataPasses = Array.isArray(metadataTrace?.passes)
    ? (metadataTrace.passes as Record<string, unknown>[])
    : [];
  const topSource = recordValue(run.sources[0]);
  const topMetadata = recordValue(topSource?.metadata);
  const topReference =
    textValue(topMetadata?.canonical_reference) ??
    textValue(topSource?.source_location) ??
    textValue(recordValue(topSource?.source_location)?.reference) ??
    "not recorded";
  const targetTerms = targetTermValues(hypothesisTrace?.target_terms);
  const referenceResults = referenceResultValues(verificationTrace?.possible_reference_results);
  const answerStatus =
    textValue(run.token_metadata.llm_answer_status) ??
    (run.timings.answer_fallback ? "fallback" : run.status);
  const steps = diagnosticsForRun(run, {
    plannerTrace,
    hypothesisTrace,
    retrievalTrace,
    seedFusionTrace,
    graphTrace,
    graphHydrationTrace,
    finalFusionTrace,
    verificationTrace,
    contextTrace,
    groundingTrace,
    metadataPasses,
    targetTerms,
    referenceResults,
    answerStatus,
  }).map((diagnostic, index) => ({ step: String(index + 1), diagnostic }));

  return {
    steps,
    topReference,
    topSource: textValue(topSource?.chunk_id) ?? textValue(topSource?.id) ?? "not recorded",
  };
}

function diagnosticsForRun(
  run: RunOut,
  fallback: {
    plannerTrace: Record<string, unknown> | undefined;
    hypothesisTrace: Record<string, unknown> | undefined;
    retrievalTrace: Record<string, unknown> | undefined;
    seedFusionTrace: Record<string, unknown> | undefined;
    graphTrace: Record<string, unknown> | undefined;
    graphHydrationTrace: Record<string, unknown> | undefined;
    finalFusionTrace: Record<string, unknown> | undefined;
    verificationTrace: Record<string, unknown> | undefined;
    contextTrace: Record<string, unknown> | undefined;
    groundingTrace: Record<string, unknown> | undefined;
    metadataPasses: Record<string, unknown>[];
    targetTerms: string[];
    referenceResults: string;
    answerStatus: string;
  },
): PathwayDiagnosticOut[] {
  if (run.pathway_diagnostics?.length) {
    return run.pathway_diagnostics;
  }
  return [
    diagnostic(
      "planner",
      "Planner",
      "query + selected documents",
      "Build retrieval plan and pathway stages",
      plannerResult(fallback.plannerTrace),
      textValue(fallback.plannerTrace?.query_hypothesis_status) ?? "unknown",
      numberValue(run.timings.planner_ms),
    ),
    diagnostic(
      "llm_planning",
      "LLM planning",
      "query + selected document metadata",
      "Generate target terms and possible references",
      listSummary("target_terms", fallback.targetTerms),
      textValue(fallback.hypothesisTrace?.status) ??
        textValue(run.timings.query_hypothesis_status) ??
        "unknown",
      numberValue(run.timings.query_hypothesis_ms),
      numberValue(run.timings.query_hypothesis_timeout_ms),
    ),
    diagnostic(
      "metadata_retrieval",
      "Metadata retrieval",
      "retrieval plan + selected documents",
      "Run metadata, lexical, and exact-reference passes",
      metadataResult(fallback.metadataPasses),
      metadataPassStatus(fallback.metadataPasses),
      numberValue(run.timings.metadata_ms),
    ),
    diagnostic(
      "native_retrieval",
      "Native retrieval",
      "query + native runtime scope",
      "Search native RAG runtime",
      textValue(run.timings.native_error) ??
        countSummary("candidates", numberValue(fallback.retrievalTrace?.native_candidates)),
      run.timings.native_degraded
        ? "warning"
        : textValue(fallback.retrievalTrace?.native_status) ?? "unknown",
      numberValue(run.timings.native_stage_ms),
      numberValue(run.query_config.native_query_timeout_ms),
    ),
    diagnostic(
      "seed_fusion",
      "Seed fusion",
      "metadata and native candidates",
      "Merge initial candidates before graph expansion",
      countSummary("seed candidates", numberValue(fallback.seedFusionTrace?.seed_candidates)),
      "success",
      numberValue(run.timings.initial_fusion_ms),
    ),
    diagnostic(
      "graph_expansion",
      "Graph expansion",
      "seed candidates",
      "Expand candidate context through graph relationships",
      countSummary("expanded candidates", numberValue(fallback.graphTrace?.expanded_candidates)),
      textValue(fallback.graphTrace?.status) ?? "unknown",
      numberValue(run.timings.graph_ms),
    ),
    diagnostic(
      "graph_hydration",
      "Graph hydration",
      "graph candidates",
      "Hydrate graph candidates into source chunks",
      countSummary(
        "hydrated chunks",
        numberValue(fallback.graphHydrationTrace?.unique_hydrated_chunks),
      ),
      textValue(fallback.graphHydrationTrace?.status) ?? "unknown",
      numberValue(run.timings.graph_hydration_ms),
    ),
    diagnostic(
      "final_fusion",
      "Final fusion",
      "metadata, native, and graph candidates",
      "Score and order final evidence candidates",
      countSummary("fused candidates", numberValue(fallback.finalFusionTrace?.fused_candidates)),
      "success",
      numberValue(run.timings.final_fusion_ms),
    ),
    diagnostic(
      "hypothesis_verification",
      "Hypothesis verification",
      "final evidence + planner hypotheses",
      "Verify possible references and target terms against evidence",
      fallback.referenceResults || textValue(fallback.verificationTrace?.reason) || "not recorded",
      textValue(fallback.verificationTrace?.status) ?? "unknown",
    ),
    diagnostic(
      "context_assembly",
      "Context assembly",
      "reranked final candidates",
      "Assemble evidence context for answer generation",
      countSummary("included", numberValue(fallback.contextTrace?.included_candidates)),
      "success",
      numberValue(run.timings.context_assembly_ms),
    ),
    diagnostic(
      "answer_generation",
      "Answer generation",
      "assembled evidence context",
      "Generate final answer wording or evidence-first fallback",
      answerResult(run),
      fallback.answerStatus,
      numberValue(run.timings.answer_ms),
      numberValue(run.timings.answer_timeout_ms) ?? numberValue(run.query_config.answer_budget_ms),
    ),
    diagnostic(
      "grounding_validation",
      "Grounding validation",
      "answer + final evidence",
      "Validate answer citations and expected references",
      groundingResult(fallback.groundingTrace),
      textValue(fallback.groundingTrace?.status) ?? "unknown",
    ),
  ];
}

function diagnostic(
  stage: string,
  label: string,
  input: string,
  action: string,
  output: string,
  status: string,
  timeMs?: number,
  budgetMs?: number,
): PathwayDiagnosticOut {
  const kind = statusKind(status);
  return {
    stage,
    label,
    input,
    action,
    output: output || "not recorded",
    status: kind,
    time_ms: timeMs,
    budget_ms: budgetMs,
    diagnosis: fallbackDiagnosis(kind),
    suggested_action: kind === "unknown" ? "Inspect raw pathway data." : "None",
  };
}

function traceByStage(traces: Record<string, unknown>[], stage: string) {
  return traces.find((trace) => trace.stage === stage);
}

function targetTermValues(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (recordValue(item) ? textValue(recordValue(item)?.surface) : textValue(item)))
    .filter((item): item is string => Boolean(item));
}

function referenceResultValues(value: unknown) {
  if (!Array.isArray(value) || !value.length) {
    return "";
  }
  return value
    .map((item) => {
      const record = recordValue(item);
      if (!record) {
        return "";
      }
      return [textValue(record.reference), textValue(record.status)].filter(Boolean).join(" ");
    })
    .filter(Boolean)
    .join(", ");
}

function metadataPassStatus(passes: Record<string, unknown>[]) {
  if (!passes.length) {
    return "skipped";
  }
  return passes.some((item) => (numberValue(item.candidate_count) ?? 0) > 0) ? "ok" : "not_found";
}

function metadataResult(passes: Record<string, unknown>[]) {
  if (!passes.length) {
    return "no metadata passes";
  }
  return passes
    .map((item) => `${textValue(item.name) ?? "pass"}: ${numberValue(item.candidate_count) ?? 0}`)
    .join(", ");
}

function plannerResult(trace: Record<string, unknown> | undefined) {
  return [
    textValue(trace?.retrieval_strategy),
    textValue(trace?.intent),
    countSummary("limit", numberValue(trace?.candidate_limit)),
  ]
    .filter(Boolean)
    .join(" · ");
}

function answerResult(run: RunOut) {
  if (run.timings.answer_fallback) {
    return textValue(run.token_metadata.fallback_reason) ?? "fallback answer generated";
  }
  return textValue(run.token_metadata.llm_answer_status) ?? "answer returned";
}

function groundingResult(trace: Record<string, unknown> | undefined) {
  const failures = Array.isArray(trace?.failures) ? trace.failures.length : 0;
  const labels = Array.isArray(trace?.cited_labels) ? trace.cited_labels.length : 0;
  if (failures) {
    return `${failures} failures`;
  }
  return labels ? `${labels} cited labels` : "not recorded";
}

function listSummary(label: string, values: string[]) {
  return values.length ? `${label}: ${values.join(", ")}` : `${label}: none`;
}

function countSummary(label: string, value: number | undefined) {
  return value === undefined ? `${label}: not recorded` : `${label}: ${value}`;
}

function statusKind(status: string): StepStatus {
  const normalized = status.toLowerCase();
  if (["valid", "ok", "succeeded", "success", "grounded", "confirmed"].includes(normalized)) {
    return "success";
  }
  if (["degraded", "timeout", "fallback", "not_found"].includes(normalized)) {
    return "warning";
  }
  if (["failed", "error", "rejected"].includes(normalized)) {
    return "failed";
  }
  if (["skipped", "not_applicable", "disabled"].includes(normalized)) {
    return "skipped";
  }
  return "unknown";
}

function fallbackDiagnosis(kind: StepStatus) {
  if (kind === "unknown") {
    return "Missing trace or timing data.";
  }
  if (kind === "warning") {
    return "Stage degraded or used fallback.";
  }
  if (kind === "failed") {
    return "Stage failed.";
  }
  if (kind === "skipped") {
    return "Skipped by query configuration.";
  }
  return "Healthy.";
}

function formatMs(value: number | undefined) {
  return value === undefined ? "not recorded" : `${Math.round(value)} ms`;
}

function textValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

import { X } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import type { RunOut } from "../../api/generated";
import { FocusTrapDialog } from "../../components/focus-trap-dialog";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";

type StepStatus = "success" | "warning" | "failed" | "skipped" | "neutral";

interface PathwayStep {
  step: string;
  pathway: string;
  status: string;
  statusKind: StepStatus;
  time: string;
  result: string;
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
            <PathwaySection title="Planner">
              <KeyValue label="Status" value={pathway.plannerStatus} />
              <KeyValue label="Timeout" value={pathway.plannerTimeout} />
              <KeyValue label="Target terms" value={pathway.targetTerms} />
              <KeyValue label="Possible references" value={pathway.possibleReferences} />
              <KeyValue label="Reference verification" value={pathway.referenceVerification} />
            </PathwaySection>
            <PathwaySection title="Retrieval">
              <KeyValue label="Metadata" value={pathway.metadataResult} />
              <KeyValue label="Native" value={pathway.nativeResult} />
              <KeyValue label="Graph" value={pathway.graphResult} />
              <KeyValue label="Fusion" value={pathway.fusionResult} />
            </PathwaySection>
            <PathwaySection title="Answer">
              <KeyValue label="Answer status" value={pathway.answerStatus} />
              <KeyValue label="Fallback" value={pathway.answerFallback} />
              <KeyValue label="Grounding" value={pathway.groundingStatus} />
            </PathwaySection>
            <PathwaySection title="Raw">
              <JsonBlock value={{ timings: run.timings, chunk_traces: run.chunk_traces, token_metadata: run.token_metadata }} />
            </PathwaySection>
          </div>
        </>
      ) : null}
    </FocusTrapDialog>
  );
}

function SummaryGrid({ run, pathway }: { run: RunOut; pathway: ReturnType<typeof buildPathway> }) {
  return (
    <div className="grid gap-2 text-sm sm:grid-cols-2">
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
            <p className="font-medium text-[#1f2933]">{step.pathway}</p>
            <div>
              <p className="sr-only">Status</p>
              <StatusPill status={step.status} kind={step.statusKind} />
            </div>
            <div className="font-mono text-xs text-[#3a4a53]">
              <span className="sr-only">Time </span>
              {step.time}
            </div>
          </div>
          <div className="mt-2 rounded-md bg-[#f8fafb] px-3 py-2">
            <p className="text-xs font-semibold text-[#62717a]">Result</p>
            <p className="mt-1 break-words text-sm text-[#3a4a53]">{step.result}</p>
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

function StatusPill({ status, kind }: { status: string; kind: StepStatus }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-6 items-center rounded-md px-2 text-xs font-semibold",
        kind === "success" && "bg-[#e7f6ed] text-[#1f6b3a]",
        kind === "warning" && "bg-[#fff4d7] text-[#8a5a00]",
        kind === "failed" && "bg-[#fff0f0] text-[#8c2525]",
        kind === "skipped" && "bg-[#eef4f6] text-[#62717a]",
        kind === "neutral" && "bg-[#f8fafb] text-[#3a4a53]",
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
  const timings = run.timings;
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
  const possibleReferences = stringArray(hypothesisTrace?.possible_references);
  const targetTerms = targetTermValues(hypothesisTrace?.target_terms);
  const referenceResults = referenceResultValues(verificationTrace?.possible_reference_results);
  const answerStatus =
    textValue(run.token_metadata.llm_answer_status) ??
    (run.timings.answer_fallback ? "fallback" : run.status);
  const steps: PathwayStep[] = [
    step("1", "Planner", textValue(plannerTrace?.query_hypothesis_status) ?? "recorded", numberValue(timings.planner_ms), plannerResult(plannerTrace)),
    step("2", "LLM planning", textValue(hypothesisTrace?.status) ?? textValue(timings.query_hypothesis_status) ?? "not recorded", numberValue(timings.query_hypothesis_ms), listSummary("terms", targetTerms)),
    step("3", "Metadata retrieval", metadataPassStatus(metadataPasses), numberValue(timings.metadata_ms), metadataResult(metadataPasses)),
    step("4", "Native retrieval", timings.native_degraded ? "degraded" : textValue(retrievalTrace?.native_status) ?? "ok", numberValue(timings.native_stage_ms), textValue(timings.native_error) ?? countSummary("candidates", numberValue(retrievalTrace?.native_candidates))),
    step("5", "Seed fusion", "ok", numberValue(timings.initial_fusion_ms), countSummary("seed candidates", numberValue(seedFusionTrace?.seed_candidates))),
    step("6", "Graph expansion", textValue(graphTrace?.status) ?? "not recorded", numberValue(timings.graph_ms), countSummary("expanded candidates", numberValue(graphTrace?.expanded_candidates))),
    step("7", "Graph hydration", textValue(graphHydrationTrace?.status) ?? "not recorded", numberValue(timings.graph_hydration_ms), countSummary("hydrated chunks", numberValue(graphHydrationTrace?.unique_hydrated_chunks))),
    step("8", "Final fusion", "ok", numberValue(timings.final_fusion_ms), countSummary("fused candidates", numberValue(finalFusionTrace?.fused_candidates))),
    step("9", "Hypothesis verification", textValue(verificationTrace?.status) ?? "not recorded", undefined, referenceResults || textValue(verificationTrace?.reason) || "not recorded"),
    step("10", "Context assembly", "ok", numberValue(timings.context_assembly_ms), countSummary("included candidates", numberValue(contextTrace?.included_candidates))),
    step("11", "Answer generation", answerStatus, numberValue(timings.answer_ms), answerResult(run)),
    step("12", "Grounding validation", textValue(groundingTrace?.status) ?? "not recorded", undefined, groundingResult(groundingTrace)),
  ];

  return {
    steps,
    topReference,
    topSource: textValue(topSource?.chunk_id) ?? textValue(topSource?.id) ?? "not recorded",
    plannerStatus: textValue(hypothesisTrace?.status) ?? textValue(timings.query_hypothesis_status) ?? "not recorded",
    plannerTimeout: formatMs(numberValue(timings.query_hypothesis_timeout_ms)),
    targetTerms: targetTerms.length ? targetTerms.join(", ") : "not recorded",
    possibleReferences: possibleReferences.length ? possibleReferences.join(", ") : "none",
    referenceVerification: referenceResults || "not recorded",
    metadataResult: metadataResult(metadataPasses),
    nativeResult: textValue(timings.native_error) ?? countSummary("native candidates", numberValue(retrievalTrace?.native_candidates)),
    graphResult: countSummary("expanded candidates", numberValue(graphTrace?.expanded_candidates)),
    fusionResult: countSummary("fused candidates", numberValue(finalFusionTrace?.fused_candidates)),
    answerStatus,
    answerFallback: run.timings.answer_fallback
      ? textValue(run.token_metadata.fallback_reason) ?? "answer fallback"
      : "none",
    groundingStatus: textValue(groundingTrace?.status) ?? "not recorded",
  };
}

function step(stepId: string, pathway: string, status: string, timeMs: number | undefined, result: string): PathwayStep {
  return {
    step: stepId,
    pathway,
    status,
    statusKind: statusKind(status),
    time: formatMs(timeMs),
    result,
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
  return "neutral";
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

function stringArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

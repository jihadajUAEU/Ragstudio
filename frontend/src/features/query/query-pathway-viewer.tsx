import { X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import type { PathwayDiagnosticOut, RunOut } from "../../api/generated";
import { FocusTrapDialog } from "../../components/focus-trap-dialog";
import { Button } from "../../components/ui/button";
import { cn } from "../../lib/utils";
import { buildThreePillarTrace, type ThreePillarTraceSummary } from "./three-pillar-trace";

type StepStatus = "success" | "warning" | "failed" | "skipped" | "unknown";
type PathwayTab = "domain" | "layout" | "context" | "raw";

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
  const [activeTab, setActiveTab] = useState<PathwayTab>("domain");
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
            <TabList activeTab={activeTab} onChange={setActiveTab} />
            {activeTab === "domain" ? <DomainAwareTab architecture={pathway.architecture} /> : null}
            {activeTab === "layout" ? <LayoutAwareTab architecture={pathway.architecture} /> : null}
            {activeTab === "context" ? (
              <ContextAwareTab architecture={pathway.architecture} steps={pathway.steps} />
            ) : null}
            {activeTab === "raw" ? (
              <PathwaySection title="Raw traces" defaultOpen>
                <JsonBlock
                  value={{
                    timings: run.timings,
                    chunk_traces: run.chunk_traces,
                    token_metadata: run.token_metadata,
                    pathway_diagnostics: run.pathway_diagnostics,
                  }}
                />
              </PathwaySection>
            ) : null}
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

function TabList({
  activeTab,
  onChange,
}: {
  activeTab: PathwayTab;
  onChange: (tab: PathwayTab) => void;
}) {
  const tabs: Array<{ id: PathwayTab; label: string }> = [
    { id: "domain", label: "Domain-aware" },
    { id: "layout", label: "Layout-aware" },
    { id: "context", label: "Context-aware" },
    { id: "raw", label: "Raw traces" },
  ];
  return (
    <div
      className="grid grid-cols-2 gap-1 rounded-md border border-[#d6dde1] bg-[#f8fafb] p-1 sm:grid-cols-4"
      role="tablist"
      aria-label="Three-pillar pathway tabs"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={cn(
            "min-h-9 rounded px-2 text-sm font-medium",
            activeTab === tab.id
              ? "bg-white text-[#174657] shadow-sm"
              : "text-[#62717a] hover:text-[#174657]",
          )}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function DomainAwareTab({ architecture }: { architecture: ThreePillarTraceSummary }) {
  return (
    <>
      <PathwaySection title="Route plan" defaultOpen>
        <ArchitectureRoute route={architecture.route} />
      </PathwaySection>
      <PathwaySection title="Lane results" defaultOpen>
        <LaneResults lanes={architecture.lanes} />
      </PathwaySection>
    </>
  );
}

function LayoutAwareTab({ architecture }: { architecture: ThreePillarTraceSummary }) {
  return (
    <>
      <PathwaySection title="Layout neighbors" defaultOpen>
        <LayoutNeighbors layout={architecture.layout} />
      </PathwaySection>
      <PathwaySection title="Layout summaries">
        <ListValue
          label="Summaries"
          values={architecture.layout.layoutSummaries.map((item) => `${item.chunkId}: ${item.summary}`)}
        />
      </PathwaySection>
    </>
  );
}

function ContextAwareTab({
  architecture,
  steps,
}: {
  architecture: ThreePillarTraceSummary;
  steps: PathwayStep[];
}) {
  return (
    <>
      <PathwaySection title="Context window" defaultOpen>
        <ContextWindowDetails context={architecture.context} />
      </PathwaySection>
      <PathwaySection title="Context assembly" defaultOpen>
        <ContextAssemblyDetails assembly={architecture.assembly} />
      </PathwaySection>
      <PathwaySection title="Reranker rank changes">
        <RerankerRankChanges reranker={architecture.reranker} />
      </PathwaySection>
      <PathwaySection title="Timeline">
        <Timeline steps={steps} />
      </PathwaySection>
    </>
  );
}

function ArchitectureRoute({ route }: { route: ThreePillarTraceSummary["route"] }) {
  return (
    <>
      <KeyValue label="Domain profile" value={route.domainProfileId} />
      <KeyValue label="Layout hint" value={route.layoutHint} />
      <KeyValue label="Materialization" value={route.materializationHint} />
      <KeyValue label="Source of truth" value={route.sourceOfTruth} />
      <KeyValue label="Direct evidence" value={route.directEvidenceRequired ? "required" : "not required"} />
      <KeyValue label="Graph context" value={route.graphContextRequired ? "required" : "not required"} />
    </>
  );
}

function LaneResults({ lanes }: { lanes: ThreePillarTraceSummary["lanes"] }) {
  if (!lanes.length) {
    return <MissingValue>No lane traces recorded</MissingValue>;
  }
  return (
    <div className="grid gap-2 sm:col-span-2">
      {lanes.map((lane) => (
        <div key={`${lane.lane}-${lane.reason}`} className="rounded-md border border-[#e1e7ea] bg-[#f8fafb] p-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <KeyValue label="Lane" value={lane.lane} />
            <KeyValue label="Status" value={lane.status} />
            <KeyValue label="Candidates" value={lane.candidateCount === null ? "not recorded" : String(lane.candidateCount)} />
            <KeyValue label="Latency" value={formatMs(lane.latencyMs ?? undefined)} />
          </div>
          <p className="mt-2 break-words text-xs text-[#62717a]">{lane.reason}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {lane.timedOut ? <StatusPill status="timeout" kind="warning" /> : null}
            {lane.partial ? <StatusPill status="partial" kind="warning" /> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function LayoutNeighbors({ layout }: { layout: ThreePillarTraceSummary["layout"] }) {
  return (
    <>
      <KeyValue label="Status" value={layout.status} />
      <KeyValue label="Reason" value={layout.reason} />
      <KeyValue label="Candidates" value={layout.candidateCount === null ? "not recorded" : String(layout.candidateCount)} />
      <KeyValue label="Reading order" value={layout.readingOrderNeighbors ? "yes" : "no"} />
      <ListValue label="Layout groups" values={layout.layoutGroupIds} />
      <ListValue label="Canonical chunks" values={layout.canonicalChunkIds} />
    </>
  );
}

function ContextWindowDetails({ context }: { context: ThreePillarTraceSummary["context"] }) {
  return (
    <>
      <KeyValue label="Status" value={context.status} />
      <KeyValue label="Reason" value={context.reason} />
      <KeyValue label="Candidates" value={context.candidateCount === null ? "not recorded" : String(context.candidateCount)} />
      <ListValue
        label="Relationship reasons"
        values={context.relationshipReasons.map((item) => `${item.chunkId}: ${item.reason}`)}
      />
    </>
  );
}

function ContextAssemblyDetails({ assembly }: { assembly: ThreePillarTraceSummary["assembly"] }) {
  return (
    <>
      <KeyValue label="Included" value={assembly.includedCandidates === null ? "not recorded" : String(assembly.includedCandidates)} />
      <KeyValue label="Dropped" value={assembly.droppedCandidates === null ? "not recorded" : String(assembly.droppedCandidates)} />
      <KeyValue label="Grounding" value={assembly.groundingStatus} />
      <KeyValue label="Breadcrumbs" value={assembly.breadcrumbsVisible ? "visible" : "not recorded"} />
      <ListValue label="Evidence ids" values={assembly.evidenceIds} />
      <ListValue
        label="Dropped reasons"
        values={assembly.droppedReasons.map((item) => `${item.candidateId}: ${item.reason}`)}
      />
    </>
  );
}

function RerankerRankChanges({ reranker }: { reranker: ThreePillarTraceSummary["reranker"] }) {
  if (!reranker.rankDeltas.length) {
    return <MissingValue>No rank deltas recorded</MissingValue>;
  }
  return (
    <div className="grid gap-2 sm:col-span-2">
      <div className="grid gap-2 sm:grid-cols-3">
        <KeyValue label="Status" value={reranker.status} />
        <KeyValue label="Provider" value={reranker.provider} />
        <KeyValue label="Model" value={reranker.model} />
      </div>
      {reranker.rankDeltas.map((delta) => (
        <div key={delta.candidateId} className="grid gap-2 rounded-md bg-[#f8fafb] px-3 py-2 sm:grid-cols-3">
          <KeyValue label="Candidate" value={delta.candidateId} />
          <KeyValue label="Rank" value={`${delta.before} -> ${delta.after}`} />
          <KeyValue label="Delta" value={String(delta.delta)} />
        </div>
      ))}
    </div>
  );
}

function ListValue({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="min-w-0 rounded-md bg-[#f8fafb] px-3 py-2 sm:col-span-2">
      <p className="text-xs font-semibold text-[#62717a]">{label}</p>
      <p className="mt-1 break-words text-sm text-[#24313a]">{values.length ? values.join(", ") : "not recorded"}</p>
    </div>
  );
}

function MissingValue({ children }: { children: ReactNode }) {
  return <p className="text-sm text-[#62717a] sm:col-span-2">{children}</p>;
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
    architecture: buildThreePillarTrace(run),
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

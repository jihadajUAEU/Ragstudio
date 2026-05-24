import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock,
  Database,
  FileCheck2,
  GitBranch,
  ShieldCheck,
} from "lucide-react";

import type {
  DocumentPipelineEventOut,
  DocumentPipelineStageOut,
  DocumentPipelineTimelineOut,
  DocumentPipelineWarningGroupOut,
  PipelineStageState,
} from "../../api/generated";

export function DocumentPipelineStageFlow({
  timeline,
}: {
  timeline: DocumentPipelineTimelineOut;
}) {
  const orderedStages = useMemo(
    () => [...timeline.stages].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id)),
    [timeline.stages],
  );
  const [selectedStageId, setSelectedStageId] = useState(() => pickInitialStageId(orderedStages));
  const selectedStage =
    orderedStages.find((stage) => stage.id === selectedStageId) ?? orderedStages[0] ?? null;

  return (
    <section
      aria-label="Document stage flow"
      className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)]"
    >
      <header className="flex flex-col gap-3 border-b border-[var(--rs-line)] bg-[var(--rs-panel)] px-4 py-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-[var(--rs-ink)]">Document stage flow</h2>
          <p className="mt-1 truncate text-sm text-[var(--rs-text)]">{timeline.filename}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-medium">
          <Metric label={`${timeline.totals.jobs} jobs`} />
          <Metric label={`${timeline.totals.chunks} chunks`} />
          <Metric label={`${timeline.totals.warnings} warnings`} tone="warning" />
          <Metric label={`${timeline.totals.graph_nodes} graph nodes`} />
        </div>
      </header>

      <StageRail stages={orderedStages} />

      <div className="grid items-start gap-0 border-t border-[var(--rs-line)] lg:grid-cols-[280px_minmax(0,1fr)_320px]">
        <FlowMap
          stages={orderedStages}
          selectedStageId={selectedStage?.id ?? null}
          onSelectStage={setSelectedStageId}
        />
        <EventLedger events={timeline.events} />
        <StageInspector
          stage={selectedStage}
          contract={timeline.contract}
          warningGroups={timeline.warning_groups}
        />
      </div>
    </section>
  );
}

function StageRail({ stages }: { stages: DocumentPipelineStageOut[] }) {
  if (stages.length === 0) {
    return <p className="px-4 py-3 text-sm text-[var(--rs-muted)]">No stages recorded.</p>;
  }

  return (
    <div className="overflow-x-auto px-4 py-3" aria-label="Compact stage rail">
      <div
        className="grid min-w-[720px] gap-2"
        style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(0, 1fr))` }}
      >
        {stages.map((stage) => (
          <div key={stage.id} className="min-w-0">
            <div className={`h-2 rounded-full ${railClass(stage.state)}`} />
            <p className="mt-2 truncate text-xs font-medium text-[var(--rs-ink)]">{stage.label}</p>
            <p className="truncate text-[11px] text-[var(--rs-muted)]">{stateLabel(stage.state)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function FlowMap({
  stages,
  selectedStageId,
  onSelectStage,
}: {
  stages: DocumentPipelineStageOut[];
  selectedStageId: string | null;
  onSelectStage: (stageId: string) => void;
}) {
  return (
    <nav
      className="border-b border-[var(--rs-line)] bg-[var(--rs-field)] p-3 lg:border-b-0 lg:border-r"
      aria-label="Actual document flow"
    >
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--rs-muted)]">
        Actual flow
      </p>
      <div className="grid gap-2">
        {stages.map((stage) => {
          const Icon = iconForStage(stage);
          const selected = stage.id === selectedStageId;
          return (
            <button
              key={stage.id}
              type="button"
              className={`grid grid-cols-[auto_minmax(0,1fr)] gap-2 rounded-md border p-2 text-left transition ${
                selected
                  ? "border-[var(--rs-accent)] bg-[var(--rs-paper)]"
                  : "border-[var(--rs-line)] bg-[var(--rs-paper)] hover:border-[var(--rs-accent)]"
              }`}
              aria-pressed={selected}
              onClick={() => onSelectStage(stage.id)}
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-md border border-[var(--rs-line)]">
                <Icon className="h-4 w-4 text-[var(--rs-accent)]" aria-hidden="true" />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-[var(--rs-ink)]">
                  {stage.label}
                </span>
                <span className="block truncate text-xs text-[var(--rs-muted)]">
                  {stateLabel(stage.state)}
                  {stage.progress !== null ? ` - ${stage.progress}%` : ""}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

function EventLedger({ events }: { events: DocumentPipelineEventOut[] }) {
  return (
    <section className="border-b border-[var(--rs-line)] p-3 lg:border-b-0 lg:border-r">
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--rs-muted)]">
        Stage event ledger
      </p>
      {events.length ? (
        <ol className="grid gap-2 overflow-y-auto pr-1" style={{ maxHeight: 620 }}>
          {events.map((event) => (
            <li
              key={`${event.sequence}-${event.stage_id}-${event.job_id ?? "document"}`}
              className="grid gap-1 rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-2 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-[var(--rs-ink)]">{event.label}</span>
                <span className="rounded-md border border-[var(--rs-line)] px-2 py-0.5 text-xs text-[var(--rs-muted)]">
                  {sourceLabel(event.source)}
                </span>
                {event.progress !== null ? (
                  <span className="text-xs text-[var(--rs-muted)]">{event.progress}%</span>
                ) : null}
              </div>
              <p className="break-words text-xs leading-5 text-[var(--rs-text)]">{event.detail}</p>
              {event.warning ? (
                <p className="w-fit rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-xs font-medium text-[#705000]">
                  {event.warning}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-[var(--rs-muted)]">No stage events are recorded.</p>
      )}
    </section>
  );
}

function StageInspector({
  stage,
  contract,
  warningGroups,
}: {
  stage: DocumentPipelineStageOut | null;
  contract: DocumentPipelineTimelineOut["contract"];
  warningGroups: DocumentPipelineWarningGroupOut[];
}) {
  if (!stage) {
    return (
      <section
        aria-label="Selected stage inspector"
        className="bg-[var(--rs-panel)] p-3 text-sm text-[var(--rs-muted)]"
      >
        No stage selected.
      </section>
    );
  }

  return (
    <section aria-label="Selected stage inspector" className="bg-[var(--rs-panel)] p-3">
      <div className="mb-3">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--rs-muted)]">
          Selected stage
        </p>
        <h3 className="mt-1 text-base font-semibold text-[var(--rs-ink)]">{stage.label}</h3>
        <p className="mt-1 text-sm leading-5 text-[var(--rs-text)]">{stage.detail}</p>
      </div>

      <div className="grid gap-2 text-sm">
        <InspectorRow label="State" value={stage.state} />
        <InspectorRow label="Source" value={sourceLabel(stage.source)} />
        <InspectorRow label="Events" value={String(stage.event_count)} />
        {stage.chunk_count !== null ? (
          <InspectorRow label="Chunks" value={String(stage.chunk_count)} />
        ) : null}
      </div>

      {stage.id === "contract" ? <ContractInspector contract={contract} /> : null}
      {stage.id === "quality_gates" ? <WarningGroupList warningGroups={warningGroups} /> : null}
    </section>
  );
}

function ContractInspector({
  contract,
}: {
  contract: DocumentPipelineTimelineOut["contract"];
}) {
  const facts = [
    contract.contract_status,
    `verified=${String(contract.verified)}`,
    `canonical_units=${String(contract.canonical_units)}`,
    contract.schema_type,
    `repair=${contract.repair_status ?? "unknown"}`,
    `validation=${contract.validation_status ?? "unknown"}`,
    `matched_units=${String(contract.validation_matched_units ?? 0)}`,
  ].filter((item): item is string => Boolean(item));

  return (
    <div className="mt-4 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-3">
      <p className="text-sm font-semibold text-[var(--rs-ink)]">Contract proof boundary</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {facts.map((fact) => (
          <span
            key={fact}
            className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] px-2 py-1 text-xs text-[var(--rs-text)]"
          >
            {fact}
          </span>
        ))}
      </div>
      {contract.rejection_reasons.length ? (
        <ul className="mt-3 grid gap-1 text-xs text-[var(--rs-muted)]">
          {contract.rejection_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function WarningGroupList({
  warningGroups,
}: {
  warningGroups: DocumentPipelineWarningGroupOut[];
}) {
  return (
    <div className="mt-4 rounded-md border border-[var(--rs-line)] bg-[var(--rs-paper)] p-3">
      <p className="text-sm font-semibold text-[var(--rs-ink)]">Warning groups</p>
      {warningGroups.length ? (
        <div className="mt-2 grid gap-2">
          {warningGroups.map((group) => (
            <div
              key={`${group.code}-${group.expected_script ?? "none"}`}
              className="rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] p-2 text-xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-[var(--rs-ink)]">{group.code}</span>
                <span className="text-[var(--rs-muted)]">{group.count}</span>
                {group.expected_script ? (
                  <span className="rounded-md border border-[var(--rs-line)] px-2 py-0.5 text-[var(--rs-text)]">
                    {group.expected_script}
                  </span>
                ) : null}
              </div>
              {group.message ? (
                <p className="mt-1 text-[var(--rs-muted)]">{group.message}</p>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-[var(--rs-muted)]">No warning groups recorded.</p>
      )}
    </div>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[var(--rs-line)] py-1 last:border-b-0">
      <span className="text-[var(--rs-muted)]">{label}</span>
      <span className="min-w-0 break-words text-right font-medium text-[var(--rs-text)]">{value}</span>
    </div>
  );
}

function Metric({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "warning" }) {
  return (
    <span
      className={
        tone === "warning"
          ? "rounded-md border border-[#e2c46b] bg-[#fff8df] px-2 py-1 text-[#705000]"
          : "rounded-md border border-[var(--rs-line)] bg-[var(--rs-field)] px-2 py-1 text-[var(--rs-text)]"
      }
    >
      {label}
    </span>
  );
}

function pickInitialStageId(stages: DocumentPipelineStageOut[]) {
  return (
    stages.find((stage) => stage.is_current)?.id ??
    stages.find((stage) => stage.state === "failed" || stage.state === "blocked")?.id ??
    stages.find((stage) => stage.state === "warning")?.id ??
    stages.find((stage) => stage.state === "metadata_only")?.id ??
    stages[0]?.id ??
    ""
  );
}

function iconForStage(stage: DocumentPipelineStageOut) {
  if (stage.state === "warning" || stage.warning_count > 0) {
    return AlertTriangle;
  }
  if (stage.state === "running") {
    return Clock;
  }
  if (stage.id.includes("contract")) {
    return ShieldCheck;
  }
  if (stage.id.includes("graph")) {
    return GitBranch;
  }
  if (stage.id.includes("chunk") || stage.id.includes("materialization")) {
    return Database;
  }
  if (stage.id.includes("ready") || stage.state === "complete") {
    return CheckCircle2;
  }
  if (stage.id.includes("upload") || stage.id.includes("vision")) {
    return FileCheck2;
  }
  return Circle;
}

function railClass(state: PipelineStageState) {
  switch (state) {
    case "complete":
      return "bg-[#20a464]";
    case "running":
      return "bg-[#2563eb]";
    case "warning":
    case "metadata_only":
      return "bg-[#d88b00]";
    case "blocked":
    case "failed":
      return "bg-[var(--rs-danger)]";
    case "skipped":
      return "bg-[#94a3b8]";
    case "pending":
    default:
      return "bg-[#cbd5e1]";
  }
}

function stateLabel(state: PipelineStageState) {
  return state.replaceAll("_", " ");
}

function sourceLabel(source: DocumentPipelineEventOut["source"]) {
  if (source === "structured_event") {
    return "structured";
  }
  if (source === "inferred_log") {
    return "inferred from log";
  }
  return source.replaceAll("_", " ");
}

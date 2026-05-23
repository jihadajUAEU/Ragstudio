import {
  AlertCircle,
  AlertTriangle,
  Box,
  ChevronLeft,
  ChevronRight,
  FileCode2,
  Filter,
  GitCommit,
  Info,
  RotateCcw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

import { EmptyState } from "../../components/empty-state";
import { Button } from "../../components/ui/button";
import { rs } from "../../lib/design-tokens";
import { cn, titleCase } from "../../lib/utils";
import type {
  ChunkEvidence,
  DiffRowEvidence,
  DocumentParseEvidence,
  EvidenceMode,
  NormalizationDecisionEvidence,
  ParserBlockEvidence,
  SourceArtifactEvidence,
  WarningEvidence,
} from "./types";

export function EvidenceInspector({
  evidence,
  mode = "local",
  onReindex,
}: {
  evidence: DocumentParseEvidence;
  mode?: EvidenceMode;
  onReindex?: () => void;
}) {
  const decisions = evidence.normalization_decisions;
  const [selectedDecisionId, setSelectedDecisionId] = useState(decisions[0]?.id ?? "");
  const [search, setSearch] = useState("");
  const [decisionType, setDecisionType] = useState("all");
  const [warningCode, setWarningCode] = useState("all");
  const [pageFilter, setPageFilter] = useState("all");
  const [quickFilter, setQuickFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const warningsById = useMemo(
    () => new Map(evidence.warnings.map((warning) => [warning.id, warning])),
    [evidence.warnings],
  );
  const blocksById = useMemo(
    () => new Map(evidence.parser_blocks.map((block) => [block.id, block])),
    [evidence.parser_blocks],
  );
  const chunksById = useMemo(
    () => new Map(evidence.chunks.map((chunk) => [chunk.id, chunk])),
    [evidence.chunks],
  );
  const evidenceRows = useMemo(
    () =>
      decisions.map((decision) => {
        const rowWarnings = orderByIds(evidence.warnings, decision.warning_ids);
        const rowBlocks = orderByIds(evidence.parser_blocks, decision.input_block_ids);
        const rowChunks = orderByIds(evidence.chunks, decision.output_chunk_ids);
        return {
          decision,
          warnings: rowWarnings,
          blocks: rowBlocks,
          chunks: rowChunks,
          pages: pagesForDecision(rowWarnings, rowBlocks, rowChunks),
          text: decisionSearchText(decision, rowWarnings, rowBlocks, rowChunks),
        };
      }),
    [decisions, evidence.chunks, evidence.parser_blocks, evidence.warnings],
  );
  const metrics = useMemo(() => evidenceMetrics(evidence), [evidence]);
  const decisionTypeOptions = useMemo(() => countBy(decisions, (decision) => decision.decision_type), [decisions]);
  const warningCodeOptions = useMemo(
    () => countBy(evidenceRows.flatMap((row) => row.warnings), (warning) => warning.code),
    [evidenceRows],
  );
  const pageOptions = useMemo(
    () =>
      Array.from(
        new Set(
          evidenceRows
            .flatMap((row) => row.pages)
            .filter((pageNumber): pageNumber is number => typeof pageNumber === "number"),
        ),
      ).sort((left, right) => left - right),
    [evidenceRows],
  );
  const filteredRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return evidenceRows.filter((row) => {
      if (decisionType !== "all" && row.decision.decision_type !== decisionType) {
        return false;
      }
      if (warningCode !== "all" && !row.warnings.some((warning) => warning.code === warningCode)) {
        return false;
      }
      if (pageFilter !== "all" && !row.pages.includes(Number(pageFilter))) {
        return false;
      }
      if (quickFilter === "audit" && !row.warnings.some((warning) => !isCountedWarning(warning))) {
        return false;
      }
      if (quickFilter === "counted" && !row.warnings.some(isCountedWarning)) {
        return false;
      }
      return !needle || row.text.includes(needle);
    });
  }, [decisionType, evidenceRows, pageFilter, quickFilter, search, warningCode]);
  const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const boundedPage = Math.min(page, pageCount);
  const pagedRows = filteredRows.slice((boundedPage - 1) * pageSize, boundedPage * pageSize);
  const selectedDecision =
    filteredRows.find((row) => row.decision.id === selectedDecisionId)?.decision ??
    filteredRows[0]?.decision ??
    decisions.find((decision) => decision.id === selectedDecisionId) ??
    decisions[0] ??
    null;
  const selectedBlocks = selectedDecision
    ? orderByIds(evidence.parser_blocks, selectedDecision.input_block_ids)
    : [];
  const selectedChunks = selectedDecision ? orderByIds(evidence.chunks, selectedDecision.output_chunk_ids) : [];
  const selectedWarnings = selectedDecision ? orderByIds(evidence.warnings, selectedDecision.warning_ids) : [];
  const selectedRow = selectedDecision
    ? evidenceRows.find((row) => row.decision.id === selectedDecision.id) ?? null
    : null;

  useEffect(() => {
    setPage(1);
  }, [search, decisionType, warningCode, pageFilter, quickFilter, pageSize]);

  return (
    <div className={cn(rs.font.body, "mx-auto max-w-7xl space-y-4")}>
      <section>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className={cn(rs.font.display, "text-[28px] font-semibold", rs.text.ink)}>
              Document parse evidence
            </h1>
            <p className={cn("mt-2 truncate text-lg font-semibold", rs.text.body)}>
              {evidence.document.filename}
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Pill>{titleCase(evidence.document.status)}</Pill>
              <Pill>{evidence.document.content_type}</Pill>
              <Pill>{evidence.document.parser_mode ?? "Parser mode not recorded"}</Pill>
              {evidence.document.page_count != null ? <Pill>{evidence.document.page_count} pages</Pill> : null}
              <Pill>Proof {titleCase(evidence.proof.mode.replaceAll("-", " "))}</Pill>
              {evidence.proof.limitations.length ? <Pill tone="warning">Preview capped</Pill> : null}
            </div>
          </div>
          {mode === "local" && onReindex ? (
            <Button type="button" variant="secondary" onClick={onReindex}>
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Reindex document
            </Button>
          ) : null}
        </div>

        {evidence.missing_sections.length ? (
          <div
            className={cn(
              "mt-4 rounded-md border p-3 text-sm",
              rs.border.warning,
              rs.bg.warningSoft,
              rs.text.warning,
            )}
          >
            <p className="font-semibold">Evidence unavailable</p>
            <p className="mt-1">{evidence.missing_sections.join(", ")}</p>
          </div>
        ) : null}
      </section>

      <MetricsGrid metrics={metrics} />

      <CountModelNotice evidence={evidence} metrics={metrics} />

      <EvidenceToolbar
        search={search}
        onSearch={setSearch}
        decisionType={decisionType}
        onDecisionType={setDecisionType}
        decisionTypeOptions={decisionTypeOptions}
        warningCode={warningCode}
        onWarningCode={setWarningCode}
        warningCodeOptions={warningCodeOptions}
        pageFilter={pageFilter}
        onPageFilter={setPageFilter}
        pageOptions={pageOptions}
        onClear={() => {
          setSearch("");
          setDecisionType("all");
          setWarningCode("all");
          setPageFilter("all");
          setQuickFilter("all");
        }}
      />

      <QuickTabs
        metrics={metrics}
        quickFilter={quickFilter}
        onQuickFilter={setQuickFilter}
        decisionType={decisionType}
        onDecisionType={setDecisionType}
      />

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <EvidenceRail
          rows={pagedRows}
          allRows={filteredRows}
          page={boundedPage}
          pageCount={pageCount}
          pageSize={pageSize}
          onPageSize={setPageSize}
          onPage={setPage}
          selectedDecisionId={selectedDecision?.id ?? ""}
          onSelect={setSelectedDecisionId}
          blocksById={blocksById}
          chunksById={chunksById}
        />

        <section
          className="min-w-0"
          aria-label={selectedDecision ? `${selectedDecision.title} evidence detail` : "Evidence detail"}
        >
          {selectedDecision ? (
            <div className="space-y-4">
              <DecisionSummary decision={selectedDecision} warnings={selectedWarnings} row={selectedRow} />
              <div className="grid gap-3 lg:grid-cols-3">
                <EvidencePanel title="Source blocks">
                  {selectedBlocks.length ? (
                    <div className="grid gap-2">
                      {selectedBlocks.map((block) => (
                        <BlockCard key={block.id} block={block} warningsById={warningsById} />
                      ))}
                    </div>
                  ) : (
                    <MissingText>Source blocks not recorded for this decision.</MissingText>
                  )}
                </EvidencePanel>
                <EvidencePanel title="Normalized unit">
                  <DiffPanel decision={selectedDecision} blocks={selectedBlocks} chunks={selectedChunks} />
                </EvidencePanel>
                <EvidencePanel title="Chunk output">
                  {selectedChunks.length ? (
                    <div className="grid gap-2">
                      {selectedChunks.map((chunk) => (
                        <ChunkCard key={chunk.id} chunk={chunk} />
                      ))}
                    </div>
                  ) : (
                    <MissingText>Chunk output not recorded for this decision.</MissingText>
                  )}
                </EvidencePanel>
              </div>
              <EvidenceSubPanels warnings={selectedWarnings} chunks={selectedChunks} />
            </div>
          ) : (
            <EmptyState
              icon={AlertCircle}
              title="Evidence unavailable"
              description="No decisions were recorded."
              className={cn(rs.bg.paper, rs.border.line)}
            />
          )}
        </section>
      </div>

      <AllWarningsPanel warnings={evidence.warnings} />

      <ProofMetadataPanel evidence={evidence} />
    </div>
  );
}

type EvidenceRow = {
  decision: NormalizationDecisionEvidence;
  warnings: WarningEvidence[];
  blocks: ParserBlockEvidence[];
  chunks: ChunkEvidence[];
  pages: number[];
  text: string;
};

function MetricsGrid({ metrics }: { metrics: EvidenceMetrics }) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Evidence summary">
      <MetricCard label="Preview decisions" value={metrics.decisions} />
      <MetricCard label="All warning rows" value={metrics.warnings} tone="warning" />
      <MetricCard label="Preview blocks" value={metrics.blocks} />
      <MetricCard label="Total chunks" value={metrics.chunks} />
      <MetricCard label="Artifacts" value={metrics.artifacts} tone="success" />
    </section>
  );
}

function CountModelNotice({
  evidence,
  metrics,
}: {
  evidence: DocumentParseEvidence;
  metrics: EvidenceMetrics;
}) {
  const previewChunkCount = evidence.chunks.length;
  const totalChunkCount = evidence.totals?.chunks ?? previewChunkCount;
  const previewIsCapped = totalChunkCount > previewChunkCount;

  return (
    <section className={cn("rounded-md border px-3 py-2 text-sm", rs.border.line, rs.bg.field, rs.text.body)}>
      <p>
        The left evidence list shows normalization decisions from the chunk proof preview
        {previewIsCapped ? ` (${previewChunkCount} of ${totalChunkCount} chunks)` : ""}. The warning table below shows all
        warning rows available for the document ({metrics.warnings} rows).
      </p>
    </section>
  );
}

function MetricCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "success" | "warning";
}) {
  return (
    <div className={cn("rounded-md border p-3", rs.border.line, rs.bg.paper)}>
      <p
        className={cn(
          "text-2xl font-semibold leading-none",
          tone === "success" ? rs.text.success : tone === "warning" ? rs.text.warning : rs.text.ink,
        )}
      >
        {value}
      </p>
      <p className={cn("mt-1 text-xs font-semibold", rs.text.muted)}>{label}</p>
    </div>
  );
}

function EvidenceToolbar({
  search,
  onSearch,
  decisionType,
  onDecisionType,
  decisionTypeOptions,
  warningCode,
  onWarningCode,
  warningCodeOptions,
  pageFilter,
  onPageFilter,
  pageOptions,
  onClear,
}: {
  search: string;
  onSearch: (value: string) => void;
  decisionType: string;
  onDecisionType: (value: string) => void;
  decisionTypeOptions: Record<string, number>;
  warningCode: string;
  onWarningCode: (value: string) => void;
  warningCodeOptions: Record<string, number>;
  pageFilter: string;
  onPageFilter: (value: string) => void;
  pageOptions: number[];
  onClear: () => void;
}) {
  return (
    <section
      className={cn("grid gap-2 rounded-md border p-3 lg:grid-cols-[minmax(0,1fr)_160px_260px_120px_auto]", rs.border.line, rs.bg.paper)}
      aria-label="Evidence filters"
    >
      <label className="relative min-w-0">
        <span className="sr-only">Search evidence</span>
        <Search className={cn("pointer-events-none absolute left-3 top-2.5 h-4 w-4", rs.text.muted)} aria-hidden="true" />
        <input
          className={filterControlClass("pl-9")}
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Search evidence, warning code, page, block type, chunk id..."
        />
      </label>
      <SelectControl label="Decision type" value={decisionType} onChange={onDecisionType}>
        <option value="all">Type: All</option>
        {Object.entries(decisionTypeOptions).map(([type, count]) => (
          <option key={type} value={type}>
            {titleCase(type.replaceAll("_", " "))} ({count})
          </option>
        ))}
      </SelectControl>
      <SelectControl label="Warning code" value={warningCode} onChange={onWarningCode}>
        <option value="all">Decision warning: All</option>
        {Object.entries(warningCodeOptions).map(([code, count]) => (
          <option key={code} value={code}>
            {code} ({count})
          </option>
        ))}
      </SelectControl>
      <SelectControl label="Page" value={pageFilter} onChange={onPageFilter}>
        <option value="all">Page: All</option>
        {pageOptions.map((pageNumber) => (
          <option key={pageNumber} value={String(pageNumber)}>
            Page {pageNumber}
          </option>
        ))}
      </SelectControl>
      <Button type="button" variant="secondary" onClick={onClear}>
        <Filter className="h-4 w-4" aria-hidden="true" />
        Clear
      </Button>
    </section>
  );
}

function SelectControl({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <label className="min-w-0">
      <span className="sr-only">{label}</span>
      <select className={filterControlClass()} value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}

function QuickTabs({
  metrics,
  quickFilter,
  onQuickFilter,
  decisionType,
  onDecisionType,
}: {
  metrics: EvidenceMetrics;
  quickFilter: string;
  onQuickFilter: (value: string) => void;
  decisionType: string;
  onDecisionType: (value: string) => void;
}) {
  const tabs = [
    {
      id: "all",
      label: `Preview decisions ${metrics.decisions}`,
      active: quickFilter === "all" && decisionType === "all",
      onClick: () => {
        onQuickFilter("all");
        onDecisionType("all");
      },
    },
    {
      id: "quality_warning",
      label: `Decision quality ${metrics.qualityWarnings}`,
      active: decisionType === "quality_warning",
      onClick: () => {
        onQuickFilter("all");
        onDecisionType("quality_warning");
      },
    },
    {
      id: "page_stitch",
      label: `Page stitch ${metrics.pageStitches}`,
      active: decisionType === "page_stitch",
      onClick: () => {
        onQuickFilter("all");
        onDecisionType("page_stitch");
      },
    },
    {
      id: "chunk_materialization",
      label: `Materialization ${metrics.materializations}`,
      active: decisionType === "chunk_materialization",
      onClick: () => {
        onQuickFilter("all");
        onDecisionType("chunk_materialization");
      },
    },
    {
      id: "audit",
      label: `Preview audit decisions ${metrics.previewAuditDecisionRows}`,
      active: quickFilter === "audit",
      onClick: () => {
        onDecisionType("all");
        onQuickFilter("audit");
      },
    },
    {
      id: "counted",
      label: `Preview counted decisions ${metrics.previewCountedDecisionRows}`,
      active: quickFilter === "counted",
      onClick: () => {
        onDecisionType("all");
        onQuickFilter("counted");
      },
    },
  ];
  return (
    <div className="flex flex-wrap gap-2" aria-label="Evidence quick filters">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={tab.onClick}
          className={cn(
            "min-h-9 rounded-md border px-3 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
            rs.focus.ring,
            rs.focus.offset,
            tab.active ? cn(rs.border.accent, rs.bg.accentSoft, rs.text.accentDeep) : cn(rs.border.line, rs.bg.paper, rs.text.body),
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function EvidenceRail({
  rows,
  allRows,
  page,
  pageCount,
  pageSize,
  onPageSize,
  onPage,
  selectedDecisionId,
  onSelect,
  blocksById,
  chunksById,
}: {
  rows: EvidenceRow[];
  allRows: EvidenceRow[];
  page: number;
  pageCount: number;
  pageSize: number;
  onPageSize: (value: number) => void;
  onPage: (value: number) => void;
  selectedDecisionId: string;
  onSelect: (id: string) => void;
  blocksById: Map<string, ParserBlockEvidence>;
  chunksById: Map<string, ChunkEvidence>;
}) {
  const start = allRows.length ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, allRows.length);
  const selectByIndex = (index: number, currentTarget: EventTarget & HTMLElement) => {
    const boundedIndex = Math.max(0, Math.min(index, allRows.length - 1));
    const nextDecision = allRows[boundedIndex]?.decision;
    if (!nextDecision) {
      return;
    }
    onSelect(nextDecision.id);
    window.requestAnimationFrame(() => {
      currentTarget
        .querySelector<HTMLButtonElement>(`button[data-decision-id="${cssEscape(nextDecision.id)}"]`)
        ?.focus();
    });
  };

  const handleKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    decision: NormalizationDecisionEvidence,
  ) => {
    const currentIndex = allRows.findIndex((item) => item.decision.id === decision.id);
    if (currentIndex < 0) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      selectByIndex((currentIndex + 1) % allRows.length, event.currentTarget.parentElement ?? event.currentTarget);
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      selectByIndex(
        (currentIndex - 1 + allRows.length) % allRows.length,
        event.currentTarget.parentElement ?? event.currentTarget,
      );
    }
    if (event.key === "Home") {
      event.preventDefault();
      selectByIndex(0, event.currentTarget.parentElement ?? event.currentTarget);
    }
    if (event.key === "End") {
      event.preventDefault();
      selectByIndex(allRows.length - 1, event.currentTarget.parentElement ?? event.currentTarget);
    }
  };

  return (
    <aside className={cn("overflow-hidden rounded-md border", rs.border.line, rs.bg.paper)} aria-label="Evidence decisions">
      <div className={cn("flex items-center justify-between border-b px-3 py-3", rs.border.line)}>
        <div className="flex items-center gap-2">
          <ShieldCheck className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />
          <h2 className={cn("text-sm font-semibold", rs.text.ink)}>Evidence list</h2>
        </div>
        <span className={cn("text-xs font-semibold", rs.text.muted)}>
          Showing {start}-{end} of {allRows.length}
        </span>
      </div>
      {rows.length ? (
        <div className="max-h-[604px] overflow-hidden" aria-label="Evidence decisions">
          {rows.map((row) => {
            const decision = row.decision;
            const selected = decision.id === selectedDecisionId;
            const primaryWarning = row.warnings[0];
            const primaryBlock = decision.input_block_ids.flatMap((id) => blocksById.get(id) ?? [])[0];
            const primaryChunk = decision.output_chunk_ids.flatMap((id) => chunksById.get(id) ?? [])[0];
            return (
              <button
                key={decision.id}
                type="button"
                data-decision-id={decision.id}
                aria-pressed={selected}
                onClick={() => onSelect(decision.id)}
                onKeyDown={(event) => handleKeyDown(event, decision)}
                className={cn(
                  "grid min-h-[74px] w-full grid-cols-[minmax(0,1fr)_auto] gap-3 border-b px-3 py-3 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-offset-2",
                  rs.focus.ring,
                  rs.focus.offset,
                  selected
                    ? cn("shadow-[inset_3px_0_0_var(--rs-accent)]", rs.bg.accentSoft, rs.text.accentDeep)
                    : cn(rs.border.line, rs.bg.paper, rs.text.body, rs.hover.field),
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate font-semibold">
                    {decision.title}
                    {row.pages[0] ? ` - page ${row.pages[0]}` : ""}
                  </span>
                  <span className="mt-1 block truncate text-xs opacity-80">
                    {primaryWarning?.code ?? titleCase(decision.decision_type.replaceAll("_", " "))}
                    {primaryBlock?.block_type ? ` - ${primaryBlock.block_type}` : ""}
                  </span>
                  <span className="mt-1 block truncate text-xs opacity-80">
                    {row.warnings.length ? `${row.warnings.length} warning rows - ` : ""}
                    {decision.input_block_ids.length} block{decision.input_block_ids.length === 1 ? "" : "s"} -{" "}
                    {decision.output_chunk_ids.length || (primaryChunk ? 1 : 0)} chunk
                    {decision.output_chunk_ids.length === 1 ? "" : "s"}
                  </span>
                </span>
                <WarningBadge warnings={row.warnings} />
              </button>
            );
          })}
        </div>
      ) : (
        <div className="p-4">
          <MissingText>No decisions match the current filters.</MissingText>
        </div>
      )}
      <div className={cn("flex flex-wrap items-center justify-between gap-2 border-t px-3 py-3", rs.border.line, rs.bg.field)}>
        <Button type="button" variant="secondary" onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1}>
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          Previous
        </Button>
        <div className="flex items-center gap-2">
          <span className={cn("text-xs font-semibold", rs.text.muted)}>
            Page {page} of {pageCount}
          </span>
          <select
            className={filterControlClass("h-8 w-20 text-xs")}
            value={pageSize}
            onChange={(event) => onPageSize(Number(event.target.value))}
            aria-label="Evidence rows per page"
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </div>
        <Button type="button" variant="secondary" onClick={() => onPage(Math.min(pageCount, page + 1))} disabled={page >= pageCount}>
          Next
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </aside>
  );
}

function DecisionSummary({
  decision,
  warnings,
  row,
}: {
  decision: NormalizationDecisionEvidence;
  warnings: WarningEvidence[];
  row: EvidenceRow | null;
}) {
  const warningGroups = groupedDecisionWarnings(warnings);
  return (
    <section className={cn("rounded-md border p-4", rs.border.line, rs.bg.paper)}>
      <p className={cn("text-xs font-semibold uppercase", rs.text.muted)}>
        {titleCase(decision.status.replaceAll("_", " "))}
      </p>
      <h2 className={cn("mt-1 text-lg font-semibold", rs.text.ink)}>{decision.title}</h2>
      <p className={cn("mt-2 text-sm leading-6", rs.text.body)}>{decision.summary}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
        <Pill>{titleCase(decision.decision_type.replaceAll("_", " "))}</Pill>
        {row?.pages.length ? <Pill>page {row.pages.join(", ")}</Pill> : null}
        <Pill>{decision.input_block_ids.length} source blocks</Pill>
        <Pill>{decision.output_chunk_ids.length} chunk outputs</Pill>
      </div>
      {warningGroups.length ? (
        <div className="mt-3 grid gap-2">
          {warningGroups.map(({ key, warnings: groupWarnings }) => {
            const warning = groupWarnings[0];
            const recovery = isAcceptedRecoveryWarning(warning);
            return (
              <div
                key={key}
                className={cn(
                  "rounded-md border px-3 py-2 text-sm",
                  recovery ? cn(rs.border.success, rs.bg.successSoft) : cn(rs.border.warning, rs.bg.warningSoft),
                )}
                >
                <p className={cn("font-semibold", recovery ? rs.text.success : rs.text.warning)}>
                  {recovery ? "Recovered text" : warning.code}
                  {groupWarnings.length > 1 ? (
                    <span className="ml-2 text-xs font-semibold opacity-80">
                      {groupWarnings.length} rows
                    </span>
                  ) : null}
                </p>
                <p className={cn("mt-1", rs.text.body)}>{warning.message}</p>
                {recovery ? (
                  <p className={cn("mt-1 text-xs font-semibold", rs.text.success)}>
                    {recoveryLabel(warning)}. Audit evidence only; not a counted parser warning.
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function EvidencePanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={cn("rounded-md border p-4", rs.border.line, rs.bg.paper)} aria-label={title}>
      <h2 className={cn("text-sm font-semibold", rs.text.ink)}>{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function WarningBadge({ warnings }: { warnings: WarningEvidence[] }) {
  if (!warnings.length) {
    return (
      <span
        className={cn(
          "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border",
          rs.border.success,
          rs.bg.successSoft,
          rs.text.success,
        )}
        aria-label="No warnings"
        title="No warnings"
      >
        <ShieldCheck className="h-4 w-4" aria-hidden="true" />
      </span>
    );
  }
  const counted = warnings.some(isCountedWarning);
  return (
    <span
      className={cn(
        "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border",
        counted ? cn(rs.border.warning, rs.bg.warningSoft, rs.text.warning) : cn(rs.border.success, rs.bg.successSoft, rs.text.success),
      )}
      aria-label={counted ? "Counted warning" : "Audit info"}
      title={counted ? "Counted warning" : "Audit info"}
    >
      {counted ? (
        <AlertTriangle className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Info className="h-4 w-4" aria-hidden="true" />
      )}
    </span>
  );
}

function BlockCard({
  block,
  warningsById,
}: {
  block: ParserBlockEvidence;
  warningsById: Map<string, WarningEvidence>;
}) {
  const recoveryWarning = block.warning_ids.map((id) => warningsById.get(id)).find(isAcceptedRecoveryWarning);
  const isRecovered = Boolean(recoveryWarning);

  return (
    <article
      className={cn(
        "rounded-md border p-3",
        isRecovered ? cn(rs.border.success, rs.bg.successSoft) : cn(rs.border.line, rs.bg.field),
      )}
    >
      <div className="flex flex-wrap gap-2 text-xs font-semibold">
        <span className={rs.text.muted}>{titleCase(block.block_type)}</span>
        <span className={rs.text.muted}>page {block.page ?? "?"}</span>
        <span className={rs.text.muted}>block {block.block_index ?? "?"}</span>
        {block.modality ? <span className={rs.text.accent}>mode {block.modality}</span> : null}
        {isRecovered ? (
          <>
            <span className={cn("rounded-md border px-2 py-0.5", rs.border.success, rs.bg.paper, rs.text.success)}>
              Recovered text
            </span>
            <span className={rs.text.success}>{recoveryLabel(recoveryWarning)}</span>
          </>
        ) : null}
      </div>
      <p className={cn("mt-2 whitespace-pre-wrap text-sm leading-6", rs.text.body)}>{block.text_preview}</p>
    </article>
  );
}

function DiffPanel({
  decision,
  blocks,
  chunks,
}: {
  decision: NormalizationDecisionEvidence;
  blocks: ParserBlockEvidence[];
  chunks: ChunkEvidence[];
}) {
  const explicitRows = decision.diff_rows ?? [];
  if (!explicitRows.length && !blocks.length && !chunks.length) {
    return <MissingText>No diffable evidence recorded.</MissingText>;
  }

  return (
    <div className="grid gap-2">
      {explicitRows.map((row) => (
        <DiffRow
          key={row.id}
          label={diffKindLabel(row.kind)}
          text={row.text}
          capped={row.capped}
          hiddenCount={row.hidden_count}
        />
      ))}
      {blocks.map((block) => (
        <DiffRow key={block.id} label="Unchanged" text={block.text_preview} />
      ))}
      {chunks.map((chunk) => (
        <DiffRow key={chunk.id} label="Added" text={chunk.text_preview} />
      ))}
    </div>
  );
}

function DiffRow({
  label,
  text,
  capped = false,
  hiddenCount = 0,
}: {
  label: "Added" | "Unchanged" | "Removed" | "Blocked";
  text: string;
  capped?: boolean;
  hiddenCount?: number;
}) {
  return (
    <div className={cn("grid gap-2 rounded-md border p-3 sm:grid-cols-[110px_minmax(0,1fr)]", rs.border.line, rs.bg.field)}>
      <span className={cn("text-xs font-semibold uppercase", rs.text.accentDeep)}>{label}</span>
      <span className={cn("whitespace-pre-wrap break-words text-sm leading-6", rs.text.body)}>
        {text}
        {capped ? (
          <span className={cn("mt-1 block text-xs font-semibold", rs.text.warning)}>
            Capped preview{hiddenCount ? ` - ${hiddenCount} hidden characters` : ""}
          </span>
        ) : null}
      </span>
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: ChunkEvidence }) {
  return (
    <article className={cn("rounded-md border p-3", rs.border.line, rs.bg.field)}>
      <div className="flex flex-wrap gap-2 text-xs font-semibold">
        <span className={rs.text.ink}>{chunk.id}</span>
        <span className={rs.text.muted}>{formatPageRange(chunk.page_start, chunk.page_end)}</span>
        <span className={rs.text.muted}>{chunk.quality_status ?? "quality not recorded"}</span>
        {chunk.modality ? <span className={rs.text.accent}>mode {chunk.modality}</span> : null}
      </div>
      <p className={cn("mt-2 whitespace-pre-wrap text-sm leading-6", rs.text.body)}>{chunk.text_preview}</p>
    </article>
  );
}

function EvidenceSubPanels({
  warnings,
  chunks,
}: {
  warnings: WarningEvidence[];
  chunks: ChunkEvidence[];
}) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <EvidencePanel title="Selected warnings">
        {warnings.length ? (
          <div className="grid gap-2">
            {warnings.map((warning) => (
              <div key={warning.id} className={cn("rounded-md border p-3 text-sm", rs.border.line, rs.bg.field)}>
                <p className={cn("font-semibold", isCountedWarning(warning) ? rs.text.warning : rs.text.success)}>
                  {warning.code}
                </p>
                <p className={cn("mt-1", rs.text.body)}>{warning.message}</p>
                <p className={cn("mt-1 text-xs font-semibold", rs.text.muted)}>
                  Severity {warning.severity}
                  {warning.quality_gate_action ? ` - ${warning.quality_gate_action}` : ""}
                  {!isCountedWarning(warning) ? " - audit evidence" : ""}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <MissingText>No warnings recorded for this evidence.</MissingText>
        )}
      </EvidencePanel>
      <EvidencePanel title="Navigation">
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" disabled={!chunks.length}>
            Open in chunks
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={!chunks.length}
            onClick={() => chunks[0] && void navigator.clipboard?.writeText(chunks[0].id)}
          >
            Copy chunk id
          </Button>
        </div>
      </EvidencePanel>
    </div>
  );
}

function AllWarningsPanel({ warnings }: { warnings: WarningEvidence[] }) {
  const [warningSearch, setWarningSearch] = useState("");
  const [warningCodeFilter, setWarningCodeFilter] = useState("all");
  const [warningScopeFilter, setWarningScopeFilter] = useState("all");
  const [warningPage, setWarningPage] = useState(1);
  const [warningPageSize, setWarningPageSize] = useState(25);
  const warningCodeOptions = useMemo(() => countBy(warnings, (warning) => warning.code), [warnings]);
  const countedWarningCount = useMemo(() => warnings.filter(isCountedWarning).length, [warnings]);
  const auditWarningCount = warnings.length - countedWarningCount;
  const filteredWarnings = useMemo(() => {
    const needle = warningSearch.trim().toLowerCase();
    return warnings.filter((warning) => {
      if (warningCodeFilter !== "all" && warning.code !== warningCodeFilter) {
        return false;
      }
      if (warningScopeFilter === "counted" && !isCountedWarning(warning)) {
        return false;
      }
      if (warningScopeFilter === "audit" && isCountedWarning(warning)) {
        return false;
      }
      return !needle || warningSearchText(warning).includes(needle);
    });
  }, [warningCodeFilter, warningScopeFilter, warningSearch, warnings]);
  const pageCount = Math.max(1, Math.ceil(filteredWarnings.length / warningPageSize));
  const boundedPage = Math.min(warningPage, pageCount);
  const visibleWarnings = filteredWarnings.slice(
    (boundedPage - 1) * warningPageSize,
    boundedPage * warningPageSize,
  );
  const start = filteredWarnings.length ? (boundedPage - 1) * warningPageSize + 1 : 0;
  const end = Math.min(boundedPage * warningPageSize, filteredWarnings.length);

  useEffect(() => {
    setWarningPage(1);
  }, [warningCodeFilter, warningPageSize, warningScopeFilter, warningSearch]);

  return (
    <section className={cn("overflow-hidden rounded-md border", rs.border.line, rs.bg.paper)} aria-label="All warning rows">
      <PanelHeader
        icon={<AlertTriangle className={cn("h-4 w-4", rs.text.warning)} aria-hidden="true" />}
        title="All warning rows"
        detail={`Showing ${start}-${end} of ${filteredWarnings.length}`}
      />
      <div className="space-y-3 p-3">
        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_190px_260px_auto]">
          <label className="relative min-w-0">
            <span className="sr-only">Search all warnings</span>
            <Search className={cn("pointer-events-none absolute left-3 top-2.5 h-4 w-4", rs.text.muted)} aria-hidden="true" />
            <input
              className={filterControlClass("pl-9")}
              value={warningSearch}
              onChange={(event) => setWarningSearch(event.target.value)}
              placeholder="Search all warnings, chunk ids, pages, actions..."
            />
          </label>
          <SelectControl label="Warning row scope" value={warningScopeFilter} onChange={setWarningScopeFilter}>
            <option value="all">Rows: All ({warnings.length})</option>
            <option value="counted">Counted ({countedWarningCount})</option>
            <option value="audit">Audit ({auditWarningCount})</option>
          </SelectControl>
          <SelectControl label="All warning code" value={warningCodeFilter} onChange={setWarningCodeFilter}>
            <option value="all">Warning: All</option>
            {Object.entries(warningCodeOptions).map(([code, count]) => (
              <option key={code} value={code}>
                {code} ({count})
              </option>
            ))}
          </SelectControl>
          <select
            className={filterControlClass("h-10 w-full lg:w-24")}
            value={warningPageSize}
            onChange={(event) => setWarningPageSize(Number(event.target.value))}
            aria-label="Warning rows per page"
          >
            {[10, 25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </div>

        {visibleWarnings.length ? (
          <div className="grid gap-2 lg:grid-cols-2">
            {visibleWarnings.map((warning) => (
              <WarningRow key={warning.id} warning={warning} />
            ))}
          </div>
        ) : (
          <MissingText>No warnings match the current filters.</MissingText>
        )}

        <div className={cn("flex flex-wrap items-center justify-between gap-2 border-t pt-3", rs.border.line)}>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setWarningPage(Math.max(1, boundedPage - 1))}
            disabled={boundedPage <= 1}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            Previous
          </Button>
          <span className={cn("text-xs font-semibold", rs.text.muted)}>
            Page {boundedPage} of {pageCount}
          </span>
          <Button
            type="button"
            variant="secondary"
            onClick={() => setWarningPage(Math.min(pageCount, boundedPage + 1))}
            disabled={boundedPage >= pageCount}
          >
            Next
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </section>
  );
}

function WarningRow({ warning }: { warning: WarningEvidence }) {
  const counted = isCountedWarning(warning);
  return (
    <article
      className={cn(
        "rounded-md border p-3 text-sm",
        counted ? cn(rs.border.warning, rs.bg.warningSoft) : cn(rs.border.success, rs.bg.successSoft),
      )}
    >
      <div className="flex items-start gap-2">
        {counted ? (
          <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", rs.text.warning)} aria-hidden="true" />
        ) : (
          <Info className={cn("mt-0.5 h-4 w-4 shrink-0", rs.text.success)} aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <p className={cn("break-words font-semibold", counted ? rs.text.warning : rs.text.success)}>
            {warning.code}
          </p>
          <p className={cn("mt-1 break-words", rs.text.body)}>{warning.message}</p>
          <p className={cn("mt-2 break-words text-xs font-semibold", rs.text.muted)}>
            Severity {warning.severity}
            {warning.page != null ? ` - page ${warning.page}` : ""}
            {warning.block_type ? ` - ${warning.block_type}` : ""}
            {warning.quality_gate_action ? ` - ${warning.quality_gate_action}` : ""}
            {!counted ? " - audit evidence" : ""}
          </p>
          {warning.affected_chunk_ids.length ? (
            <p className={cn(rs.font.mono, "mt-2 break-words text-xs", rs.text.muted)}>
              chunks {warning.affected_chunk_ids.join(", ")}
            </p>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function ProofMetadataPanel({ evidence }: { evidence: DocumentParseEvidence }) {
  const [redactionSearch, setRedactionSearch] = useState("");
  const [redactionPage, setRedactionPage] = useState(1);
  const filteredRedactions = evidence.proof.redaction_summary.filter((item) =>
    item.toLowerCase().includes(redactionSearch.trim().toLowerCase()),
  );
  const redactionPageSize = 6;
  const redactionPageCount = Math.max(1, Math.ceil(filteredRedactions.length / redactionPageSize));
  const boundedRedactionPage = Math.min(redactionPage, redactionPageCount);
  const visibleRedactions = filteredRedactions.slice(
    (boundedRedactionPage - 1) * redactionPageSize,
    boundedRedactionPage * redactionPageSize,
  );

  useEffect(() => {
    setRedactionPage(1);
  }, [redactionSearch]);

  return (
    <section aria-label="Proof metadata" className="grid gap-4 lg:grid-cols-[1.1fr_1fr_1fr]">
      <div className={cn("overflow-hidden rounded-md border", rs.border.line, rs.bg.paper)}>
        <PanelHeader
          icon={<GitCommit className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />}
          title="Artifacts"
          detail={`${evidence.source_artifacts.length} sources`}
        />
        <div className="grid gap-2 p-3">
          {evidence.source_artifacts.length ? (
            evidence.source_artifacts.map((artifact) => <ArtifactRow key={artifact.id} artifact={artifact} />)
          ) : (
            <MissingText>No artifacts recorded.</MissingText>
          )}
        </div>
      </div>

      <div className={cn("overflow-hidden rounded-md border", rs.border.line, rs.bg.paper)}>
        <PanelHeader
          icon={<Box className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />}
          title="Limitations"
          detail={`${evidence.proof.limitations.length} items`}
        />
        <div className="space-y-3 p-3">
          <MetadataItem label="Mode" value={titleCase(evidence.proof.mode.replaceAll("-", " "))} />
          <MetadataItem label="Commit" value={evidence.proof.source_commit ?? "Not recorded"} mono />
          {evidence.proof.source_commit_href ? (
            <MetadataLink href={evidence.proof.source_commit_href}>View source commit</MetadataLink>
          ) : null}
          <MetadataItem label="Packet" value={evidence.proof.proof_packet_id ?? "Local evidence"} mono />
          {evidence.proof.proof_packet_href ? (
            <MetadataLink href={evidence.proof.proof_packet_href}>Open proof packet</MetadataLink>
          ) : null}
          <MetadataItem label="Replay" value={evidence.proof.replay_command ?? "Replay command not recorded"} mono />
          {evidence.proof.replay_href ? <MetadataLink href={evidence.proof.replay_href}>Replay proof</MetadataLink> : null}
          <ListSection title="Limitations" items={evidence.proof.limitations} />
        </div>
      </div>

      <div className={cn("overflow-hidden rounded-md border", rs.border.line, rs.bg.paper)}>
        <PanelHeader
          icon={<ShieldCheck className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />}
          title="Redactions"
          detail={`${filteredRedactions.length} rows`}
        />
        <div className="space-y-2 p-3">
          <label>
            <span className="sr-only">Search redactions</span>
            <input
              className={filterControlClass()}
              placeholder="Search redactions..."
              value={redactionSearch}
              onChange={(event) => setRedactionSearch(event.target.value)}
            />
          </label>
          {visibleRedactions.length ? (
            <div className="grid gap-2">
              {visibleRedactions.map((item) => (
                <div key={item} className={cn(rs.font.mono, "rounded-md border p-2 text-xs", rs.border.line, rs.bg.field, rs.text.body)}>
                  {item}
                </div>
              ))}
            </div>
          ) : (
            <MissingText>No redactions match the current search.</MissingText>
          )}
          <div className="flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRedactionPage(Math.max(1, boundedRedactionPage - 1))}
              disabled={boundedRedactionPage <= 1}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Previous
            </Button>
            <span className={cn("text-xs font-semibold", rs.text.muted)}>
              Page {boundedRedactionPage} of {redactionPageCount}
            </span>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setRedactionPage(Math.min(redactionPageCount, boundedRedactionPage + 1))}
              disabled={boundedRedactionPage >= redactionPageCount}
            >
              Next
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function PanelHeader({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-2 border-b px-3 py-3", rs.border.line)}>
      <div className="flex items-center gap-2">
        {icon}
        <h2 className={cn("text-sm font-semibold", rs.text.ink)}>{title}</h2>
      </div>
      <span className={cn("text-xs font-semibold", rs.text.muted)}>{detail}</span>
    </div>
  );
}

function ArtifactRow({ artifact }: { artifact: SourceArtifactEvidence }) {
  return (
    <div className={cn("rounded-md border p-3 text-xs", rs.border.line, rs.bg.field)}>
      <div className="flex items-start gap-2">
        <FileCode2 className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", rs.text.accent)} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className={cn(rs.font.mono, "break-words", rs.text.body)}>{artifact.path ?? artifact.id}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Pill>{artifact.kind}</Pill>
            <Pill>{artifact.preview_available ? "Preview available" : "Preview unavailable"}</Pill>
          </div>
          {artifact.href ? (
            <div className="mt-2">
              <MetadataLink href={artifact.href}>Open raw artifact</MetadataLink>
            </div>
          ) : null}
          {artifact.preview_capped ? (
            <p className={cn("mt-2", rs.text.warning)}>{artifact.hidden_count} hidden characters</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function MetadataItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className={cn("rounded-md p-2", rs.bg.field)}>
      <p className={cn("text-xs font-semibold uppercase", rs.text.muted)}>{label}</p>
      <p className={cn("mt-1 break-words text-sm", rs.text.body, mono && rs.font.mono)}>{value}</p>
    </div>
  );
}

function ListSection({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <div>
      <p className={cn("text-xs font-semibold uppercase", rs.text.muted)}>{title}</p>
      {items.length ? (
        <ul className={cn("mt-2 list-disc space-y-1 pl-5 text-sm", rs.text.body)}>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <MissingText>None recorded.</MissingText>
      )}
    </div>
  );
}

function MetadataLink({ href, children }: { href: string; children: ReactNode }) {
  const safeHref = safeLinkHref(href);
  if (!safeHref) {
    return <MissingText>Unsafe link hidden.</MissingText>;
  }

  return (
    <a
      href={safeHref}
      className={cn(
        "inline-flex items-center text-sm underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
        rs.text.accent,
        rs.focus.ring,
        rs.focus.offset,
      )}
    >
      {children}
    </a>
  );
}

function Pill({ children, tone = "default" }: { children: ReactNode; tone?: "default" | "warning" }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-1",
        tone === "warning" ? cn(rs.border.warning, rs.bg.warningSoft, rs.text.warning) : cn(rs.border.line, rs.bg.field, rs.text.body),
      )}
    >
      {children}
    </span>
  );
}

function MissingText({ children }: { children: ReactNode }) {
  return <p className={cn("text-sm", rs.text.muted)}>{children}</p>;
}

function formatPageRange(pageStart?: number | null, pageEnd?: number | null) {
  if (pageStart == null && pageEnd == null) {
    return "page ?";
  }
  if (pageStart != null && pageEnd != null && pageEnd !== pageStart) {
    return `page ${pageStart} -> ${pageEnd}`;
  }
  return `page ${pageStart ?? pageEnd ?? "?"}`;
}

function orderByIds<T extends { id: string }>(items: T[], ids: string[]) {
  const itemsById = new Map(items.map((item) => [item.id, item]));
  return ids.flatMap((id) => {
    const item = itemsById.get(id);
    return item ? [item] : [];
  });
}

function isAcceptedRecoveryWarning(warning?: WarningEvidence | null) {
  return Boolean(
    warning &&
      (warning.code === "recovered_text_from_disallowed_block" ||
        warning.quality_gate_action === "accepted_recovery" ||
        warning.suppressed_from_counts),
  );
}

function recoveryLabel(warning?: WarningEvidence | null) {
  const blockType = warning?.block_type ? ` from ${titleCase(warning.block_type)}` : "";
  return `Accepted recovery${blockType}`;
}

function diffKindLabel(kind: DiffRowEvidence["kind"]) {
  const labels: Record<DiffRowEvidence["kind"], "Added" | "Unchanged" | "Removed" | "Blocked"> = {
    added: "Added",
    unchanged: "Unchanged",
    removed: "Removed",
    blocked: "Blocked",
  };
  return labels[kind];
}

function cssEscape(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function safeLinkHref(href: string) {
  const trimmed = href.trim();
  if (!trimmed) {
    return null;
  }
  if (trimmed.startsWith("//")) {
    return null;
  }
  if (trimmed.startsWith("/") || trimmed.startsWith("./") || trimmed.startsWith("../") || trimmed.startsWith("#")) {
    return trimmed;
  }
  try {
    const url = new URL(trimmed);
    return url.protocol === "https:" || url.protocol === "http:" ? trimmed : null;
  } catch {
    return null;
  }
}

interface EvidenceMetrics {
  decisions: number;
  warnings: number;
  blocks: number;
  chunks: number;
  artifacts: number;
  qualityWarnings: number;
  pageStitches: number;
  materializations: number;
  auditWarnings: number;
  countedWarnings: number;
  previewAuditDecisionRows: number;
  previewCountedDecisionRows: number;
}

function evidenceMetrics(evidence: DocumentParseEvidence): EvidenceMetrics {
  const decisionsById = new Map(evidence.normalization_decisions.map((decision) => [decision.id, decision]));
  const previewDecisionWarnings = evidence.warnings.filter((warning) => {
    if (!warning.decision_id) {
      return false;
    }
    return decisionsById.has(warning.decision_id);
  });
  const previewWarningRowsByDecision = new Map<string, WarningEvidence[]>();
  for (const warning of previewDecisionWarnings) {
    if (!warning.decision_id) {
      continue;
    }
    previewWarningRowsByDecision.set(warning.decision_id, [
      ...(previewWarningRowsByDecision.get(warning.decision_id) ?? []),
      warning,
    ]);
  }
  const previewDecisionWarningGroups = Array.from(previewWarningRowsByDecision.values());
  return {
    decisions: evidence.normalization_decisions.length,
    warnings: evidence.warnings.length,
    blocks: evidence.parser_blocks.length,
    chunks: evidence.totals?.chunks ?? evidence.chunks.length,
    artifacts: evidence.source_artifacts.length,
    qualityWarnings: evidence.normalization_decisions.filter(
      (decision) => decision.decision_type === "quality_warning",
    ).length,
    pageStitches: evidence.normalization_decisions.filter((decision) => decision.decision_type === "page_stitch")
      .length,
    materializations: evidence.normalization_decisions.filter(
      (decision) => decision.decision_type === "chunk_materialization",
    ).length,
    auditWarnings: evidence.warnings.filter((warning) => !isCountedWarning(warning)).length,
    countedWarnings: evidence.warnings.filter(isCountedWarning).length,
    previewAuditDecisionRows: previewDecisionWarningGroups.filter((warnings) =>
      warnings.some((warning) => !isCountedWarning(warning)),
    ).length,
    previewCountedDecisionRows: previewDecisionWarningGroups.filter((warnings) =>
      warnings.some(isCountedWarning),
    ).length,
  };
}

function pagesForDecision(
  warnings: WarningEvidence[],
  blocks: ParserBlockEvidence[],
  chunks: ChunkEvidence[],
) {
  return Array.from(
    new Set(
      [
        ...warnings.map((warning) => warning.page),
        ...blocks.map((block) => block.page),
        ...chunks.map((chunk) => chunk.page_start),
        ...chunks.map((chunk) => chunk.page_end),
      ].filter((value): value is number => typeof value === "number"),
    ),
  ).sort((left, right) => left - right);
}

function decisionSearchText(
  decision: NormalizationDecisionEvidence,
  warnings: WarningEvidence[],
  blocks: ParserBlockEvidence[],
  chunks: ChunkEvidence[],
) {
  return [
    decision.id,
    decision.title,
    decision.summary,
    decision.decision_type,
    decision.status,
    ...warnings.flatMap((warning) => [
      warning.id,
      warning.code,
      warning.message,
      warning.severity,
      warning.block_type ?? "",
      warning.page == null ? "" : String(warning.page),
    ]),
    ...blocks.flatMap((block) => [
      block.id,
      block.block_type,
      block.text_preview,
      block.page == null ? "" : String(block.page),
    ]),
    ...chunks.flatMap((chunk) => [
      chunk.id,
      chunk.text_preview,
      chunk.quality_status ?? "",
      chunk.page_start == null ? "" : String(chunk.page_start),
      chunk.page_end == null ? "" : String(chunk.page_end),
    ]),
  ]
    .join(" ")
    .toLowerCase();
}

function warningSearchText(warning: WarningEvidence) {
  return [
    warning.id,
    warning.code,
    warning.message,
    warning.severity,
    warning.block_id ?? "",
    warning.block_type ?? "",
    warning.quality_gate_action ?? "",
    warning.decision_id ?? "",
    warning.page == null ? "" : String(warning.page),
    ...warning.affected_chunk_ids,
  ]
    .join(" ")
    .toLowerCase();
}

function groupedDecisionWarnings(warnings: WarningEvidence[]) {
  const groups = new Map<string, WarningEvidence[]>();
  for (const warning of warnings) {
    const key = [
      warning.code,
      warning.quality_gate_action ?? "",
      warning.block_type ?? "",
      String(isCountedWarning(warning)),
      normalizedSeverity(warning.severity),
    ].join("|");
    groups.set(key, [...(groups.get(key) ?? []), warning]);
  }
  return Array.from(groups.entries()).map(([key, groupWarnings]) => ({
    key,
    warnings: groupWarnings,
  }));
}

function normalizedSeverity(severity: string) {
  const normalized = severity.toLowerCase();
  return normalized === "warn" ? "warning" : normalized;
}

function countBy<T>(items: T[], keyForItem: (item: T) => string) {
  return items.reduce<Record<string, number>>((counts, item) => {
    const key = keyForItem(item);
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
}

function isCountedWarning(warning: WarningEvidence) {
  return !warning.suppressed_from_counts && warning.severity.toLowerCase() !== "info";
}

function filterControlClass(extra = "") {
  return cn(
    "h-10 w-full rounded-md border px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
    rs.border.strong,
    rs.bg.paper,
    rs.text.body,
    rs.focus.ring,
    rs.focus.offset,
    extra,
  );
}

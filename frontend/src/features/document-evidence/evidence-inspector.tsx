import { AlertCircle, Box, FileCode2, GitCommit, RotateCcw, ShieldCheck } from "lucide-react";
import { useState, type KeyboardEvent, type ReactNode } from "react";

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

  const selectedDecision =
    decisions.find((decision) => decision.id === selectedDecisionId) ?? decisions[0] ?? null;
  const selectedBlocks = selectedDecision
    ? orderByIds(evidence.parser_blocks, selectedDecision.input_block_ids)
    : [];
  const selectedChunks = selectedDecision ? orderByIds(evidence.chunks, selectedDecision.output_chunk_ids) : [];
  const selectedWarnings = selectedDecision ? orderByIds(evidence.warnings, selectedDecision.warning_ids) : [];
  return (
    <div className={cn(rs.font.body, "mx-auto grid max-w-7xl gap-4 xl:grid-cols-[280px_minmax(0,1fr)_300px]")}>
      <section className="xl:col-span-3">
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

      <EvidenceRail
        decisions={decisions}
        selectedDecisionId={selectedDecision?.id ?? ""}
        onSelect={setSelectedDecisionId}
      />

      <section
        className="min-w-0"
        aria-label={selectedDecision ? `${selectedDecision.title} evidence detail` : "Evidence detail"}
      >
        {selectedDecision ? (
          <div className="space-y-4">
            <DecisionSummary decision={selectedDecision} warnings={selectedWarnings} />
            <EvidencePanel title="Source blocks">
              {selectedBlocks.length ? (
                <div className="grid gap-2">
                  {selectedBlocks.map((block) => (
                    <BlockCard key={block.id} block={block} />
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
        ) : (
          <EmptyState
            icon={AlertCircle}
            title="Evidence unavailable"
            description="No decisions were recorded."
            className={cn(rs.bg.paper, rs.border.line)}
          />
        )}
      </section>

      <ProofMetadataPanel evidence={evidence} />
    </div>
  );
}

function EvidenceRail({
  decisions,
  selectedDecisionId,
  onSelect,
}: {
  decisions: NormalizationDecisionEvidence[];
  selectedDecisionId: string;
  onSelect: (id: string) => void;
}) {
  const selectByIndex = (index: number, currentTarget: EventTarget & HTMLElement) => {
    const boundedIndex = Math.max(0, Math.min(index, decisions.length - 1));
    const nextDecision = decisions[boundedIndex];
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
    const currentIndex = decisions.findIndex((item) => item.id === decision.id);
    if (currentIndex < 0) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      selectByIndex((currentIndex + 1) % decisions.length, event.currentTarget.parentElement ?? event.currentTarget);
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      selectByIndex(
        (currentIndex - 1 + decisions.length) % decisions.length,
        event.currentTarget.parentElement ?? event.currentTarget,
      );
    }
    if (event.key === "Home") {
      event.preventDefault();
      selectByIndex(0, event.currentTarget.parentElement ?? event.currentTarget);
    }
    if (event.key === "End") {
      event.preventDefault();
      selectByIndex(decisions.length - 1, event.currentTarget.parentElement ?? event.currentTarget);
    }
  };

  return (
    <aside className={cn("rounded-md border p-3", rs.border.line, rs.bg.paper)} aria-label="Evidence decisions">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />
        <h2 className={cn("text-sm font-semibold", rs.text.ink)}>Decisions</h2>
      </div>
      {decisions.length ? (
        <div className="grid gap-2" aria-label="Evidence decisions">
          {decisions.map((decision) => {
            const selected = decision.id === selectedDecisionId;
            return (
              <button
                key={decision.id}
                type="button"
                data-decision-id={decision.id}
                aria-pressed={selected}
                onClick={() => onSelect(decision.id)}
                onKeyDown={(event) => handleKeyDown(event, decision)}
                className={cn(
                  "min-h-11 rounded-md border px-3 py-2 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-offset-2",
                  rs.focus.ring,
                  rs.focus.offset,
                  selected
                    ? cn(rs.border.accent, rs.bg.accentSoft, rs.text.accentDeep)
                    : cn(rs.border.line, rs.bg.paper, rs.text.body, rs.hover.field),
                )}
              >
                <span className="block font-semibold">{decision.title}</span>
                <span className="mt-1 block text-xs opacity-80">
                  {titleCase(decision.decision_type.replaceAll("_", " "))}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <MissingText>No decisions recorded.</MissingText>
      )}
    </aside>
  );
}

function DecisionSummary({
  decision,
  warnings,
}: {
  decision: NormalizationDecisionEvidence;
  warnings: WarningEvidence[];
}) {
  return (
    <section className={cn("rounded-md border p-4", rs.border.line, rs.bg.paper)}>
      <p className={cn("text-xs font-semibold uppercase", rs.text.muted)}>
        {titleCase(decision.status.replaceAll("_", " "))}
      </p>
      <h2 className={cn("mt-1 text-lg font-semibold", rs.text.ink)}>{decision.title}</h2>
      <p className={cn("mt-2 text-sm leading-6", rs.text.body)}>{decision.summary}</p>
      {warnings.length ? (
        <div className="mt-3 grid gap-2">
          {warnings.map((warning) => (
            <div
              key={warning.id}
              className={cn("rounded-md border px-3 py-2 text-sm", rs.border.warning, rs.bg.warningSoft)}
            >
              <p className={cn("font-semibold", rs.text.warning)}>{warning.code}</p>
              <p className={cn("mt-1", rs.text.body)}>{warning.message}</p>
            </div>
          ))}
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

function BlockCard({ block }: { block: ParserBlockEvidence }) {
  return (
    <article className={cn("rounded-md border p-3", rs.border.line, rs.bg.field)}>
      <div className="flex flex-wrap gap-2 text-xs font-semibold">
        <span className={rs.text.muted}>{titleCase(block.block_type)}</span>
        <span className={rs.text.muted}>page {block.page ?? "?"}</span>
        <span className={rs.text.muted}>block {block.block_index ?? "?"}</span>
        {block.modality ? <span className={rs.text.accent}>mode {block.modality}</span> : null}
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
            Capped preview{hiddenCount ? ` · ${hiddenCount} hidden characters` : ""}
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

function ProofMetadataPanel({ evidence }: { evidence: DocumentParseEvidence }) {
  return (
    <section
      className={cn("space-y-3 rounded-md border p-4", rs.border.line, rs.bg.paper)}
      aria-label="Proof metadata"
    >
      <div className="flex items-center gap-2">
        <GitCommit className={cn("h-4 w-4", rs.text.accent)} aria-hidden="true" />
        <h2 className={cn("text-sm font-semibold", rs.text.ink)}>Proof metadata</h2>
      </div>
      <MetadataItem label="Commit" value={evidence.proof.source_commit ?? "Not recorded"} mono />
      {evidence.proof.source_commit_href ? (
        <MetadataLink href={evidence.proof.source_commit_href}>View source commit</MetadataLink>
      ) : null}
      <MetadataItem
        label="Packet"
        value={evidence.proof.proof_packet_id ?? "Local evidence"}
        mono
      />
      {evidence.proof.proof_packet_href ? (
        <MetadataLink href={evidence.proof.proof_packet_href}>Open proof packet</MetadataLink>
      ) : null}
      <MetadataItem
        label="Replay"
        value={evidence.proof.replay_command ?? "Replay command not recorded"}
        mono
      />
      {evidence.proof.replay_href ? <MetadataLink href={evidence.proof.replay_href}>Replay proof</MetadataLink> : null}
      <MetadataItem label="Mode" value={titleCase(evidence.proof.mode.replaceAll("-", " "))} />

      <div>
        <p className={cn("text-xs font-semibold uppercase", rs.text.muted)}>Artifacts</p>
        <div className="mt-2 grid gap-2">
          {evidence.source_artifacts.length ? (
            evidence.source_artifacts.map((artifact) => <ArtifactRow key={artifact.id} artifact={artifact} />)
          ) : (
            <MissingText>No artifacts recorded.</MissingText>
          )}
        </div>
      </div>

      <ListSection
        title="Limitations"
        items={evidence.proof.limitations}
        icon={<Box className="h-4 w-4" aria-hidden="true" />}
      />
      <ListSection
        title="Redactions"
        items={evidence.proof.redaction_summary}
        icon={<ShieldCheck className="h-4 w-4" aria-hidden="true" />}
      />
    </section>
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
  icon,
}: {
  title: string;
  items: string[];
  icon: ReactNode;
}) {
  return (
    <div>
      <p className={cn("flex items-center gap-1 text-xs font-semibold uppercase", rs.text.muted)}>
        {icon}
        {title}
      </p>
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

function Pill({ children }: { children: ReactNode }) {
  return (
    <span className={cn("rounded-full border px-2 py-1", rs.border.line, rs.bg.field, rs.text.body)}>
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

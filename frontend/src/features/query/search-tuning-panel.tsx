import { X } from "lucide-react";

import type { ChunkOut, HybridSearchWeights } from "../../api/generated";
import { FocusTrapDialog } from "../../components/focus-trap-dialog";
import { Button } from "../../components/ui/button";

const controls = [
  { key: "reference_exact", label: "Reference exact" },
  { key: "term_coverage", label: "Term coverage" },
  { key: "metadata_boost", label: "Metadata boost" },
  { key: "semantic_density", label: "Semantic density" },
] as const;

export function SearchTuningPanel({
  open,
  weights,
  previewItems,
  isLoading,
  error,
  onChange,
  onClose,
}: {
  open: boolean;
  weights: HybridSearchWeights;
  previewItems: ChunkOut[];
  isLoading: boolean;
  error?: string;
  onChange: (weights: HybridSearchWeights) => void;
  onClose: () => void;
}) {
  const updateWeight = (key: keyof HybridSearchWeights, value: number) => {
    onChange({ ...weights, [key]: value });
  };

  return (
    <FocusTrapDialog
      open={open}
      title="Search tuning"
      onClose={onClose}
      overlayLabel="Close search tuning"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-xl flex-col overflow-hidden border-l border-[#cfd8dd] bg-white shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-[#e1e7ea] px-4 py-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-[#1f2933]">Search tuning</h3>
          <p className="mt-1 text-xs text-[#62717a]">Simulation preview only</p>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div className="space-y-4">
          {controls.map((control) => {
            const value = Number(weights[control.key] ?? 1);
            return (
              <label key={control.key} className="block rounded-md border border-[#e1e7ea] p-3">
                <span className="flex items-center justify-between gap-3 text-sm font-medium text-[#24313a]">
                  <span>{control.label}</span>
                  <span>{value.toFixed(1)}</span>
                </span>
                <input
                  aria-label={control.label}
                  className="mt-3 w-full accent-[#176b87]"
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={value}
                  onChange={(event) => updateWeight(control.key, Number(event.target.value))}
                />
              </label>
            );
          })}
        </div>

        <section className="mt-5">
          <h4 className="text-sm font-semibold text-[#1f2933]">Preview ranking</h4>
          {isLoading ? (
            <p
              className="mt-3 rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-3 text-sm text-[#62717a]"
              role="status"
              aria-live="polite"
            >
              Updating preview
            </p>
          ) : error ? (
            <p
              className="mt-3 rounded-md border border-[#e19a9a] bg-[#fff0f0] p-3 text-sm text-[#8c2525]"
              role="status"
              aria-live="polite"
            >
              {error}
            </p>
          ) : previewItems.length ? (
            <ol className="mt-3 space-y-2" aria-live="polite">
              {previewItems.map((chunk, index) => (
                <li key={chunk.id} className="rounded-md border border-[#e1e7ea] bg-[#fbfcfd] p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-[#176b87]">#{index + 1}</p>
                      <p className="mt-1 line-clamp-3 text-sm leading-5 text-[#24313a]">
                        {chunk.text}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-md bg-[#eef4f6] px-2 py-1 text-xs font-medium text-[#174657]">
                      {formatScore(chunk.metadata.score)}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p
              className="mt-3 rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-3 text-sm text-[#62717a]"
              role="status"
              aria-live="polite"
            >
              No chunks matched this simulation.
            </p>
          )}
        </section>
      </div>
    </FocusTrapDialog>
  );
}

function formatScore(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? `score ${value.toFixed(2)}`
    : "score n/a";
}

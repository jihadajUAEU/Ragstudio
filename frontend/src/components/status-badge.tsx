import type { StageStatus } from "../api/generated";
import { cn, titleCase } from "../lib/utils";

const statusClasses: Record<StageStatus, string> = {
  not_configured: "border-[#d9b24c] bg-[#fff7df] text-[#705300]",
  ready: "border-[#8fb99f] bg-[#ecf8f0] text-[#24563a]",
  running: "border-[#8cb9c7] bg-[#e8f6fa] text-[#16566b]",
  succeeded: "border-[#8fb99f] bg-[#ecf8f0] text-[#24563a]",
  failed: "border-[#e19a9a] bg-[#fff0f0] text-[#8c2525]",
  unsupported: "border-[#c7cdd1] bg-[#f1f3f4] text-[#5b656b]",
};

export function StatusBadge({
  status,
  className,
}: {
  status: StageStatus;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        statusClasses[status],
        className,
      )}
    >
      <span className="truncate">{titleCase(status)}</span>
    </span>
  );
}

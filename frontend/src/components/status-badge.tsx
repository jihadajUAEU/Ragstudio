import type { StageStatus } from "../api/generated";
import { rs } from "../lib/design-tokens";
import { cn, titleCase } from "../lib/utils";

const statusClasses: Record<StageStatus, string> = {
  not_configured: `${rs.border.warning} ${rs.bg.warningSoft} ${rs.text.warning}`,
  ready: `${rs.border.success} ${rs.bg.successSoft} ${rs.text.success}`,
  running: `${rs.border.accent} ${rs.bg.accentSoft} ${rs.text.accentDeep}`,
  succeeded: `${rs.border.success} ${rs.bg.successSoft} ${rs.text.success}`,
  failed: `${rs.border.danger} ${rs.bg.dangerSoft} ${rs.text.danger}`,
  unsupported: `${rs.border.line} ${rs.bg.field} ${rs.text.body}`,
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

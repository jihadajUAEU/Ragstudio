import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-h-40 flex-col items-center justify-center rounded-md border border-dashed border-[#cdd6da] bg-[#f8fafb] p-6 text-center",
        className,
      )}
    >
      <Icon className="mb-3 h-8 w-8 text-[#6f7f87]" aria-hidden="true" />
      <h3 className="max-w-full text-sm font-semibold text-[#24313a]">{title}</h3>
      <p className="mt-1 max-w-md text-sm leading-6 text-[#62717a]">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

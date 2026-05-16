import { useEffect, useId, useRef, type ReactNode } from "react";

import { cn } from "../lib/utils";

const focusableSelector =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function FocusTrapDialog({
  open,
  title,
  ariaLabel,
  overlayLabel,
  onClose,
  children,
  className,
  overlayClassName,
  labelledBy,
  panelId,
}: {
  open: boolean;
  title?: string;
  ariaLabel?: string;
  overlayLabel?: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  overlayClassName?: string;
  labelledBy?: string;
  panelId?: string;
}) {
  const generatedTitleId = useId();
  const titleId = labelledBy ?? (title ? generatedTitleId : undefined);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousActiveElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusFirstControl = () => {
      const focusable = getFocusableElements(dialogRef.current);
      focusable[0]?.focus();
    };
    focusFirstControl();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const focusable = getFocusableElements(dialogRef.current);
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previousActiveElement?.isConnected) {
        previousActiveElement.focus();
      }
    };
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        className={cn("fixed inset-0 z-20 bg-[#1f2933]/35", overlayClassName)}
        aria-label={overlayLabel ?? "Close dialog"}
        onClick={onClose}
      />
      <div
        id={panelId}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-label={title ? undefined : ariaLabel}
        className={className}
      >
        {title ? (
          <h2 id={titleId} className="sr-only">
            {title}
          </h2>
        ) : null}
        {children}
      </div>
    </>
  );
}

function getFocusableElements(container: HTMLElement | null) {
  return Array.from(container?.querySelectorAll<HTMLElement>(focusableSelector) ?? []).filter(
    (element) => !element.hasAttribute("disabled") && element.tabIndex !== -1,
  );
}

export const rs = {
  bg: {
    page: "bg-[var(--rs-page)]",
    paper: "bg-[var(--rs-paper)]",
    field: "bg-[var(--rs-field)]",
    accent: "bg-[var(--rs-accent)]",
    accentDeep: "bg-[var(--rs-accent-deep)]",
    accentSoft: "bg-[var(--rs-accent-soft)]",
    earthSoft: "bg-[var(--rs-earth-soft)]",
    successSoft: "bg-[var(--rs-success-soft)]",
    warningSoft: "bg-[var(--rs-warning-soft)]",
    dangerSoft: "bg-[var(--rs-danger-soft)]",
  },
  text: {
    ink: "text-[var(--rs-ink)]",
    body: "text-[var(--rs-text)]",
    muted: "text-[var(--rs-muted)]",
    accent: "text-[var(--rs-accent)]",
    accentDeep: "text-[var(--rs-accent-deep)]",
    earth: "text-[var(--rs-earth)]",
    success: "text-[var(--rs-success)]",
    warning: "text-[var(--rs-warning)]",
    danger: "text-[var(--rs-danger)]",
    visited: "text-[var(--rs-visited)]",
    white: "text-[var(--rs-on-accent)]",
  },
  border: {
    line: "border-[var(--rs-line)]",
    strong: "border-[var(--rs-line-strong)]",
    accent: "border-[var(--rs-accent)]",
    success: "border-[var(--rs-success)]",
    warning: "border-[var(--rs-warning)]",
    danger: "border-[var(--rs-danger)]",
  },
  divide: {
    line: "divide-[var(--rs-line)]",
  },
  hover: {
    field: "hover:bg-[var(--rs-field)]",
    accentDeep: "hover:bg-[var(--rs-accent-deep)]",
    accentSoft: "hover:bg-[var(--rs-accent-soft)]",
  },
  focus: {
    ring: "focus-visible:ring-[var(--rs-accent)]",
    offset: "focus-visible:ring-offset-[var(--rs-page)]",
  },
  font: {
    display: "font-[Literata,Georgia,serif]",
    body:
      "font-['Source_Sans_3',ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe_UI',sans-serif]",
    mono:
      "font-['IBM_Plex_Mono','SFMono-Regular',Consolas,'Liberation_Mono',Menlo,monospace]",
  },
} as const;

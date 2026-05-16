---
phase: 06
slug: app-evidence-viewer-and-runtime-trust-banner
status: approved
shadcn_initialized: false
preset: none
created: 2026-05-16
---

# Phase 6 - UI Design Contract

> Visual and interaction contract for the runtime trust chip/panel and shared
> evidence viewer. Generated for Phase 6 and verified against the existing
> Ragstudio Studio UI patterns.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | existing local primitives |
| Icon library | lucide-react |
| Font | existing Studio font stack; use IBM Plex Mono only if already loaded for code/JSON |

### Existing Primitives To Reuse

- `Button` from `frontend/src/components/ui/button.tsx`.
- `StatusBadge` from `frontend/src/components/status-badge.tsx` when generic
  stage status is needed.
- `EmptyState` for diagnostics/evidence unavailable states.
- Existing `AppShell` header/sidebar structure, focus restoration pattern, and
  mobile dialog keyboard handling.
- Existing Diagnostics, Query, Chunk Inspector, and Graph page card/panel
  styling as the source of truth for borders, radius, and compact layout.

Do not introduce shadcn, Radix, Headless UI, or another component library in
this phase.

---

## Spacing Scale

Declared values must remain multiples of 4 unless noted.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, status dot spacing, compact metadata separators |
| sm | 8px | Badge gaps, button icon gap, drawer section label spacing |
| md | 16px | Default card/panel padding, evidence section spacing |
| lg | 24px | Drawer header/footer padding, page panel gaps |
| xl | 32px | Desktop drawer content breathing room when needed |
| 2xl | 48px | Avoid inside Phase 6 modals/drawers except page shell spacing already present |
| 3xl | 64px | Not used in Phase 6 UI surfaces |

Exceptions: drawer overlay may use full viewport dimensions and sticky header
offsets to fit the existing shell.

### Layout Density

- Runtime chip must fit in the existing `AppShell` header without increasing
  header height beyond the current `min-h-16`.
- Runtime trust panel and evidence viewer are operational tools, not marketing
  surfaces; use compact sections with 12-16px internal padding.
- Do not nest cards inside cards. Use section dividers, bordered panels, or
  collapsible rows inside the drawer instead.
- Long paths, ids, hashes, JSON keys, and error strings must wrap or scroll
  inside bounded containers without widening the page.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.5 |
| Label | 12px | 600 | 1.35 |
| Heading | 16px | 600 | 1.35 |
| Panel title | 18px | 600 | 1.35 |
| Mono data | 12px | 400-600 | 1.5 |

### Typography Rules

- No negative letter spacing.
- Do not scale font size directly with viewport width.
- Header chip text must remain a single compact label: `Ready`, `Degraded`,
  `Blocked`, `Indexing`, `Graph pending`, or `Provider issue`.
- Drawer section headings should be short nouns or noun phrases:
  `Summary`, `Chunk text`, `Source location`, `Parser quality`, `Reranker`,
  `Graph context`, `Metadata`, `Raw JSON`.
- Use mono styling only for raw JSON, ids, paths, hashes, and provider/model
  values where scannability benefits.

---

## Color

Use the current Studio shell palette as the base so Phase 6 blends into the
existing app:

| Role | Value | Usage |
|------|-------|-------|
| Page background | `#f5f7f8` | Existing shell background |
| Surface | `#fbfcfd`, `#ffffff` | Header/sidebar/drawer surfaces |
| Border | `#d6dde1` | Shell, panel, drawer, and row borders |
| Text | `#24313a`, `#1f2933` | Body and heading text |
| Muted text | `#62717a`, `#6f7f87` | Metadata and helper text |
| Accent | `#176b87` | Active nav, primary status/action emphasis |
| Accent soft | `#e7f1f4`, `#eef4f6` | Active/hover surfaces |
| Success | `#256a3b` on `#e9f6eb` | `Ready`, successful provider tests |
| Warning | `#8a5a00` on `#fff4d7` | `Degraded`, `Indexing`, `Graph pending` |
| Danger | `#8c2525` on `#fff0f0` | `Blocked`, `Provider issue`, failed tests |
| Neutral | `#3a4a53` on `#f8fafb` | `Not recorded`, unavailable, raw metadata |

Accent reserved for: primary shell navigation, the trust chip focus/hover
treatment, actionable links, and selected/active evidence state. Status colors
must not be used as decoration.

### Runtime Chip Color Contract

| Label | Color Treatment |
|-------|-----------------|
| `Ready` | success text/background/border |
| `Degraded` | warning text/background/border |
| `Blocked` | danger text/background/border |
| `Indexing` | warning text/background/border |
| `Graph pending` | warning text/background/border |
| `Provider issue` | danger text/background/border |

When diagnostics cannot load, show `Blocked` plus detail text
`Diagnostics unavailable`.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Trust chip aria label | `Runtime trust status: {label}. {detail}` |
| Trust panel title | `Runtime trust` |
| Trust panel refresh | `Refresh status` |
| Diagnostics link | `Open Diagnostics` |
| Provider actions | `Test LLM`, `Test embeddings`, `Test reranker`, `Test MinerU` |
| Evidence action | `Inspect evidence` |
| Evidence viewer title | `Evidence details` |
| Missing parser warning | `Parser warnings not recorded` |
| Missing quality state | `Quality policy not recorded` |
| Missing source location | `Source location not recorded` |
| Missing graph healthy | `No graph relationship recorded for this evidence` |
| Missing document link | `Document link not recorded` |
| Reranker fallback note | `Run-level reranker summary; not source-specific` |
| Raw JSON summary | `Raw JSON` |
| Drawer close aria label | `Close evidence details` or `Close runtime trust` |

Copy must stay direct and operational. Avoid marketing words like
`seamless`, `all-in-one`, `next-generation`, and `transform your workflow`.

---

## Runtime Trust Chip And Panel Contract

### Placement

- Place the chip in the `AppShell` header, to the left of or near the mobile
  navigation button where it remains visible on every Studio route.
- The chip must not obscure the page title. On narrow mobile widths, prefer
  a second compact row within the header or truncate detail text, but preserve
  the primary status label and button target.
- Minimum interactive target: 44px high on mobile and 32px high on desktop.

### Status Priority

Primary chip label is deterministic:

1. `Blocked`
2. `Provider issue`
3. `Indexing`
4. `Graph pending`
5. `Degraded`
6. `Ready`

The panel still lists every issue even when the chip shows only one label.

### Panel Shape

- Use a right-side drawer on desktop if implementation can share drawer
  infrastructure with evidence; otherwise use a compact popover-style panel
  that still traps focus while open.
- Use a full-screen sheet on mobile when opened.
- The panel must close on Escape, restore focus to the chip, and prevent body
  scroll while open.
- The panel must include grouped readiness sections:
  `Backend/API`, `Worker/jobs`, `Postgres/PGVector`, `Neo4j/graph projection`,
  `MinerU/parser`, `LLM`, `Embeddings`, `Reranker`.
- Each section has a status badge, one-line detail, and explicit unavailable
  text if the diagnostics payload does not include enough detail.

### Actions

- `Refresh status` refetches diagnostics only.
- `Open Diagnostics` navigates to `/diagnostics`.
- Provider tests are separate actions with independent pending states.
- Provider tests fetch/use the saved default settings profile only and must not
  mutate settings.
- Inline provider results stay visible until the panel closes or that same test
  runs again.

---

## Evidence Viewer Contract

### Shape

- Open as a shared right-side drawer on desktop.
- Open as a full-screen sheet on mobile.
- Trap focus, close on Escape, restore focus to the `Inspect evidence` trigger,
  and prevent background scroll while open.
- Use a shared normalized evidence input for Query sources and Chunk Inspector
  rows.

### Default Open State

- Only `Summary` is expanded by default.
- The following sections are present and expandable when relevant:
  `Chunk text`, `Source location`, `Parser quality`, `Retrieval reasons`,
  `Reranker`, `Graph context`, `Metadata`, `Raw JSON`.
- Missing sections must show explicit `Not recorded` or unavailable messages
  instead of silently disappearing.

### Summary Contents

The summary section should surface the fastest trust/debugging facts:

- Source id or chunk id.
- Document id/name when available.
- Runtime profile id when available.
- Source location summary when available.
- Quality action/status when available.
- Parser warning count or `Parser warnings not recorded`.
- Reranker provider/model/status when available.
- Graph relationship count or graph unavailable reason.

### Query Entry Point

- Add compact readable source rows above or alongside existing raw Sources JSON.
- Each row has `Inspect evidence`.
- Preserve raw Sources JSON as fallback.
- Source rows must not require opening raw JSON to discover the inspect action.

### Chunk Entry Point

- Add `Inspect evidence` to each Chunk Inspector result card.
- Preserve existing chunk text, badges, retrieval explain, source location, and
  metadata display.
- Do not make the card itself the trigger; use an explicit button for keyboard
  and screen-reader clarity.

### Graph And Reranker Missing States

- If selected evidence contains relationship refs, list them in `Graph context`.
- If graph refs are missing and diagnostics says graph is disabled, pending, or
  failed, show the diagnostics reason.
- If diagnostics is healthy but no graph refs are present, show
  `No graph relationship recorded for this evidence`.
- If source-specific reranker matching is not available, show the run-level
  reranker summary and the note `Run-level reranker summary; not source-specific`.

### Cross-Surface Links

- Show available links to existing Studio routes:
  `Open Documents`, `Open Chunks`, `Open Query`, `Open Graph`,
  `Open Diagnostics`.
- If context for a link is missing, keep the row visible but disabled or labelled
  with unavailable copy, for example `Document link not recorded`.
- Do not create new routes in Phase 6.

---

## Responsive Contract

| Viewport | Required Behavior |
|----------|-------------------|
| 320px mobile | Trust chip and title do not overlap; drawer becomes full-screen sheet; buttons wrap without clipped text. |
| 768px tablet | Drawer/sheet content remains readable; section controls are at least 44px high. |
| 1024px+ desktop | Drawer opens from the right and preserves page context behind the overlay. |

Text inside chips, buttons, and badges must wrap or truncate intentionally.
Long JSON and metadata use bounded scrolling containers.

---

## Accessibility Contract

- Trust chip is a button with accessible status text.
- Trust panel and evidence viewer use `role="dialog"`, `aria-modal="true"`, and
  an accessible label/title.
- Escape closes each modal surface.
- Focus is trapped while open and restored to the trigger on close.
- Provider test results are announced through a polite live region or equivalent
  status text.
- Expandable evidence sections use native `details/summary` or equivalent
  accessible controls with keyboard support.
- Disabled/unavailable links are not focusable as active links; they must expose
  explanatory text.
- All body text and status text must meet 4.5:1 contrast.

---

## Testing Contract

Frontend tests must cover:

- Runtime chip labels for ready, degraded, failed, graph pending, stale job, and
  provider failure diagnostics.
- Diagnostics polling runs on initial render and after 30 seconds.
- Polling calls diagnostics only and does not call provider test APIs.
- Trust panel opens/closes with focus restoration and Escape close.
- Refresh, Open Diagnostics, Test LLM, Test embeddings, Test reranker, and
  Test MinerU call the expected client/navigate paths.
- Query source row opens evidence viewer and identifies the selected source id.
- Chunk Inspector row opens evidence viewer and identifies the selected chunk id.
- Evidence viewer renders explicit `Not recorded`, graph unavailable, and
  `not source-specific` states.
- Mobile and desktop layout checks verify no clipped controls or incoherent
  overlap.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not required |
| third-party | none | no third-party registry blocks allowed |

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-05-16

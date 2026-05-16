# Phase 6: App Evidence Viewer and Runtime Trust Banner - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 6 adds local Studio app UI primitives that help Ragstudio operators trust
the running runtime and inspect evidence without leaving the shell. It owns the
app-shell runtime trust chip, the trust detail panel, provider retest actions,
and a shared in-app evidence viewer opened from Query sources and Chunk
Inspector rows.

This phase does not add exportable investigation reports, public proof-site
changes, hosted demos, upload sandboxes, new provider configuration fields,
retrieval or graph algorithm changes, full PDF visual preview, authentication,
multi-user permissions, or audit-log storage.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**8 requirements are locked.** See `06-SPEC.md` for full requirements,
boundaries, and acceptance criteria.

Downstream agents MUST read `06-SPEC.md` before planning or implementing.
Requirements are not duplicated here.

**In scope (from SPEC.md):**
- App shell runtime trust chip derived from diagnostics.
- Auto-polling diagnostics for shell status.
- Runtime trust detail panel with grouped health sections.
- Manual actions for refresh, Diagnostics navigation, and LLM/embedding/reranker/MinerU provider tests.
- Evidence viewer opened from Query sources and Chunk Inspector rows.
- Human-readable evidence sections for chunk text, source location, metadata, parser warnings, quality status, reranker context, graph neighbors, and raw JSON fallback.
- Links from the viewer to existing Documents, Chunks, Query, Graph, and Diagnostics surfaces.
- Frontend tests for status states, panel actions, evidence entry points, and accessibility-critical interactions.

**Out of scope (from SPEC.md):**
- Exportable investigation reports - separate phase after viewer and status primitives exist.
- Public proof-site changes - this phase targets the local Ragstudio Studio app, not `ragstudio-site`.
- New live hosted demo, upload sandbox, or public API path - outside the local app UI scope.
- New provider configuration fields or saved settings mutation - this phase can test current settings but must not redesign Settings.
- New graph materialization or retrieval algorithms - the viewer displays available graph/retrieval context, it does not change retrieval behavior.
- Full document/PDF page preview and visual page highlighting - later enhancement after evidence selection is stable.
- Authentication, multi-user permissions, or audit-log storage - not required for the local operator workflow.

</spec_lock>

<decisions>
## Implementation Decisions

### Trust Status Priority
- **D-01:** The app-shell trust chip uses a deterministic priority ladder for
  its primary label: `Blocked` > `Provider issue` > `Indexing` >
  `Graph pending` > `Degraded` > `Ready`.
- **D-02:** The chip remains compact but color-coded: red for `Blocked` and
  `Provider issue`, amber for `Indexing`, `Graph pending`, and `Degraded`, and
  green for `Ready`.
- **D-03:** If diagnostics cannot load, the chip shows `Blocked` with
  `Diagnostics unavailable`. The detail panel shows the API error and provides
  refresh and Diagnostics navigation actions.
- **D-04:** The shell polls diagnostics every 30 seconds. Polling must refresh
  diagnostics only and must not trigger provider tests, settings mutations,
  indexing, graph materialization, or other side effects.

### Trust Panel Actions
- **D-05:** The trust detail panel shows separate provider test actions:
  `Test LLM`, `Test embeddings`, `Test reranker`, and `Test MinerU`.
- **D-06:** Each provider test shows its own latest inline success or failure
  message inside the panel.
- **D-07:** Provider tests may run independently in parallel. Each button
  disables only itself while its request is pending.
- **D-08:** Provider tests use the saved default settings profile only. The
  panel should fetch the current default profile and submit that payload to the
  existing settings test API methods.
- **D-09:** Inline provider test results stay visible until the panel closes or
  that specific provider test runs again.

### Evidence Viewer Shape
- **D-10:** Evidence opens in a shared viewer as a right-side drawer on desktop
  and a full-screen sheet on mobile.
- **D-11:** The viewer opens with a human-readable summary first. Raw JSON is a
  lower fallback, not the primary view.
- **D-12:** Query results add compact, readable source rows with an
  `Inspect evidence` action above or alongside the existing raw Sources JSON.
  The raw Sources JSON remains available as fallback.
- **D-13:** Only the summary is expanded by default. Details such as exact chunk
  text, source location, parser and quality fields, reranker context, graph
  context, metadata, and raw JSON are expandable.
- **D-14:** Query sources and Chunk Inspector rows use one shared evidence
  viewer with normalized evidence input.

### Missing Context And Cross-Surface Links
- **D-15:** Missing graph context is explained using diagnostics when available.
  If diagnostics says graph is disabled, pending, or failed, show that reason.
  If diagnostics is healthy but the selected payload has no graph refs, show
  `No graph relationship recorded for this evidence`.
- **D-16:** When a selected source cannot be matched to a source-specific
  reranker trace, the viewer shows the run-level reranker summary with a clear
  `not source-specific` note.
- **D-17:** Missing parser warning, quality status, source location, and related
  evidence fields show explicit `Not recorded` states rather than disappearing.
- **D-18:** Evidence viewer links show available route actions plus disabled or
  unavailable labels for missing context, such as `Document link not recorded`.

### the agent's Discretion
- The agent may choose exact component boundaries, helper names, normalized
  evidence type names, test filenames, and whether the shared drawer lives under
  `frontend/src/components/` or a feature-local module, as long as the decisions
  above and the SPEC acceptance criteria are preserved.
- The agent may choose the exact status derivation helper shape and section
  grouping implementation after reading the diagnostics payload and existing
  frontend patterns.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Scope And Locked Requirements
- `.planning/phases/06-app-evidence-viewer-and-runtime-trust-banner/06-SPEC.md`
  - Locked requirements, boundaries, constraints, and acceptance criteria.
- `.planning/ROADMAP.md` - Phase 6 goal, dependency, success criteria, and
  APP-UI scope.
- `.planning/REQUIREMENTS.md` - Requirement IDs `APP-UI-01` and `APP-UI-02`.
- `.planning/STATE.md` - Current planning state and Phase 6 addition note.
- `DESIGN.md` - Compact evidence-console direction, proof card guidance,
  table/JSON wrapping, and accessibility expectations.

### App Shell And Diagnostics
- `frontend/src/components/app-shell.tsx` - Global shell/header/sidebar where
  the runtime trust chip and panel entry point connect.
- `frontend/src/features/diagnostics/diagnostics-page.tsx` - Existing
  diagnostics rendering, refresh behavior, warnings, dependency rows, runtime
  checks, and raw diagnostics fallback.
- `backend/src/ragstudio/schemas/diagnostics.py` - Diagnostics API contract
  exposed to the frontend.
- `backend/src/ragstudio/services/diagnostics_service.py` - Source of
  `overall_status`, warnings, graph projection status, worker job counts, and
  dependency status fields.

### Provider Test Actions
- `frontend/src/api/client.ts` - Existing `defaultSettings`,
  `testEmbeddingSettings`, `testLlmSettings`, `testRerankerSettings`, and
  `testMinerUSettings` API client methods.
- `frontend/src/features/settings/settings-page.tsx` - Current provider test
  mutation patterns and message formatting.

### Evidence Entry Points And Payloads
- `frontend/src/features/query/query-page.tsx` - Query result rendering,
  Sources JSON, chunk traces, reranker traces, token metadata, and run-level
  reranker summary.
- `frontend/src/features/chunks/chunk-inspector.tsx` - Chunk result cards,
  source location, metadata, retrieval explain, and relationship refs.
- `frontend/src/features/graph/graph-page.tsx` - Existing graph unavailable
  diagnostics wording and graph capability checks.
- `frontend/src/api/generated.ts` - Current TypeScript contracts for `RunOut`,
  `ChunkOut`, and `DiagnosticsOut`.
- `backend/src/ragstudio/schemas/runs.py` - Backend `RunOut` source, trace,
  timing, reranker, and token metadata fields.
- `backend/src/ragstudio/schemas/chunks.py` - Backend `ChunkOut` text, source
  location, metadata, retrieval explain, and relationship ref fields.

### Codebase Maps
- `.planning/codebase/STACK.md` - React/Vite/TanStack Query/Tailwind/lucide
  stack and test tooling.
- `.planning/codebase/STRUCTURE.md` - Frontend feature layout and core file
  locations.
- `.planning/codebase/CONVENTIONS.md` - Frontend naming, imports, state,
  styling, and testing conventions.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `frontend/src/components/app-shell.tsx` already owns the sticky header and
  has existing focus-trap/restore behavior for mobile navigation that can guide
  the trust panel and evidence drawer behavior.
- `frontend/src/features/diagnostics/diagnostics-page.tsx` already renders
  warnings, dependency rows, runtime checks, refresh actions, and raw
  diagnostics.
- `frontend/src/features/settings/settings-page.tsx` already formats
  provider-test success and failure messages for LLM, embeddings, reranker, and
  MinerU.
- `frontend/src/features/query/query-page.tsx` already has run sources, chunk
  traces, reranker traces, query config, token metadata, and raw JSON panels.
- `frontend/src/features/chunks/chunk-inspector.tsx` already displays chunk
  text, source location, metadata, retrieval explain, and relationship refs.
- `frontend/src/features/graph/graph-page.tsx` already derives graph
  unavailable detail from diagnostics warnings/checks.

### Established Patterns
- Frontend server state uses TanStack Query and API calls are centralized in
  `frontend/src/api/client.ts`.
- UI surfaces are compact operational panels with `Button`, `EmptyState`,
  `StatusBadge`, `DataTable`, lucide icons, and Tailwind utilities.
- Raw JSON remains available for debugging, but Phase 6 should add
  human-readable summaries before raw payloads.
- Missing or partial payloads should be explicit and non-crashing; older run and
  chunk payloads may lack source-specific parser, quality, reranker, or graph
  details.

### Integration Points
- The trust chip connects to `AppShell`, calls `apiClient.diagnostics`, and
  should share or mirror Diagnostics page status derivation without duplicating
  backend policy.
- The trust panel calls `apiClient.defaultSettings` and the existing provider
  test methods. It does not mutate settings.
- Query results need readable source rows and `Inspect evidence` controls while
  preserving existing raw JSON panels.
- Chunk Inspector cards need `Inspect evidence` controls that normalize
  `ChunkOut` into the shared evidence viewer input.
- The evidence viewer may use diagnostics data to explain graph unavailable
  states, but should not fetch full graph data or trigger graph materialization.

</code_context>

<specifics>
## Specific Ideas

- Keep the chip small enough to live on every Studio route without competing
  with page titles.
- Treat diagnostics failure itself as a trust failure: `Blocked` plus
  `Diagnostics unavailable`.
- Make provider retests feel like quick debugging tools: independent buttons,
  separate messages, saved default settings only.
- Keep the evidence drawer tidy by opening only the summary section by default,
  while making detailed evidence available through clear expandable sections.
- Phrase missing evidence honestly with `Not recorded`, `not source-specific`,
  and route-specific unavailable labels.

</specifics>

<deferred>
## Deferred Ideas

- Exportable investigation reports remain deferred to a later phase after the
  trust panel and shared evidence viewer primitives exist.
- Full document/PDF visual page preview and visual page highlighting remain
  deferred.
- Fetching full graph data on evidence drawer open is deferred; Phase 6 displays
  payload relationship refs and diagnostics-derived graph availability only.

</deferred>

---

*Phase: 6-App Evidence Viewer and Runtime Trust Banner*
*Context gathered: 2026-05-16*

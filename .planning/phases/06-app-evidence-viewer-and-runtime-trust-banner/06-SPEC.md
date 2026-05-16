# Phase 6: App Evidence Viewer and Runtime Trust Banner - Specification

**Created:** 2026-05-16
**Ambiguity score:** 0.19 (gate: <= 0.20)
**Requirements:** 8 locked

## Goal

Ragstudio operators can see whether the running app is trustworthy and inspect query or chunk evidence in context without leaving the Studio shell.

## Background

The current Studio already has the raw pieces for this experience, but they are spread across pages. `frontend/src/components/app-shell.tsx` renders the global shell and header, but it does not show runtime trust state. `frontend/src/features/diagnostics/diagnostics-page.tsx` displays `/api/diagnostics` details, and the backend already returns `overall_status`, `checks`, `warnings`, dependency status, graph projection state, stale job counts, and capability flags. `frontend/src/features/settings/settings-page.tsx` already has provider test mutations for embedding, LLM, reranker, and MinerU settings.

For evidence inspection, `frontend/src/features/query/query-page.tsx` renders query answers, sources, chunk traces, reranker traces, timings, and token metadata as raw JSON panels. `frontend/src/features/chunks/chunk-inspector.tsx` renders chunk search rows with chunk text, source location, metadata, retrieval explain details, and runtime badges. Backend schemas already expose `RunOut.sources`, `RunOut.chunk_traces`, `RunOut.reranker_traces`, `ChunkOut.text`, `ChunkOut.source_location`, `ChunkOut.metadata`, `ChunkOut.retrieval_explain`, and relationship refs. The missing product behavior is a focused evidence viewer that connects these fields into an operator-readable debugging surface.

## Requirements

1. **Runtime trust chip**: The app shell displays a compact runtime trust chip derived from current diagnostics.
   - Current: The app shell shows navigation and page title only; runtime health is visible only after opening Diagnostics.
   - Target: Every Studio page shows a compact status with one of `Ready`, `Degraded`, `Blocked`, `Indexing`, `Graph pending`, or `Provider issue`, based on `/api/diagnostics`.
   - Acceptance: With mocked diagnostics for ready, degraded, failed, pending graph projection, stale job, and provider failure states, the shell renders the expected chip label and accessible status text.

2. **Automatic status refresh**: Runtime trust status refreshes automatically without user interaction.
   - Current: Diagnostics refresh only when the Diagnostics page query runs or the user clicks Refresh.
   - Target: The shell status polls diagnostics on a bounded interval and updates the chip when diagnostics change.
   - Acceptance: A frontend test with fake timers proves the shell calls `apiClient.diagnostics` on initial render and again after the configured polling interval; provider retest actions are not triggered by polling.

3. **Runtime trust detail panel**: Clicking the chip opens a detail panel that explains readiness across core runtime areas.
   - Current: Diagnostics tables expose checks and dependencies, but there is no compact cross-page summary.
   - Target: The panel groups backend/API, worker/jobs, Postgres/PGVector, Neo4j/graph projection, MinerU/parser, LLM, embeddings, and reranker readiness with ready/degraded/blocked status and the current blocking detail when present.
   - Acceptance: Given a diagnostics payload with failed Neo4j, pending graph projection, and stale worker lease, the panel shows those exact issues in named sections and preserves the raw Diagnostics page as the deeper drill-down.

4. **Runtime trust actions**: The detail panel provides operator actions for refresh, diagnostics navigation, and provider retests.
   - Current: Diagnostics refresh and provider test actions are split across Diagnostics and Settings pages.
   - Target: The panel includes actions for `Refresh status`, `Open Diagnostics`, `Test LLM`, `Test embeddings`, `Test reranker`, and `Test MinerU`; provider tests use the current default settings profile and show success/failure details inline.
   - Acceptance: Frontend tests verify each action calls the correct API client method or navigates to `/diagnostics`; failed test calls display the API error message without closing the panel.

5. **Evidence viewer entry points**: Query source rows and Chunk Inspector rows can open a focused evidence viewer.
   - Current: Query result evidence is split across JSON panels, and Chunk Inspector rows are static cards.
   - Target: Each query source and each chunk result exposes an `Inspect evidence` control that opens the same viewer with the selected source or chunk as context.
   - Acceptance: Frontend tests can open the viewer from a mocked Query source and from a mocked Chunk Inspector row, and the viewer identifies the selected chunk/source id.

6. **Evidence viewer content**: The viewer shows the evidence fields needed for faster debugging and local user trust.
   - Current: Chunk text, source location, metadata, parser warnings, quality policy, and reranker traces are available but require reading raw JSON panels.
   - Target: The viewer displays exact chunk text, document id/name when available, source location, metadata summary, parser warnings, quality action/status, retrieval reasons, reranker provider/model/status/rank context, and the raw JSON fallback.
   - Acceptance: Given a source with `parser_quality_warning_codes`, `quality_action_policy`, source location, and reranker trace data, the viewer renders human-readable sections for all of those fields plus a raw JSON section.

7. **Graph neighbor context**: The viewer includes graph relationship context when available and a clear unavailable state when not available.
   - Current: Graph information is available on the Graph page and in selected retrieval traces, but it is not connected to source inspection.
   - Target: The viewer shows graph neighbor or relationship references linked to the selected chunk when the payload contains them, and otherwise shows why graph context is unavailable or absent.
   - Acceptance: Given a chunk/source with relationship refs, the viewer lists those refs; given diagnostics where graph capability is disabled, the viewer shows the diagnostics reason instead of an empty graph section.

8. **Cross-surface navigation and accessibility**: The viewer and status panel route back to existing Studio surfaces and remain keyboard/mobile usable.
   - Current: Existing pages are navigable from the sidebar, but evidence/status details do not link operators to the related page context.
   - Target: The viewer provides links to Documents, Chunks, Query, Graph, and Diagnostics where applicable; both the viewer and status panel trap focus when modal, close on Escape, restore focus on close, fit mobile viewports, and avoid text overlap.
   - Acceptance: Component tests verify Escape close and focus restoration; Playwright or equivalent UI checks cover desktop and mobile widths without clipped controls, overlapped text, or inaccessible action buttons.

## Boundaries

**In scope:**
- App shell runtime trust chip derived from diagnostics.
- Auto-polling diagnostics for shell status.
- Runtime trust detail panel with grouped health sections.
- Manual actions for refresh, Diagnostics navigation, and LLM/embedding/reranker/MinerU provider tests.
- Evidence viewer opened from Query sources and Chunk Inspector rows.
- Human-readable evidence sections for chunk text, source location, metadata, parser warnings, quality status, reranker context, graph neighbors, and raw JSON fallback.
- Links from the viewer to existing Documents, Chunks, Query, Graph, and Diagnostics surfaces.
- Frontend tests for status states, panel actions, evidence entry points, and accessibility-critical interactions.

**Out of scope:**
- Exportable investigation reports - separate phase after viewer and status primitives exist.
- Public proof-site changes - this phase targets the local Ragstudio Studio app, not `ragstudio-site`.
- New live hosted demo, upload sandbox, or public API path - outside the local app UI scope.
- New provider configuration fields or saved settings mutation - this phase can test current settings but must not redesign Settings.
- New graph materialization or retrieval algorithms - the viewer displays available graph/retrieval context, it does not change retrieval behavior.
- Full document/PDF page preview and visual page highlighting - later enhancement after evidence selection is stable.
- Authentication, multi-user permissions, or audit-log storage - not required for the local operator workflow.

## Constraints

- Use current diagnostics and settings test APIs where possible; add backend fields only when the existing payload cannot express a required status or evidence field.
- Auto polling must be bounded and non-destructive; it must refresh diagnostics only and never trigger provider tests, reindexing, graph materialization, or settings updates.
- Provider retests are manually triggered by the user and must use the currently saved/default settings profile.
- Runtime trust labels must be deterministic from diagnostics data so tests can assert them.
- Evidence viewer must tolerate partial payloads from older runs or legacy chunks and show `Unavailable` or `Not recorded` states instead of crashing.
- UI must meet existing frontend conventions: lucide icons, compact operational layout, no nested card-heavy composition, responsive text containment, and accessible focus behavior.

## Acceptance Criteria

- [ ] App shell renders a runtime trust chip on all Studio routes using `/api/diagnostics`.
- [ ] Runtime trust chip auto-polls diagnostics and updates when status changes.
- [ ] Runtime trust detail panel groups backend/API, worker/jobs, Postgres/PGVector, Neo4j/graph projection, MinerU/parser, LLM, embeddings, and reranker readiness.
- [ ] Runtime trust actions include Refresh status, Open Diagnostics, Test LLM, Test embeddings, Test reranker, and Test MinerU.
- [ ] Query sources expose an Inspect evidence control that opens the evidence viewer.
- [ ] Chunk Inspector rows expose an Inspect evidence control that opens the evidence viewer.
- [ ] Evidence viewer displays exact chunk text, source location, metadata summary, parser warnings, quality action/status, reranker context, graph neighbor context, and raw JSON fallback when those fields exist.
- [ ] Evidence viewer shows explicit unavailable states for missing graph/reranker/parser-quality data instead of blank sections.
- [ ] Viewer links route to existing Documents, Chunks, Query, Graph, and Diagnostics surfaces where applicable.
- [ ] Frontend tests cover status mapping, polling, provider action calls, Query entry point, Chunk entry point, and modal keyboard behavior.

## Ambiguity Report

| Dimension          | Score | Min   | Status | Notes |
|--------------------|-------|-------|--------|-------|
| Goal Clarity       | 0.90  | 0.75  | met    | Outcome locked as faster debugging and clearer local trust. |
| Boundary Clarity   | 0.80  | 0.70  | met    | Includes Query and Chunk entry points; excludes export reports and public site work. |
| Constraint Clarity | 0.70  | 0.65  | met    | Auto polling, provider retest side effects, and partial payload behavior are constrained. |
| Acceptance Criteria| 0.72  | 0.70  | met    | Criteria are pass/fail and map to UI tests. |
| **Ambiguity**      | 0.19  | <=0.20| met    | Gate passed after round 2. |

Status: met = dimension meets minimum.

## Interview Log

| Round | Perspective | Question summary | Decision locked |
|-------|-------------|------------------|-----------------|
| 1 | Researcher | Should Evidence Viewer open from Query only or Query plus Chunk Inspector? | Include both Query result sources and Chunk Inspector rows. |
| 1 | Researcher | Should Runtime Trust Banner be read-only diagnostics or include actions? | Include diagnostics status plus useful actions. |
| 1 | Researcher | Main success outcome: debugging, local trust, or public screenshot story? | Optimize for faster debugging and clearer local user trust. |
| 2 | Researcher + Simplifier | Should Evidence Viewer include graph neighbors? | Include chunk text, source location, metadata, parser/quality warnings, reranker context, and graph neighbors. |
| 2 | Researcher + Simplifier | Should banner actions include provider retests? | Include Refresh, Open Diagnostics, Test LLM, Test embeddings, Test reranker, and Test MinerU. |
| 2 | Researcher + Simplifier | Should Runtime Trust Banner poll automatically or refresh manually only? | Poll automatically, with manual refresh still available. |

---

*Phase: 06-app-evidence-viewer-and-runtime-trust-banner*
*Spec created: 2026-05-16*
*Next step: $gsd-discuss-phase 6 - implementation decisions (how to build what's specified above)*

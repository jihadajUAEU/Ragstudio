# Phase 6: App Evidence Viewer and Runtime Trust Banner - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-16
**Phase:** 06-App Evidence Viewer and Runtime Trust Banner
**Areas discussed:** Trust Status Priority, Trust Panel Actions, Evidence Viewer Shape, Graph + Unavailable Evidence

---

## Trust Status Priority

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic priority ladder | Show the most urgent operator action first: `Blocked` > `Provider issue` > `Indexing` > `Graph pending` > `Degraded` > `Ready`; the detail panel still shows everything. | ✓ |
| Backend status first | Use `/api/diagnostics.overall_status` as the main source, then only show `Graph pending`, `Indexing`, or `Provider issue` when backend status is otherwise `ready`. | |
| Primary label plus small secondary hint | Main chip shows `Blocked/Degraded/Ready`, with a small hint like `Graph pending` or `2 issues`; richer but more UI complexity. | |

**User's choice:** Deterministic priority ladder.
**Notes:** The chip primary label should be deterministic and action-oriented.

| Option | Description | Selected |
|--------|-------------|----------|
| Compact but color-coded | Small chip in the header; red for `Blocked/Provider issue`, amber for `Indexing/Graph pending/Degraded`, green for `Ready`. | ✓ |
| Always quiet until clicked | Keep the chip visually subtle for all statuses, relying on the detail panel for urgency. | |
| Attention-grabbing for blocked states | `Blocked` and `Provider issue` become more prominent, with stronger visual treatment. | |

**User's choice:** Compact but color-coded.
**Notes:** Keep the status visible without making every page feel noisy.

| Option | Description | Selected |
|--------|-------------|----------|
| Show `Blocked` with `Diagnostics unavailable` | Treat missing diagnostics as a trust problem; panel shows API error plus Refresh/Open Diagnostics. | ✓ |
| Show `Degraded` | Less alarming, but may understate that the app cannot prove runtime health. | |
| Show `Unknown` | Technically precise, but adds a seventh label beyond the SPEC target labels. | |

**User's choice:** Show `Blocked` with `Diagnostics unavailable`.
**Notes:** Diagnostics failure is itself a blocked trust state.

| Option | Description | Selected |
|--------|-------------|----------|
| Every 30 seconds | Fast enough for indexing/graph/provider changes to become visible without making the backend noisy. | ✓ |
| Every 60 seconds | Quieter backend load, slower feedback. | |
| Every 15 seconds | More live, but unnecessarily chatty for a diagnostic summary. | |

**User's choice:** Every 30 seconds.
**Notes:** Polling is diagnostics-only and must never trigger provider tests.

---

## Trust Panel Actions

| Option | Description | Selected |
|--------|-------------|----------|
| Separate test buttons with inline results | Show `Test LLM`, `Test embeddings`, `Test reranker`, and `Test MinerU` as separate actions, each with its own latest result. | ✓ |
| One `Test all providers` button plus details | Faster one-click health check, but slower/noisier and harder to isolate failures. | |
| Separate buttons plus optional `Test all` | Most complete, but more UI and test complexity than Phase 6 needs. | |

**User's choice:** Separate test buttons with inline results.
**Notes:** Optimize for isolated debugging of individual dependencies.

| Option | Description | Selected |
|--------|-------------|----------|
| Allow independent tests in parallel | Each button only disables itself while running; faster debugging with separated results. | ✓ |
| Only one provider test at a time | Simpler state and less provider load, but slower when checking several dependencies. | |
| Disable all actions while any test runs | Conservative, but makes the panel feel stuck during slow tests. | |

**User's choice:** Allow independent tests in parallel.
**Notes:** Each provider test owns its own pending state.

| Option | Description | Selected |
|--------|-------------|----------|
| Saved default settings profile only | Fetch `apiClient.defaultSettings()` and test exactly what the running app uses. | ✓ |
| Current Settings form values if Settings page is open | Useful while editing, but unreliable from a global shell panel. | |
| Ask the user to open Settings for tests | Safest implementation, but weaker for fast debugging. | |

**User's choice:** Saved default settings profile only.
**Notes:** Matches the SPEC and avoids unsaved Settings-page confusion.

| Option | Description | Selected |
|--------|-------------|----------|
| Stay until the panel closes or test runs again | Good for comparing provider results during a debugging pass. | ✓ |
| Auto-clear after a short timeout | Keeps the panel clean, but can erase useful failure text too quickly. | |
| Persist across page navigation | Helpful, but implies extra state beyond this phase. | |

**User's choice:** Stay until panel closes or test reruns.
**Notes:** Results are session-local to the open panel.

---

## Evidence Viewer Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Right-side drawer on desktop, full-screen sheet on mobile | Keeps page context visible on desktop and gives mobile enough room. | ✓ |
| Centered modal | Simpler and direct, but long chunk text/JSON can feel cramped. | |
| Inline expansion under the row | Contextual, but duplicates heavy UI and makes long results hard to scan. | |

**User's choice:** Right-side drawer on desktop, full-screen sheet on mobile.
**Notes:** Best match for inspecting evidence without leaving the Studio shell.

| Option | Description | Selected |
|--------|-------------|----------|
| Human-readable evidence summary first | Top shows chunk/source id, document/location, quality/parser/reranker badges, exact chunk text; raw JSON lower. | ✓ |
| Exact chunk text first | Fastest for reading evidence, but status and warning context are less visible. | |
| Raw payload first with summaries below | Developer-heavy and weaker for local trust. | |

**User's choice:** Human-readable evidence summary first.
**Notes:** Raw JSON remains a fallback, not the primary experience.

| Option | Description | Selected |
|--------|-------------|----------|
| Render compact source rows above/alongside raw Sources JSON | Add readable source rows with `Inspect evidence`; keep raw JSON fallback. | ✓ |
| Add buttons inside the existing JSON panel | Smaller change, but awkward and harder to make accessible. | |
| Replace raw Sources JSON with readable rows | Cleaner UI, but loses raw fallback too early. | |

**User's choice:** Render compact source rows while keeping raw JSON.
**Notes:** Query page should become readable without removing debugging depth.

| Option | Description | Selected |
|--------|-------------|----------|
| Show key sections expanded; raw JSON collapsed | Expanded summary/common evidence, collapsed raw payloads. | |
| Everything expanded | Max transparency, but long metadata/JSON can overwhelm the drawer. | |
| Only summary expanded | Tidy by default; users expand details as needed. | ✓ |

**User's choice:** Only summary expanded.
**Notes:** Detailed sections remain accessible but do not dominate initial view.

| Option | Description | Selected |
|--------|-------------|----------|
| Shared viewer with normalized evidence input | Keeps behavior consistent across Query and Chunk rows. | ✓ |
| Separate Query and Chunk viewers | Faster locally but risks drift and duplicated accessibility/fallback logic. | |
| Shared layout, separate data adapters | Middle path with one shell and page-specific normalizers. | |

**User's choice:** Shared viewer with normalized evidence input.
**Notes:** Consistency matters more than page-local shortcuts.

---

## Graph + Unavailable Evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Explain using diagnostics when available | If graph is disabled/pending/failed, show that reason; otherwise show no relationship recorded. | ✓ |
| Only use the selected payload | Show refs if present; otherwise `Not recorded`. Simpler but less helpful for global graph issues. | |
| Fetch full graph data on drawer open | Richer context, but likely larger and slower than Phase 6 needs. | |

**User's choice:** Explain using diagnostics when available.
**Notes:** Use diagnostics for missing graph context, but do not fetch full graph data.

| Option | Description | Selected |
|--------|-------------|----------|
| Show run-level reranker summary plus `not source-specific` | Useful and honest when exact source rank was not recorded. | ✓ |
| Hide reranker section unless exact source match exists | Precise, but loses useful debugging context. | |
| Show all reranker traces raw only | Complete, but much less readable. | |

**User's choice:** Show run-level reranker summary plus `not source-specific`.
**Notes:** Avoid implying a source-specific rank that is not present.

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit `Not recorded` states | Each missing section says what is missing. | ✓ |
| Hide missing sections | Cleaner, but ambiguous about whether data passed or was never recorded. | |
| Single generic `legacy payload` note | Compact, but not precise enough for debugging. | |

**User's choice:** Explicit `Not recorded` states.
**Notes:** Missing parser/quality/source fields should be visible and honest.

| Option | Description | Selected |
|--------|-------------|----------|
| Always show available route links with disabled/unavailable labels | Example: `Open Chunks`, `Open Graph`, `Open Diagnostics`, or `Document link not recorded`. | ✓ |
| Only show links that can definitely navigate | Cleaner, but hides why a useful link is missing. | |
| Show all links and let destination pages handle missing context | Simpler, but can feel broken if context is absent. | |

**User's choice:** Always show available route links with disabled/unavailable labels.
**Notes:** Links should teach what context exists and what was not recorded.

---

## the agent's Discretion

- Exact component boundaries, helper names, normalized evidence type names, test filenames, and status derivation helper shape.

## Deferred Ideas

- Exportable investigation reports.
- Full document/PDF visual page preview and visual page highlighting.
- Fetching full graph data on evidence drawer open.

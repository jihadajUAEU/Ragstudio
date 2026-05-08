# Branch Runtime UI Review

**Audited:** 2026-05-08
**Baseline:** Product context + `docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md`
**Git range:** `71c5f6ec01c56f6b70f95b89a241e4af44124d4a..fe0d7aae6bb2dd9b9af2ecd4d40f0f8c1dca6303`
**Screenshots:** Captured in `.planning/ui-reviews/branch-runtime-20260508-192235`

---

## Resolution

Post-review fixes were applied after this audit:

- Native runtime is labeled as blocked while the adapter is pending.
- Runtime mode and storage backend now move as explicit fallback/native pairs.
- Secret inputs are controlled and clear after successful save, reload, or reset.
- Diagnostics overall runtime status now uses severity-colored badge treatment.
- Chunk search empty state now refers to mirrored chunks.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 2/4 | Native runtime copy implies an available mode without inline blocked-state context. |
| 2. Visuals | 3/4 | Settings layout is readable and operational, but runtime safety state is visually under-emphasized. |
| 3. Color | 3/4 | Status colors are consistent, but Diagnostics overall status is plain text instead of severity-coded. |
| 4. Typography | 3/4 | Type scale is controlled and scannable; dense forms rely on repeated same-weight labels. |
| 5. Spacing | 3/4 | Spacing is consistent; mobile stacks cleanly, but long settings pages have little grouping guidance. |
| 6. Experience Design | 2/4 | Runtime/storage pairing and uncontrolled secret reset behavior create avoidable safety risks. |

**Overall: 16/24**

---

## Top 3 Priority Fixes

1. **Make native runtime unavailable/blocked in Settings until implemented** - prevents users from saving a mode that looks production-ready - add disabled option or adjacent warning/status callout tied to runtime health.
2. **Fix secret reset/save behavior for password fields** - prevents stale typed secrets from surviving Reset or post-save - control secret inputs or remount/clear them on reset and mutation success.
3. **Align runtime/storage pairing in both directions** - prevents `fallback` + `Postgres / PGVector / Neo4j` ambiguity - selecting production storage should switch to native runtime or show an explicit "fallback ignores production stores" state.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)

- **WARNING:** `frontend/src/features/settings/settings-page.tsx:347` renders `Runtime mode` with an enabled `Native runtime` option at `:355`, but the branch context says the native RAG-Anything adapter is intentionally blocked until implemented. The Settings page has no inline warning that selecting native runtime will hit a blocking diagnostics check rather than execute a complete native adapter.
- **WARNING:** `frontend/src/features/chunks/chunk-inspector.tsx:250` still says "No chunks matched" instead of the planned "No mirrored chunks matched", weakening the distinction between mirrored inspection snapshots and retrieval truth.
- **WARNING:** `frontend/src/features/settings/settings-page.tsx:1192` reports "No default profile saved" but the form silently falls back to default local fallback values. This is safe operationally, but it should say that a fallback profile can be saved from the defaults.

### Pillar 2: Visuals (3/4)

- **WARNING:** Screenshots show the Settings page is clean and predictable, with dense two-column form sections on desktop and a single-column mobile stack. However, runtime mode is visually identical to ordinary low-risk selects at `frontend/src/features/settings/settings-page.tsx:347`, despite being the highest-risk control on the page.
- **WARNING:** Diagnostics summary metrics at `frontend/src/features/diagnostics/diagnostics-page.tsx:166` make "Overall status" prominent, but the value is just title-cased text at `:170`; failed/degraded/fallback states do not get the badge treatment used elsewhere.

### Pillar 3: Color (3/4)

- **WARNING:** Runtime check statuses use green/yellow/red badges at `frontend/src/features/diagnostics/diagnostics-page.tsx:310`, but the top-level overall runtime status does not. This makes the most important status less visually actionable than lower-level checks.
- **INFO:** The changed surfaces use the existing palette consistently: teal accent `#176b87`, neutral borders/backgrounds, green/yellow/red status colors. No new arbitrary color family dominates the branch-specific UI.

### Pillar 4: Typography (3/4)

- **WARNING:** The affected files stay within a small type scale (`text-xs`, `text-sm`, `text-base`, `text-2xl`) and two main weights (`font-medium`, `font-semibold`). This is good for operational scanability.
- **WARNING:** The Settings form has many repeated section headers and field labels at the same visual weight (`frontend/src/features/settings/settings-page.tsx:333`, `:415`, `:509`, `:656`, `:760`, `:885`), so the most consequential controls are not typographically differentiated.

### Pillar 5: Spacing (3/4)

- **WARNING:** Spacing is consistent (`gap-4`, `p-4`, `sm:p-5`, `h-10` controls) and screenshots confirm mobile labels/controls do not overlap at 375px.
- **WARNING:** The page adds many controls without sticky actions or a compact navigation aid; on mobile the Save action is far below the runtime controls (`frontend/src/features/settings/settings-page.tsx:988`), which increases repeated-use friction for an operational settings surface.

### Pillar 6: Experience Design (2/4)

- **WARNING:** `frontend/src/features/settings/settings-page.tsx:141` only forces fallback when storage becomes `fallback_local`; selecting `postgres_pgvector_neo4j` at `:366` while runtime mode remains `fallback` is possible. That pairing reads as production storage but still uses fallback behavior, which is ambiguous and risky for operators.
- **WARNING:** Password inputs are intentionally uncontrolled via `Field` when no `onChange` is passed (`frontend/src/features/settings/settings-page.tsx:1037`), including Neo4j, vision, reranker, LLM, and embedding secrets (`:403`, `:439`, `:488`, `:540`, `:921`). The Reset button only clears React state at `:996`; it does not clear typed secret DOM values, so a later save/test can still submit a secret the user thought was discarded.
- **WARNING:** Diagnostics has loading/error/empty states and runtime checks (`frontend/src/features/diagnostics/diagnostics-page.tsx:150`, `:224`), but the implementation does not render the planned top-level `<StatusBadge status={diagnosticsQuery.data.overall_status} />` from the plan, reducing status clarity.

---

## Requested 1-5 Scores

| Category | Score |
|----------|-------|
| Clarity | 3/5 |
| Interaction safety | 2/5 |
| Visual hierarchy | 3/5 |
| Responsiveness | 4/5 |
| Accessibility | 3/5 |
| Product fit | 3/5 |

---

## Registry Safety

Skipped: `components.json` is not present, so shadcn/third-party registry audit does not apply.

---

## Files Audited

- `frontend/src/api/generated.ts`
- `frontend/src/features/settings/settings-page.tsx`
- `frontend/src/features/diagnostics/diagnostics-page.tsx`
- `frontend/src/features/chunks/chunk-inspector.tsx`
- `frontend/src/features/query/query-page.tsx`
- `frontend/src/components/data-table.tsx`
- `frontend/tests/settings-page.test.tsx`
- `frontend/tests/chunk-inspector.test.tsx`
- `frontend/tests/pipeline-builder.test.tsx`
- `docs/superpowers/specs/2026-05-08-rag-anything-production-runtime-design.md`
- `docs/superpowers/plans/2026-05-08-rag-anything-production-runtime.md`

# Phase 4: Static Proof Viewer and Public Site UX - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 4-Static Proof Viewer and Public Site UX
**Areas discussed:** First viewport, Claim list shape, Claim detail view, Evidence panels, Feedback links, Screenshots, Raw artifact experience

---

## Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| All core areas | Landing story, proof viewer detail, feedback links, screenshots/signoff. | ✓ |
| Viewer only | Claim list, claim detail, evidence panels, raw artifacts, deep links. | |
| Screenshots only | Approved demo images, signoff, responsive polish. | |

**User's choice:** All core areas.
**Notes:** User chose to discuss the full Phase 4 decision set before context capture.

---

## First Viewport

| Option | Description | Selected |
|--------|-------------|----------|
| Proof-first technical field guide | Lead with “Ragstudio makes RAG evidence inspectable before retrieval breaks answers,” then CTA `Inspect the proof trail`. | ✓ |
| Product-story first | Lead with a simpler public story about document quality gates, then introduce proof trail as validation. | |
| Evidence dashboard first | Put claim counts, packet status, and source commit immediately up front, with less narrative. | |

**User's choice:** Proof-first technical field guide.
**Notes:** This preserves the approved Technical Field Guide direction and keeps the proof trail as the first trust moment.

---

## Claim List Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Status-grouped list | Separate `Proven`, `Roadmap`, and `Disabled` sections so honesty is obvious. | ✓ |
| Single table | One dense table with status, claim, evidence count, source commit, and links. | |
| Story sequence | Claims appear in a guided order: parser gate, trace visibility, roadmap, disabled. | |

**User's choice:** Status-grouped list.
**Notes:** Non-proven claims must stay visible and clearly labeled.

---

## Claim Detail View

| Option | Description | Selected |
|--------|-------------|----------|
| Evidence dossier | Clear sections for summary, proof status, limitations, evidence artifacts, raw links, and source commit. | ✓ |
| Narrative walkthrough | A guided explanation first, with artifacts revealed progressively. | |
| Raw artifact explorer | Dense JSON/artifact-first view for technical users. | |

**User's choice:** Evidence dossier.
**Notes:** Claim detail should be inspectable without becoming a raw JSON-first interface.

---

## Evidence Panels

| Option | Description | Selected |
|--------|-------------|----------|
| By evidence type | Parser warning/unit, chunk/source, retrieval trace, graph/reranker, screenshot, raw artifact. | ✓ |
| By artifact file | One panel per artifact path, with extracted highlights inside. | |
| By proof strength | Proven evidence first, limitations/missing evidence after. | |

**User's choice:** By evidence type.
**Notes:** The viewer should map evidence to the proof concepts visitors need to inspect.

---

## Feedback Links

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-filled GitHub issue URL | Include claim id, artifact path, packet id/hash, source commit, and viewer URL. | ✓ |
| mailto link | Open email with the same proof context. | |
| Copy feedback context | Button copies the context block; no external destination yet. | |

**User's choice:** Pre-filled GitHub issue URL.
**Notes:** Phase 4 remains static-friendly while carrying enough proof context for actionable feedback.

---

## Screenshots

| Option | Description | Selected |
|--------|-------------|----------|
| Use only approved packet screenshots | Render screenshots already listed in the proof packet/signoff. | ✓ |
| Add new static screenshots from the local app | Capture more screenshots now, then add signoff records. | |
| No screenshots in Phase 4 | Keep screenshot rendering deferred to Phase 5. | |

**User's choice:** Use only approved packet screenshots.
**Notes:** No new local screenshots should enter Phase 4 without explicit signoff work.

---

## Raw Artifact Experience

| Option | Description | Selected |
|--------|-------------|----------|
| Static raw artifact links with fallback text | Link to `/proof/<packet>/...`; if not copied yet, show clear “not available in this static build.” | ✓ |
| Inline JSON preview | Render compact JSON snippets inside the detail page. | |
| Download-only links | Keep the UI simple and let users open/download raw files. | |

**User's choice:** Static raw artifact links with fallback text.
**Notes:** Avoid broken links and avoid implying unavailable artifacts are present in the static build.

## the agent's Discretion

- Exact React component boundaries, route implementation, local type definitions, CSS structure, and test names.
- Exact visual layout within the Technical Field Guide direction.

## Deferred Ideas

- Cloudflare Pages/domain/release gates remain Phase 5.
- Public upload/auth/live backend demo remains out of scope for v1.
- New screenshot capture is deferred unless a later phase adds capture plus signoff.

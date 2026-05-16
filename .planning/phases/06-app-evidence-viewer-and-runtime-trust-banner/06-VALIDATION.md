---
phase: 06
slug: app-evidence-viewer-and-runtime-trust-banner
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-16
---

# Phase 6 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest 4.1.5 + Testing Library 16.3.2 |
| **Config file** | `frontend/vite.config.ts` |
| **Quick run command** | `npm test -- --run app-shell.test.tsx query-page.test.tsx chunk-inspector.test.tsx graph-page.test.tsx settings-page.test.tsx` |
| **Full suite command** | `npm test && npm run build` |
| **Estimated runtime** | ~60-180 seconds |

---

## Sampling Rate

- **After every task commit:** Run the targeted changed test file with `npm test -- --run <file>.test.tsx`.
- **After every plan wave:** Run `npm test -- --run app-shell.test.tsx query-page.test.tsx chunk-inspector.test.tsx graph-page.test.tsx settings-page.test.tsx`.
- **Before `$gsd-verify-work`:** Run `npm test && npm run build` from `frontend/`.
- **Max feedback latency:** 180 seconds for the targeted Phase 6 suite.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | APP-UI-02 | T-06-01 | Diagnostics polling does not trigger provider tests or settings mutation | component | `npm test -- --run app-shell.test.tsx` | yes | pending |
| 06-01-02 | 01 | 1 | APP-UI-02 | T-06-01 | Trust status maps failed diagnostics to blocked state | component | `npm test -- --run app-shell.test.tsx` | yes | pending |
| 06-01-03 | 01 | 1 | APP-UI-02 | T-06-02 | Provider tests use saved default settings without rendering secrets | component | `npm test -- --run app-shell.test.tsx settings-page.test.tsx` | yes | pending |
| 06-02-01 | 02 | 2 | APP-UI-01 | T-06-03 | Loose Query source payloads are normalized without unsafe HTML rendering | component | `npm test -- --run query-page.test.tsx` | yes | pending |
| 06-02-02 | 02 | 2 | APP-UI-01 | T-06-03 | Chunk payloads show explicit missing-state text instead of hiding fields | component | `npm test -- --run chunk-inspector.test.tsx` | yes | pending |
| 06-03-01 | 03 | 3 | APP-UI-01, APP-UI-02 | T-06-04 | Dialog focus is trapped and restored; mobile layout avoids clipped controls | component/build | `npm test -- --run app-shell.test.tsx query-page.test.tsx chunk-inspector.test.tsx && npm run build` | yes | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements:

- `frontend/vite.config.ts` already configures Vitest with jsdom.
- Existing tests already cover `AppShell`, `QueryPage`, `ChunkInspector`, `GraphPage`, and `SettingsPage`.
- No new package or test framework is required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 320px mobile text/control containment | APP-UI-01, APP-UI-02 | jsdom does not compute real layout and clipping reliably | Start the frontend dev server, open the app at 320px width, verify trust chip, panel, evidence drawer, and provider buttons do not overlap or clip. |
| Desktop drawer preserves page context | APP-UI-01 | Component tests can assert DOM state but not visual page context | Open Query/Chunks at desktop width, inspect evidence, and confirm right drawer leaves the current page visible behind the overlay. |

---

## Validation Sign-Off

- [x] All tasks have automated verify commands or existing Wave 0 infrastructure.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency < 180s for targeted suite.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-05-16

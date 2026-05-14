---
phase: 05-launch-hardening-and-domain-release
plan: "02"
subsystem: testing
tags: [playwright, axe, accessibility, launch-gate, fixture-size]
requires:
  - phase: 05-launch-hardening-and-domain-release
    provides: 05-01 release proof and Cloudflare setup docs
provides:
  - Playwright proof-viewer flow coverage
  - axe accessibility scans for homepage and deep-linked claim dossier
  - Fixture-size gate for public proof assets
  - Manual launch checklist parser and fail-closed launch command
affects: [05-launch-hardening-and-domain-release, ragstudio-site, accessibility]
tech-stack:
  added:
    - "@playwright/test"
    - "@axe-core/playwright"
  patterns:
    - Tagged Playwright tests split browser flow and axe scans
    - `launch:check` composes all release gates and blocks unchecked manual items
key-files:
  created:
    - /Users/meet/Documents/ragstudio-site/playwright.config.ts
    - /Users/meet/Documents/ragstudio-site/tests/e2e/proof-viewer.spec.ts
    - /Users/meet/Documents/ragstudio-site/scripts/check-fixture-size.mjs
    - /Users/meet/Documents/ragstudio-site/scripts/launch-check.mjs
    - /Users/meet/Documents/ragstudio-site/docs/launch/manual-checklist.md
  modified:
    - /Users/meet/Documents/ragstudio-site/package.json
    - /Users/meet/Documents/ragstudio-site/package-lock.json
    - /Users/meet/Documents/ragstudio-site/scripts/import-proof-packet.mjs
    - /Users/meet/Documents/ragstudio-site/src/App.tsx
    - /Users/meet/Documents/ragstudio-site/src/styles.css
    - /Users/meet/Documents/ragstudio-site/vite.config.ts
key-decisions:
  - "Manual launch checklist items remain unchecked and block final launch unless `--allow-pending-manual` is used for prelaunch local checks."
  - "The proof importer now preserves screenshot assets referenced by the public viewer."
patterns-established:
  - "Browser-flow tests use `test:e2e`; axe scans use `test:a11y` with the `@a11y` tag."
  - "Fixture-size checks report `totalBytes` and enforce a configurable threshold with `PROOF_FIXTURE_MAX_BYTES`."
requirements-completed:
  - QA-01
  - QA-02
  - QA-03
  - QA-04
  - QA-05
duration: 11 min
completed: 2026-05-14
---

# Phase 05 Plan 02: Launch Quality Gate Summary

**Playwright, axe, fixture-size, and manual-checklist gates now block the public proof release path.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-05-14T15:56:59Z
- **Completed:** 2026-05-14T16:04:19Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Added Playwright coverage for homepage, proof CTA navigation, deep-linked claim dossier, feedback context, screenshot rendering, and 320px/390px overflow.
- Added axe scans for `/` and `/#claim-RAGSTUDIO-TRACE-VISIBILITY`.
- Added fixture-size reporting and threshold enforcement for public proof assets.
- Added a parseable manual launch checklist for keyboard, mobile, overflow, raw fallbacks, overlap, screenshot/privacy, `ragstudio.dev`, README, and `jihadaj.com`.
- Added `npm run launch:check` as the composed release gate.

## Task Commits

1. **Tasks 1-3: Launch quality gate** - `a31d8e1` (`feat(05-02): add launch quality gate`)

**Plan metadata:** pending in this summary commit

## Files Created/Modified

- `/Users/meet/Documents/ragstudio-site/playwright.config.ts` - Local Vite preview server and Playwright configuration.
- `/Users/meet/Documents/ragstudio-site/tests/e2e/proof-viewer.spec.ts` - Browser flow, mobile overflow, screenshot-load, and axe tests.
- `/Users/meet/Documents/ragstudio-site/scripts/check-fixture-size.mjs` - Public proof asset-size report and threshold gate.
- `/Users/meet/Documents/ragstudio-site/scripts/launch-check.mjs` - Composed launch gate with manual-checklist blocking.
- `/Users/meet/Documents/ragstudio-site/docs/launch/manual-checklist.md` - Required manual launch signoff checklist.
- `/Users/meet/Documents/ragstudio-site/scripts/import-proof-packet.mjs` - Preserves public screenshot assets during proof import.
- `/Users/meet/Documents/ragstudio-site/src/App.tsx` and `/Users/meet/Documents/ragstudio-site/src/styles.css` - Accessibility fixes required by axe.

## Decisions Made

- Kept final manual checklist items unchecked because `ragstudio.dev`, README, and `jihadaj.com` are not final-verified yet.
- Used `--allow-pending-manual` only for prelaunch local validation; plain `npm run launch:check` fails while manual items remain pending.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Preserved screenshot assets during proof import**

- **Found during:** Task 3 (full launch gate)
- **Issue:** `npm run import:proof` pruned copied screenshot files, so the UI could show an image element whose public asset was missing.
- **Fix:** Updated the importer to copy `screenshots/signoff.json` and PNG screenshots listed in the packet hashes, then added an E2E `naturalWidth` assertion.
- **Files modified:** `/Users/meet/Documents/ragstudio-site/scripts/import-proof-packet.mjs`, `/Users/meet/Documents/ragstudio-site/tests/e2e/proof-viewer.spec.ts`
- **Verification:** `npm run launch:check -- --allow-pending-manual` passed with four public proof files present.
- **Committed in:** `a31d8e1`

**2. [Rule 3 - Blocking] Fixed axe accessibility failures**

- **Found during:** Task 1 (axe scans)
- **Issue:** Axe flagged roadmap label contrast, nested complementary landmark semantics, and repeated panel heading IDs.
- **Fix:** Darkened roadmap label color, changed nested proof-summary `aside` to a non-landmark `div`, and removed duplicated panel `aria-labelledby` IDs.
- **Files modified:** `/Users/meet/Documents/ragstudio-site/src/App.tsx`, `/Users/meet/Documents/ragstudio-site/src/styles.css`
- **Verification:** `npm run test:a11y` passed.
- **Committed in:** `a31d8e1`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking).
**Impact on plan:** Both fixes directly support the planned launch gate and accessibility contract.

## Issues Encountered

- Playwright was installed but Chromium was missing locally. Installed it with `npx playwright install chromium`, then reran the tests successfully.
- Vitest initially picked up the Playwright spec; `vite.config.ts` now excludes `tests/e2e/**`.

## Verification

- `npm run launch:check` - failed as expected while manual checklist items were unchecked.
- `PROOF_FIXTURE_MAX_BYTES=1 npm run check:fixtures` - failed as expected below current total bytes.
- `npm run test:e2e && npm run test:a11y` - passed.
- `npm run launch:check -- --allow-pending-manual` - passed.

## User Setup Required

No new external setup was added in this plan. The Phase 05 Cloudflare checklist
from `05-USER-SETUP.md` remains required before final launch.

## Next Phase Readiness

Ready for Plan 05-03: verify `https://ragstudio.dev`, update public amplifier
links, and record the final release proof/report.

---
*Phase: 05-launch-hardening-and-domain-release*
*Completed: 2026-05-14*

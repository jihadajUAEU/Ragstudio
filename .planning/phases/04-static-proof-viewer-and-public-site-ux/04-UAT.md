---
status: complete
phase: 04-static-proof-viewer-and-public-site-ux
source:
  - .planning/phases/04-static-proof-viewer-and-public-site-ux/04-01-SUMMARY.md
  - .planning/phases/04-static-proof-viewer-and-public-site-ux/04-02-SUMMARY.md
  - .planning/phases/04-static-proof-viewer-and-public-site-ux/04-03-SUMMARY.md
started: 2026-05-14T15:01:54Z
updated: 2026-05-14T15:06:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Proof-First Landing View
expected: Open the site. The first screen should present the Ragstudio proof story, the headline "Inspect RAG evidence before retrieval failures become answers.", and a primary "Inspect the proof trail" CTA. The proof summary should show the packet id, validation status, claim count, source commit, validated date, and validation id.
result: pass

### 2. Honest Claim Status Scan
expected: Click or scroll to "Inspect the proof trail". The claim trail should show separate "Proven claims", "Roadmap claims", and "Disabled claims" sections. The 2000+ page scale claim should remain roadmap, and the public upload claim should remain disabled rather than hidden or presented as proven.
result: pass

### 3. Claim Evidence Dossier
expected: Open the trace visibility claim dossier. The claim should show proof metadata, limitations, source paths, evidence panels for retrieval trace and graph/reranker states, raw artifact links, and fallback text where artifacts are not copied into the static build.
result: pass

### 4. Feedback Deep Link Context
expected: In any claim dossier, the "Open feedback issue" link should open a GitHub issue URL containing proof context: claim id, artifact path where available, packet id, validation id, source commit, and the claim hash.
result: pass

### 5. Approved Screenshot Signoff
expected: The screenshot evidence section should show only the approved Ragstudio documents-page screenshot, with reviewer "Meet", reviewed date, safe-to-publish state, and a caption/note saying it contains no uploaded private content.
result: pass

### 6. Mobile And Deep-Link Usability
expected: The claim deep link should load directly at the selected claim on desktop and mobile widths. Long claim ids, source paths, commits, and artifact paths should wrap without horizontal scrolling or overlapping text.
result: pass

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

none yet

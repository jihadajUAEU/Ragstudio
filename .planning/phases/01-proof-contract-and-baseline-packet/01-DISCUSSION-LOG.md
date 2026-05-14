# Phase 1: Proof Contract and Baseline Packet - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 1-Proof Contract and Baseline Packet
**Areas discussed:** Proof packet contents, Claim status rules, Synthetic corpus shape, Public safety boundary

---

## Proof Packet Contents

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| For the baseline packet, what should be mandatory? | Evidence-complete packet; Minimal contract packet; Split packet | Evidence-complete packet |
| How should the packet be organized? | Reviewer-first folders; Pipeline-first folders; Flat manifest-first | Reviewer-first folders |
| For raw artifacts, what should Phase 1 require? | Curated public artifacts only; Full exported run artifacts; Schema examples only | Full exported run artifacts |
| What should the top-level manifest guarantee? | Full provenance manifest; Light manifest; Folder manifests | Full provenance manifest |

**Notes:** The packet must be complete enough for a reviewer to inspect the full proof story, not just see schema examples.

---

## Claim Status Rules

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| What should qualify a claim as proven? | Artifact-backed only; Test-backed too; Maintainer-approved | Artifact-backed only |
| How should roadmap claims behave? | Visible but explicitly unproven; Hidden from main viewer; Shown as coming soon | Visible but explicitly unproven |
| How should disabled claims behave? | Visible safety stop; Hidden by default; Removed entirely | Visible safety stop |
| Should a claim be allowed to reference private/local evidence? | No private evidence; Allowed if redacted summary exists; Allowed for maintainer-only appendix | No private evidence |

**Notes:** Public claims must be honest by construction. Private/local-only support demotes the claim to `roadmap` or `disabled`.

---

## Synthetic Corpus Shape

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| What should the Phase 1 corpus be? | Multi-case synthetic corpus; Tiny canonical fixture; Richer stress sample | Multi-case synthetic corpus |
| What languages/reference shape should it include? | Arabic + English with reference units; English only; Arabic, English, and mixed OCR noise | Arabic + English with reference units |
| How much parser-quality failure should the corpus intentionally include? | Representative warnings; Mostly clean; Failure-heavy | Representative warnings |
| Should Phase 1 include real screenshots from the current Ragstudio UI? | Yes, but static approved screenshots only; No screenshots in Phase 1; Generated/mock screenshots | Yes, but static approved screenshots only |

**Notes:** The corpus should be small but meaningful, proving the multilingual/reference warning story without using restricted real corpus material.

---

## Public Safety Boundary

| Question | Options Presented | Selected |
|----------|-------------------|----------|
| What should redaction fail closed on? | Strict public-safety list; Secrets only; Manual review only | Strict public-safety list |
| Who/what can approve screenshot publication? | Manual signoff file; Commit approval only; Automated scan only | Manual signoff file |
| How should unapproved or unsafe artifacts appear in the packet? | Excluded with reason; Redacted placeholder; Private appendix | Excluded with reason |
| Should LAN/private host examples be allowed if they are fake? | Only reserved documentation examples; Allow fake-looking LAN IPs; No host/IP examples at all | Only reserved documentation examples |

**Notes:** Safety is part of the Phase 1 contract. Unsafe artifacts are excluded, and affected claims cannot be marked `proven`.

## the agent's Discretion

- Exact JSON Schema filenames, manifest field ordering, fixture filenames, and smallest sufficient exported-artifact set.

## Deferred Ideas

None.

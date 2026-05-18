# Semantic Page Boundary Stitching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join paragraph text that MinerU splits only because a sentence crosses a PDF page boundary.

**Architecture:** Keep the change inside `MinerUContentNormalizer` as a post-normalization pass. The pass only merges adjacent text-like blocks across consecutive pages when punctuation and casing indicate a sentence continuation, and it records `page_start` / `page_end` on the synthetic source item.

**Tech Stack:** Python 3.12, pytest, existing Ragstudio parser normalization services.

---

### Task 1: Regression Test

**Files:**
- Modify: `backend/tests/test_parser_normalization.py`

- [ ] **Step 1: Add a failing regression**

Add a test that normalizes two paragraph blocks on pages 1 and 2 where the first block does not end in terminal punctuation and the second block begins lowercase. Assert the normalizer returns one block with text joined by a space, `page` set to `1`, and source metadata containing `page_start: 1`, `page_end: 2`, and `semantic_stitch: "page_boundary"`.

- [ ] **Step 2: Run the focused test**

Run: `python -m pytest backend/tests/test_parser_normalization.py::test_semantic_page_boundary_stitches_continuation_paragraph -q`

Expected before implementation: FAIL because two separate blocks are returned.

### Task 2: Normalizer Stitch Pass

**Files:**
- Modify: `backend/src/ragstudio/services/parser_normalization.py`

- [ ] **Step 1: Add a post-normalization stitch pass**

After existing PDF text-layer gap recovery, call a helper that walks normalized blocks in order and merges only eligible consecutive page-boundary text blocks.

- [ ] **Step 2: Add conservative eligibility helpers**

Eligibility requires consecutive pages, text-like block types, no warnings or recovery, no obvious headings/list starts, previous text lacking terminal punctuation, and next text beginning like a sentence continuation.

- [ ] **Step 3: Preserve evidence metadata**

Merged blocks keep the first page for compatibility and add `page_start`, `page_end`, `stitched_block_types`, `stitched_pages`, and `semantic_stitch` to a synthetic source item.

### Task 3: Verification

**Files:**
- Test: `backend/tests/test_parser_normalization.py`

- [ ] **Step 1: Run the focused parser normalization test file**

Run: `python -m pytest backend/tests/test_parser_normalization.py -q`

- [ ] **Step 2: Run lint for touched files**

Run: `python -m ruff check backend/src/ragstudio/services/parser_normalization.py backend/tests/test_parser_normalization.py`

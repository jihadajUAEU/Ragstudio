# Hadith Visual Reference Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add visual reference-window assembly as a reusable canonical-assembly architecture capability, with Hadith/Bukhari as the first concrete resolver case.

**Architecture:** Keep the quality warning as a detector, not a suppression target. The fix belongs in canonical assembly: normalize parser blocks into layout-aware evidence windows, apply domain resolver policies to assign body blocks to reference anchors, and persist the decision/provenance so future multimodal and domain-specific resolvers can use the same mechanism. Hadith is the immediate implementation, but the abstractions must remain domain-neutral enough for Qur'an/tafseer, legal sections, page-line corpora, image/table recovery, and future RAG-Anything multimodal outputs.

**Tech Stack:** Python 3.12, pytest, existing `ChunkSplitter`, `CanonicalAssemblyStrategy`, `HadithResolver`, `EvidenceGraph`, and MinerU `source_content_list.json` fixtures.

---

## Architectural Direction

This is not a one-document patch. The architecture needs a stable stage between parser normalization and chunk materialization:

```text
MinerU / RAG-Anything blocks
  -> normalized evidence blocks with page, bbox, modality, scripts, warnings
  -> visual reference-window builder
  -> domain resolver policy
  -> canonical reference units
  -> quality gate
  -> vector/graph materialization
```

The visual reference-window builder is responsible for geometry and boundary facts:

- page order
- bbox order
- before/after candidate windows
- next primary anchor boundaries
- max page gap
- recovered text provenance
- modality and script evidence

Domain resolvers are responsible for domain semantics:

- what counts as a primary anchor
- which body scripts are required
- whether translations are optional or required
- how far continuation may carry
- when a candidate unit is answerable vs provenance-only

The warning system remains downstream validation. `reference_unit_missing_expected_script` should continue to flag incomplete assembled units. The fix is to assemble complete evidence-backed units before the warning fires.

## Root Cause Summary

The PDF page shows this visual order:

```text
Book 2, Hadith 12
Arabic body
English translation
Book 2, Hadith 13
Arabic body
English translation
Book 2, Hadith 14
...
```

The parsed artifacts contain the Arabic, but the final chunk for `book:2:hadith:12` only contains the recovered header and English translation. The current domain-aware hadith resolver misses this real page shape because it only handles isolated late-header cases:

```python
if len(header_blocks) != 1:
    return []
```

It also requires a single resolved unit to cover every text block in the graph. That is incompatible with dense pages containing multiple hadith references.

## Edge Cases To Cover Architecturally

- **Recovered header after body in parser order, before body in visual order:** `Book 2, Hadith 12` appears as a recovered header block late in `source_content_list.json`, but its bbox places it above the Arabic and English blocks.
- **Multiple hadiths on one page:** the resolver must process each header independently and stop at the next `Book N, Hadith N`.
- **Next-reference footer/header:** `Book 2, Hadith 15` may appear as a footer at the bottom of the previous page; it must not absorb Hadith 14 body text.
- **Cross-page continuation:** English or Arabic continuation can start on the next page and still belong to the previous hadith when it is before the next primary anchor and inside `max_page_gap`.
- **Previous-page dangling body:** body blocks before the first visible header on a page should not be assigned unless a trusted nearby recovered header or prior open reference proves the association.
- **Competing anchor inside candidate window:** if another `Book N, Hadith N` appears between a header and body candidate, stop instead of merging across hadiths.
- **Arabic-only or English-only partial units:** answerable chunks need Arabic for hadith domains; English-only chunks should still warn, not be silently accepted.
- **Recovered header provenance:** `recovered_text_from_disallowed_block` must remain as positive audit metadata on the assembled unit.
- **Non-hadith domains:** Qur'an/tafseer reference assembly tests must continue to pass unchanged.

## File Structure

- Modify `backend/tests/test_chunk_splitter.py`
  - Add regression tests for the Bukhari page layout and edge cases.
- Modify `backend/src/ragstudio/services/evidence_graph.py`
  - Add reusable visual-window helpers for page/bbox ordered traversal, primary-anchor windows, and boundary-safe body selection.
- Modify `backend/src/ragstudio/services/domain_resolvers/hadith.py`
  - Replace global single-header logic with per-header candidate resolution using the generic evidence-window helpers.
  - Keep Hadith-specific anchor/script policy in the resolver.
- Optionally create `backend/src/ragstudio/services/visual_reference_windows.py`
  - Use this if `evidence_graph.py` starts growing beyond simple graph traversal.
  - Own reusable `ReferenceWindow`, `WindowBoundary`, and candidate body selection primitives.
- Verify `backend/src/ragstudio/services/chunk_splitter.py`
  - No direct edit expected unless block ordering evidence shows the resolver receives non-visual order.

## Non-Goals

- Do not hard-code Bukhari page numbers, document IDs, chunk IDs, or source artifact names.
- Do not suppress `reference_unit_missing_expected_script`.
- Do not special-case `Book 2, Hadith 12` in production code.
- Do not make all recovered headers trusted body text.
- Do not merge across a competing primary anchor.
- Do not replace quality gates with resolver guesses.

## Architecture Acceptance Criteria

- Visual reference-window logic is reusable by at least one future resolver without copying Hadith-specific code.
- Hadith-specific code only defines anchor regex, script requirements, continuation policy, and answerable/provenance rules.
- Every assembled unit records provenance for anchor and body blocks.
- Every accepted recovery warning remains visible as audit evidence.
- Incomplete units still produce real quality warnings.
- Existing Qur'an/tafseer and generic chunking behavior remains unchanged.

## Task 1: Reproduce The Bukhari Page Failure

**Files:**
- Modify: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Add the failing regression test**

Add this test near `test_chunk_splitter_uses_layout_aware_hadith_strategy_for_late_header`:

```python
def test_chunk_splitter_reassociates_recovered_hadith_header_on_dense_visual_page(
    tmp_path: Path,
):
    arabic_12 = (
        "المسلم غنم يتبع بها شعف الجبال ومواقع القطر، "
        "يفر بدينه من الفتن"
    )
    english_12 = (
        "Narrated Abu Said Al-Khudri: Allah's Messenger (■) said, "
        "\"A time will soon come when the best property of a Muslim will be sheep.\""
    )
    arabic_13 = "حتى يعرف الغضب في وجهه ثم يقول إن أتقاكم وأعلمكم بالله أنا"
    english_13 = "Narrated 'Aisha: Whenever Allah's Messenger ordered the Muslims."

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": arabic_12,
                    "bbox": [101, 103, 906, 229],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_12,
                    "bbox": [89, 239, 900, 291],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": "Book 2, Hadith 13",
                    "bbox": [91, 309, 218, 324],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": arabic_13,
                    "bbox": [91, 334, 905, 496],
                    "page_idx": 14,
                },
                {
                    "type": "text",
                    "text": english_13,
                    "bbox": [89, 506, 803, 613],
                    "page_idx": 14,
                },
                {
                    "type": "header",
                    "recovered_text": "Book 2, Hadith 12",
                    "bbox": [93, 75, 217, 89],
                    "page_idx": 14,
                },
                {
                    "type": "footer",
                    "recovered_text": "Book 2, Hadith 14",
                    "bbox": [93, 901, 217, 915],
                    "page_idx": 14,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
                "chunk_index": 0,
            }
        },
    )
    metadata = DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "max_page_gap": 1,
            },
            "provenance": {
                "preserve_original_blocks": True,
                "store_text_hash": True,
            },
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=metadata,
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    hadith_12 = by_ref["book:2:hadith:12"]
    assert "Book 2, Hadith 12" in hadith_12.text
    assert arabic_12 in hadith_12.text
    assert english_12 in hadith_12.text
    assert "Book 2, Hadith 13" not in hadith_12.text
    assert hadith_12.metadata["canonical_reference_unit"]["assembly_strategy"] == (
        "domain_evidence_graph"
    )
    assert "reference_unit_missing_expected_script" not in parser_warning_codes(hadith_12)
    assert "recovered_text_from_disallowed_block" in parser_warning_codes(hadith_12)
```

- [ ] **Step 2: Run the test to verify the current failure**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_reassociates_recovered_hadith_header_on_dense_visual_page -q
```

Expected: FAIL. The failure should show that `book:2:hadith:12` is missing `arabic_12` or still has `reference_unit_missing_expected_script`.

- [ ] **Step 3: Commit the failing test only if following red-green commits**

```powershell
git add backend/tests/test_chunk_splitter.py
git commit -m "test: reproduce dense hadith page assembly gap"
```

## Task 2: Make HadithResolver Resolve Per Header Candidate

**Files:**
- Modify: `backend/src/ragstudio/services/domain_resolvers/hadith.py`

- [ ] **Step 1: Remove global single-header exit**

Replace this:

```python
if len(header_blocks) != 1:
    return []
```

with per-candidate processing:

```python
if not header_blocks:
    return []
```

Keep iterating over `header_blocks`.

- [ ] **Step 2: Replace global coverage check with local boundary check**

Delete the call:

```python
if not self._covers_all_text_blocks(graph, header=block, body_blocks=body_blocks):
    continue
```

Add this local safety check:

```python
if self._has_competing_anchor_between(graph, header=block, body_blocks=body_blocks):
    continue
```

Add this method:

```python
def _has_competing_anchor_between(
    self,
    graph: EvidenceGraph,
    *,
    header: EvidenceBlockView,
    body_blocks: list[EvidenceBlockView],
) -> bool:
    header_index = graph.index_of(header)
    body_indices = [graph.index_of(block) for block in body_blocks]
    concrete_indices = [index for index in body_indices if index is not None]
    if header_index is None or not concrete_indices:
        return True
    start = min(header_index, *concrete_indices)
    end = max(header_index, *concrete_indices)
    for candidate in graph.blocks[start + 1 : end]:
        if candidate.source_ref.key == header.source_ref.key:
            continue
        if any(candidate.source_ref.key == block.source_ref.key for block in body_blocks):
            continue
        if HADITH_HEADER_RE.search(candidate.text):
            return True
    return False
```

- [ ] **Step 3: Run the Bukhari regression**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_reassociates_recovered_hadith_header_on_dense_visual_page -q
```

Expected: if this alone is enough, PASS. If it still fails because body selection only looks before the header in parser order, continue to Task 3.

## Task 3: Introduce Reusable Visual Reference Windows

**Files:**
- Modify: `backend/src/ragstudio/services/evidence_graph.py`
- Optionally create: `backend/src/ragstudio/services/visual_reference_windows.py`
- Modify: `backend/src/ragstudio/services/domain_resolvers/hadith.py`

- [ ] **Step 1: Add a reusable reference-window primitive**

Prefer adding this to `backend/src/ragstudio/services/evidence_graph.py` first. If the file becomes too broad, move the dataclass and helper into `visual_reference_windows.py`.

```python
from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class ReferenceWindow:
    anchor: EvidenceBlockView
    body_blocks: tuple[EvidenceBlockView, ...]
    next_anchor: EvidenceBlockView | None = None
    previous_anchor: EvidenceBlockView | None = None
```

Add a generic window method:

```python
def visual_window_after_anchor(
    self,
    anchor: EvidenceBlockView,
    *,
    is_anchor: Callable[[EvidenceBlockView], bool],
    accepts_body: Callable[[EvidenceBlockView], bool],
    max_page_gap: int | None,
) -> ReferenceWindow:
    anchor_index = self.index_of(anchor)
    if anchor_index is None:
        return ReferenceWindow(anchor=anchor, body_blocks=())

    body_blocks: list[EvidenceBlockView] = []
    next_anchor: EvidenceBlockView | None = None
    for candidate in self.blocks[anchor_index + 1 :]:
        if not candidate.has_text:
            continue
        if is_anchor(candidate):
            next_anchor = candidate
            break
        if not self._within_page_gap(anchor, candidate, max_page_gap=max_page_gap):
            break
        if accepts_body(candidate):
            body_blocks.append(candidate)
    previous_anchor = next(
        (
            candidate
            for candidate in reversed(self.blocks[:anchor_index])
            if candidate.has_text and is_anchor(candidate)
        ),
        None,
    )
    return ReferenceWindow(
        anchor=anchor,
        body_blocks=tuple(body_blocks),
        next_anchor=next_anchor,
        previous_anchor=previous_anchor,
    )
```

Add a graph-level page-gap helper:

```python
def _within_page_gap(
    self,
    anchor: EvidenceBlockView,
    candidate: EvidenceBlockView,
    *,
    max_page_gap: int | None,
) -> bool:
    if max_page_gap is None:
        return True
    anchor_page = anchor.page_start
    candidate_page = candidate.page_end if candidate.page_end is not None else candidate.page_start
    if anchor_page is None or candidate_page is None:
        return True
    return candidate_page - anchor_page <= max_page_gap
```

This primitive is intentionally domain-neutral: it knows geometry and boundaries, not hadith semantics.

- [ ] **Step 2: Replace previous-only Hadith neighborhood selection**

Replace `_prior_unambiguous_body_blocks` with `_visual_body_blocks_for_header`.

Use this method:

```python
def _visual_body_blocks_for_header(
    self,
    graph: EvidenceGraph,
    header: EvidenceBlockView,
    *,
    context: ResolverContext,
) -> list[EvidenceBlockView]:
    window = graph.visual_window_after_anchor(
        header,
        is_anchor=self._is_primary_anchor,
        accepts_body=self._is_answerable_body_block,
        max_page_gap=context.max_page_gap,
    )
    if window.body_blocks:
        return list(window.body_blocks)

    # Fallback for parser order that still places recovered headers after body.
    candidates = graph.neighborhood(header, before=3, after=0)
    if any(self._is_primary_anchor(candidate) for candidate in candidates):
        return []
    selected = [
        candidate
        for candidate in candidates
        if self._is_answerable_body_block(candidate)
    ]
    if not self._within_page_gap(selected, header, max_page_gap=context.max_page_gap):
        return []
    return selected
```

Then update `resolve_units`:

```python
body_blocks = self._visual_body_blocks_for_header(graph, block, context=context)
```

- [ ] **Step 2: Preserve header-first text output**

Keep `_unit_from_blocks` building:

```python
blocks = [header, *body_blocks]
```

This ensures final text starts with `Book N, Hadith N`, followed by Arabic and English body.

- [ ] **Step 4: Ensure the generic primitive can be reused**

Add a small direct unit test in `backend/tests/test_chunk_splitter.py` only if no dedicated evidence graph tests exist. The test can instantiate the chunk splitter path rather than importing the graph directly, but it must prove this architectural behavior:

```python
def test_hadith_visual_windows_stop_at_next_anchor_without_document_specific_ids(
    tmp_path: Path,
):
    arabic = "قال رسول الله صلى الله عليه وسلم"
    next_arabic = "قال الصحابي في الحديث التالي"
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Book 10, Hadith 1", "bbox": [91, 80, 220, 96], "page_idx": 1},
                {"type": "text", "text": arabic, "bbox": [91, 110, 906, 170], "page_idx": 1},
                {"type": "text", "text": "Book 10, Hadith 2", "bbox": [91, 190, 220, 206], "page_idx": 1},
                {"type": "text", "text": next_arabic, "bbox": [91, 220, 906, 280], "page_idx": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic in by_ref["book:10:hadith:1"].text
    assert next_arabic not in by_ref["book:10:hadith:1"].text
    assert next_arabic in by_ref["book:10:hadith:2"].text
```

- [ ] **Step 5: Run the focused regression**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_reassociates_recovered_hadith_header_on_dense_visual_page -q
```

Expected: PASS.

- [ ] **Step 6: Run existing late-header test**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py::test_chunk_splitter_uses_layout_aware_hadith_strategy_for_late_header -q
```

Expected: PASS.

## Task 4: Implement Edge-Case Boundary Rules And Regression Tests

**Files:**
- Modify: `backend/src/ragstudio/services/domain_resolvers/hadith.py`
- Modify: `backend/tests/test_chunk_splitter.py`

- [ ] **Step 1: Add explicit boundary classification helpers**

In `backend/src/ragstudio/services/domain_resolvers/hadith.py`, add helpers so every edge case has one domain-policy point:

```python
def _is_primary_anchor(self, block: EvidenceBlockView) -> bool:
    return bool(block.has_text and HADITH_HEADER_RE.search(block.text))


def _is_recovered_anchor(self, block: EvidenceBlockView) -> bool:
    if not self._is_primary_anchor(block):
        return False
    return block.block_type in {"header", "footer", "page_footnote", "page_header"}


def _is_answerable_body_block(self, block: EvidenceBlockView) -> bool:
    return block.has_text and ("arabic" in block.scripts or "latin" in block.scripts)
```

Then use `_is_primary_anchor(...)` instead of direct `HADITH_HEADER_RE.search(...)` checks inside body-window logic. Keep these helpers in the resolver, not the graph/window primitive, because anchor recognition is domain-specific.

- [ ] **Step 2: Make next-reference footer/header a hard boundary**

In `_visual_body_blocks_for_header`, stop when any later candidate is a primary anchor:

```python
for candidate in graph.blocks[header_index + 1 :]:
    if not candidate.has_text:
        continue
    if self._is_primary_anchor(candidate):
        break
    if not self._within_page_gap([candidate], header, max_page_gap=context.max_page_gap):
        break
    if self._is_answerable_body_block(candidate):
        selected.append(candidate)
```

This fixes the footer edge case where `Book 2, Hadith 15` appears at the bottom of the previous page. It must become its own reference/provenance boundary and must not be absorbed into Hadith 14.

- [ ] **Step 3: Preserve recovered header provenance without trusting it as body**

In `_unit_from_blocks`, keep the header as the first output block but make sure recovered header warnings remain merged:

```python
blocks = [header, *body_blocks]
parser_warnings = self._block_warnings(blocks)
```

Expected behavior:
- `recovered_text_from_disallowed_block` stays attached to the canonical unit.
- The recovered header is marked as `reference_header` in provenance.
- It is not treated as Arabic/English body evidence.

- [ ] **Step 4: Keep English-only visual units warning**

Do not allow `_visual_body_blocks_for_header` to mark a unit valid just because it found Latin text. In `resolve_units`, keep this guard:

```python
if not body_blocks or not any("arabic" in item.scripts for item in body_blocks):
    continue
```

If the resolver returns no domain-evidence unit for an English-only body, fallback quality gating should still produce `reference_unit_missing_expected_script`. This prevents the edge-case fix from hiding genuine missing-Arabic warnings.

- [ ] **Step 5: Keep cross-page continuation inside max_page_gap**

In `_within_page_gap`, preserve existing `max_page_gap` behavior. The visual body window may include blocks from the next page only when:

```python
block_page - header_page <= max_page_gap
```

Expected behavior:
- continuation text before the next anchor can be included across a page boundary
- once the next `Book N, Hadith N+1` appears, collection stops
- blocks beyond `max_page_gap` are not attached

- [ ] **Step 6: Add test for next-reference footer not absorbing current body**

Add:

```python
def test_chunk_splitter_keeps_next_hadith_footer_as_provenance_boundary(
    tmp_path: Path,
):
    arabic_14 = "ومن يكره أن يعود في الكفر بعد إذ أنقذه الله"
    english_14 = "Narrated Anas: The Prophet said whoever possesses three qualities."
    arabic_15 = "صفراء ملتوية قال وهيب حدثنا عمرو"

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Book 2, Hadith 14", "bbox": [91, 631, 218, 645], "page_idx": 14},
                {"type": "text", "text": arabic_14, "bbox": [99, 655, 905, 784], "page_idx": 14},
                {"type": "text", "text": english_14, "bbox": [89, 795, 905, 866], "page_idx": 14},
                {"type": "footer", "recovered_text": "Book 2, Hadith 15", "bbox": [93, 901, 217, 915], "page_idx": 14},
                {"type": "text", "text": arabic_15, "bbox": [96, 75, 906, 299], "page_idx": 15},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_14 in by_ref["book:2:hadith:14"].text
    assert arabic_15 not in by_ref["book:2:hadith:14"].text
    assert by_ref["book:2:hadith:15"].content_type in {"text", "reference_provenance"}
```

- [ ] **Step 7: Add helper metadata factory**

If no existing helper is close enough, add this near the hadith tests:

```python
def bukhari_hadith_metadata() -> DomainMetadata:
    return DomainMetadata(
        domain="hadith",
        document_type="collection",
        tags=["hadith", "arabic", "english"],
        script="arabic",
        custom_json={
            "reference_schema": {
                "type": "book_hadith",
                "canonical_ref_template": "book:{book}:hadith:{hadith}",
            },
            "chunking": {"unit": "hadith", "preserve_parallel_text": True},
            "reference_resolution": {
                "enabled": True,
                "build_canonical_units": True,
                "carry_forward_body_blocks": True,
                "header_only_policy": "provenance_only",
                "continuation_policy": "until_next_reference",
                "max_page_gap": 1,
            },
            "provenance": {
                "preserve_original_blocks": True,
                "store_text_hash": True,
            },
        },
    )
```

Use this helper in the new tests and optionally in the existing late-header tests.

- [ ] **Step 8: Add test for English-only body still warning**

Add:

```python
def test_chunk_splitter_keeps_missing_arabic_warning_when_visual_unit_has_no_arabic(
    tmp_path: Path,
):
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Book 2, Hadith 20", "bbox": [91, 100, 218, 116], "page_idx": 20},
                {
                    "type": "text",
                    "text": "Narrated Abu Huraira: English translation only.",
                    "bbox": [91, 130, 900, 160],
                    "page_idx": 20,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    assert "reference_unit_missing_expected_script" in parser_warning_codes(split[0])
```

- [ ] **Step 9: Add test for cross-page continuation before next anchor**

Add:

```python
def test_chunk_splitter_keeps_hadith_body_across_page_until_next_anchor(
    tmp_path: Path,
):
    arabic = "قال رسول الله صلى الله عليه وسلم"
    english_page_two = "The translation continues on the next page before a new hadith."
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "text", "text": "Book 3, Hadith 4", "bbox": [91, 880, 218, 896], "page_idx": 30},
                {"type": "text", "text": arabic, "bbox": [91, 904, 906, 940], "page_idx": 30},
                {"type": "text", "text": english_page_two, "bbox": [91, 74, 900, 120], "page_idx": 31},
                {"type": "text", "text": "Book 3, Hadith 5", "bbox": [91, 140, 218, 156], "page_idx": 31},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic in by_ref["book:3:hadith:4"].text
    assert english_page_two in by_ref["book:3:hadith:4"].text
    assert "Book 3, Hadith 5" not in by_ref["book:3:hadith:4"].text
```

- [ ] **Step 10: Add test for competing recovered header inside the candidate window**

Add:

```python
def test_chunk_splitter_stops_hadith_body_at_competing_recovered_anchor(
    tmp_path: Path,
):
    arabic_20 = "قال رسول الله صلى الله عليه وسلم في الحديث الأول"
    english_20 = "Narrated first companion: first translation."
    arabic_21 = "قال رسول الله صلى الله عليه وسلم في الحديث الثاني"

    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {"type": "header", "recovered_text": "Book 5, Hadith 20", "bbox": [91, 80, 220, 96], "page_idx": 50},
                {"type": "text", "text": arabic_20, "bbox": [91, 110, 906, 170], "page_idx": 50},
                {"type": "text", "text": english_20, "bbox": [91, 180, 906, 230], "page_idx": 50},
                {"type": "header", "recovered_text": "Book 5, Hadith 21", "bbox": [91, 240, 220, 256], "page_idx": 50},
                {"type": "text", "text": arabic_21, "bbox": [91, 270, 906, 330], "page_idx": 50},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk = AdapterChunk(
        text="fallback markdown should not be used",
        source_location={"artifact": "source/auto/source.md"},
        metadata={
            "parser_metadata": {
                "backend": "mineru",
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            }
        },
    )

    split = ChunkSplitter(max_words=1500).split(
        [chunk],
        domain_metadata=bukhari_hadith_metadata(),
        parser_mode="mineru_strict",
    )

    by_ref = {piece.preview_ref: piece for piece in split if piece.preview_ref}
    assert arabic_20 in by_ref["book:5:hadith:20"].text
    assert arabic_21 not in by_ref["book:5:hadith:20"].text
    assert arabic_21 in by_ref["book:5:hadith:21"].text
```

- [ ] **Step 11: Run the edge-case test set**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py -q -k "hadith and (dense_visual_page or footer_as_provenance_boundary or no_arabic or cross_page or competing_recovered_anchor)"
```

Expected: all selected tests PASS.

## Task 5: Run Existing Regression Suite Around Chunking

**Files:**
- Verify: `backend/tests/test_chunk_splitter.py`
- Verify: `backend/tests/test_chunk_quality_gate.py`
- Verify: `backend/tests/test_chunk_service_arabic_search.py`

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
pytest backend/tests/test_chunk_splitter.py backend/tests/test_chunk_quality_gate.py backend/tests/test_chunk_service_arabic_search.py -q
```

Expected: PASS.

- [ ] **Step 2: Compile touched backend files**

Run:

```powershell
python -m py_compile backend/src/ragstudio/services/domain_resolvers/hadith.py backend/src/ragstudio/services/evidence_graph.py backend/src/ragstudio/services/chunk_splitter.py
```

Expected: no output.

- [ ] **Step 3: Commit backend fix**

```powershell
git add backend/src/ragstudio/services/domain_resolvers/hadith.py backend/src/ragstudio/services/evidence_graph.py backend/tests/test_chunk_splitter.py
git commit -m "fix: assemble dense hadith pages by visual reference windows"
```

If `evidence_graph.py` was not changed, omit it from `git add`.

## Task 6: Verify Against Real Bukhari Data

**Files:**
- Verify runtime data only; no source edits expected.

- [ ] **Step 1: Re-index Bukhari**

Use the UI re-index action for `hadith_bukhari.pdf` or call the existing reindex endpoint with the prior job options.

Expected: job succeeds.

- [ ] **Step 2: Inspect Hadith 12 chunk**

Run:

```powershell
docker exec ragstudio-postgres psql -U ragstudio -d ragstudio -t -A -F "|" -c "select id, left(text, 1200), metadata_json->'canonical_reference_unit'->>'assembly_strategy', metadata_json->'canonical_reference_unit'->>'body_status', metadata_json->'extraction_quality' from chunks where document_id='a389808a-b340-4e05-bcf4-1ca001c82c5f' and metadata_json->'reference_metadata'->'references' ? 'book:2:hadith:12';"
```

Expected:
- text contains `Book 2, Hadith 12`
- text contains Arabic such as `المسلم غنم`
- text contains English translation
- assembly strategy is `domain_evidence_graph` or another explicitly visual/domain-aware strategy
- no counted `reference_unit_missing_expected_script` for this chunk

- [ ] **Step 3: Compare warning counts**

Run:

```powershell
docker exec ragstudio-postgres psql -U ragstudio -d ragstudio -t -A -F "|" -c "select id,status,progress,coalesce((result->'parser_quality'->'warning_counts')::text,'{}'),coalesce((result->'parser_quality'->>'affected_chunks'),'') from jobs j join documents d on d.id=j.target_id where d.filename='hadith_bukhari.pdf' and j.type='index_document' order by j.created_at desc limit 3;"
```

Expected:
- latest job succeeded
- warning count decreases for cases fixed by visual assembly
- remaining warnings still correspond to chunks where Arabic is genuinely absent from the assembled unit

- [ ] **Step 4: Spot-check neighboring hadiths**

Inspect `book:2:hadith:11`, `book:2:hadith:12`, `book:2:hadith:13`, `book:2:hadith:14`, and `book:2:hadith:15`.

Expected:
- no chunk contains another hadith's header/body
- each answerable chunk has one canonical reference
- recovered header warnings remain positive audit rows

## Self-Review

Spec coverage:
- The PDF-page case is covered by Task 1.
- Other edge cases are covered by Task 4.
- Real Bukhari runtime verification is covered by Task 6.

Placeholder scan:
- No `TBD`, `TODO`, "similar to", or undefined implementation placeholders remain.

Type consistency:
- New helper names are consistent: `_visual_body_blocks_for_header`, `_has_competing_anchor_between`, and `bukhari_hadith_metadata`.

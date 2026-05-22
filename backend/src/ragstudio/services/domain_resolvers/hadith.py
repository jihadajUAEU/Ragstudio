from __future__ import annotations

import hashlib
import re

from ragstudio.services.canonical_assembly import EvidenceBlockView
from ragstudio.services.domain_resolvers.base import (
    AssemblyDecision,
    CanonicalUnit,
    ResolverContext,
)
from ragstudio.services.evidence_graph import EvidenceGraph

HADITH_HEADER_RE = re.compile(
    r"\bBook\s+(?P<book>\d{1,4})\s*,?\s*Hadith\s+(?P<hadith>\d{1,6})\b",
    re.IGNORECASE,
)


class HadithResolver:
    def can_resolve(self, context: ResolverContext) -> bool:
        if (context.domain_metadata.domain or "").strip().casefold() != "hadith":
            return False
        semantics = context.reference_semantics
        if semantics is None:
            return True
        return semantics.reference_type in {"book_hadith", "hadith"} and (
            semantics.chunk_unit in {"hadith", "section", "verse"}
        )

    def resolve_units(
        self,
        graph: EvidenceGraph,
        *,
        context: ResolverContext,
    ) -> list[CanonicalUnit]:
        if not self.can_resolve(context):
            return []

        header_blocks = [
            block
            for block in graph.blocks
            if self._is_primary_anchor(block, context=context)
        ]
        if not header_blocks:
            return []
        if not any(self._is_late_header(block) for block in header_blocks):
            return []

        units: list[CanonicalUnit] = []
        used_body_refs: set[str] = set()
        for block in header_blocks:
            match = HADITH_HEADER_RE.search(block.text)
            if match is None:
                continue
            body_blocks = [
                body
                for body in self._visual_body_blocks_for_header(graph, block, context=context)
                if body.source_ref.key not in used_body_refs
            ]
            if not body_blocks:
                units.append(
                    self._header_only_unit(
                        header=block,
                        match=match,
                        context=context,
                        reason=(
                            "Reference anchor did not have Arabic body evidence in the "
                            "visual window."
                        ),
                    )
                )
                continue
            if not any("arabic" in item.scripts for item in body_blocks):
                units.append(
                    self._unit_from_blocks(
                        header=block,
                        body_blocks=body_blocks,
                        match=match,
                        context=context,
                        answerable=True,
                        body_status=(
                            "assembled" if len(body_blocks) > 1 else "single_block"
                        ),
                        decision_code="reference_anchor_retained_missing_required_script",
                        decision_reason=(
                            "Reference anchor and body were retained so quality gates "
                            "can report the missing expected script."
                        ),
                    )
                )
                used_body_refs.update(body.source_ref.key for body in body_blocks)
                continue
            if self._has_competing_anchor_between(graph, header=block, body_blocks=body_blocks):
                units.append(
                    self._header_only_unit(
                        header=block,
                        match=match,
                        context=context,
                        reason=(
                            "Reference anchor was separated from candidate body by a "
                            "competing anchor."
                        ),
                    )
                )
                continue
            units.append(
                self._unit_from_blocks(
                    header=block,
                    body_blocks=body_blocks,
                    match=match,
                    context=context,
                )
            )
            used_body_refs.update(body.source_ref.key for body in body_blocks)
        return units

    def _is_primary_anchor(
        self,
        block: EvidenceBlockView,
        *,
        context: ResolverContext | None = None,
    ) -> bool:
        if not block.has_text:
            return False
        text = block.text.strip()
        pattern = HADITH_HEADER_RE
        if (
            context
            and context.reference_semantics
            and context.reference_semantics.primary_anchor_pattern
        ):
            try:
                pattern = re.compile(
                    context.reference_semantics.primary_anchor_pattern,
                    re.IGNORECASE,
                )
            except re.error:
                pattern = HADITH_HEADER_RE
        match = pattern.search(text)
        if match is None or match.start() != 0:
            return False
        remainder = text[match.end() :].strip()
        return not remainder or remainder[0] in {":", "-", "\u2013", "\u2014"}

    def _is_late_header(self, block: EvidenceBlockView) -> bool:
        return block.block_type in {"header", "footer", "page_footnote", "page_header"}

    def _is_answerable_body_block(self, block: EvidenceBlockView) -> bool:
        return block.has_text and ("arabic" in block.scripts or "latin" in block.scripts)

    def _visual_body_blocks_for_header(
        self,
        graph: EvidenceGraph,
        header: EvidenceBlockView,
        *,
        context: ResolverContext,
    ) -> list[EvidenceBlockView]:
        window = graph.visual_window_after_anchor(
            header,
            is_anchor=lambda block: self._is_primary_anchor(block, context=context),
            accepts_body=self._is_answerable_body_block,
            max_page_gap=context.max_page_gap,
        )
        if window.body_blocks:
            return list(window.body_blocks)

        if not self._is_late_header(header):
            return []
        reverse_window = graph.visual_window_before_anchor(
            header,
            is_anchor=lambda block: self._is_primary_anchor(block, context=context),
            accepts_body=self._is_answerable_body_block,
            max_page_gap=context.max_page_gap,
        )
        return list(reverse_window.body_blocks)

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
        body_refs = {block.source_ref.key for block in body_blocks}
        for candidate in graph.blocks[start + 1 : end]:
            if candidate.source_ref.key == header.source_ref.key:
                continue
            if candidate.source_ref.key in body_refs:
                continue
            if self._is_primary_anchor(candidate):
                return True
        return False

    def _within_page_gap(
        self,
        body_blocks: list[EvidenceBlockView],
        header: EvidenceBlockView,
        *,
        max_page_gap: int | None,
    ) -> bool:
        if max_page_gap is None:
            return True
        header_page = header.page_start
        if header_page is None:
            return True
        for block in body_blocks:
            block_page = block.page_end if block.page_end is not None else block.page_start
            if block_page is None:
                continue
            if abs(header_page - block_page) > max_page_gap:
                return False
        return True

    def _header_only_unit(
        self,
        *,
        header: EvidenceBlockView,
        match: re.Match[str],
        context: ResolverContext,
        reason: str,
    ) -> CanonicalUnit:
        return self._unit_from_blocks(
            header=header,
            body_blocks=[],
            match=match,
            context=context,
            answerable=False,
            body_status="header_only",
            decision_code="reference_anchor_retained_without_body",
            decision_reason=reason,
        )

    def _unit_from_blocks(
        self,
        *,
        header: EvidenceBlockView,
        body_blocks: list[EvidenceBlockView],
        match: re.Match[str],
        context: ResolverContext,
        answerable: bool = True,
        body_status: str = "assembled",
        decision_code: str = "late_header_body_reassociated",
        decision_reason: str = (
            "Reference header appeared after nearby body blocks in parser order."
        ),
    ) -> CanonicalUnit:
        book = int(match.group("book"))
        hadith = int(match.group("hadith"))
        reference = f"book:{book}:hadith:{hadith}"
        blocks = [header, *body_blocks]
        text = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())
        source_location = dict(context.parent_source_location)
        page_starts = [block.page_start for block in blocks if block.page_start is not None]
        page_ends = [block.page_end for block in blocks if block.page_end is not None]
        if page_starts:
            source_location["page_start"] = min(page_starts)
        if page_ends:
            source_location["page_end"] = max(page_ends)

        source_block_refs = tuple(block.source_ref.key for block in blocks)
        decision = AssemblyDecision(
            code=decision_code,
            reason=decision_reason,
            source_block_refs=source_block_refs,
            confidence="medium",
        )
        metadata = dict(context.parent_metadata)
        metadata["reference_metadata"] = {
            "reference_type": "book_hadith",
            "references": [reference],
            "book_start": book,
            "book_end": book,
            "hadith_start": hadith,
            "hadith_end": hadith,
            **{
                key: value
                for key, value in source_location.items()
                if key.startswith("page_")
            },
        }
        metadata["canonical_reference_unit"] = {
            "reference": reference,
            "raw_reference": match.group(0),
            "unit": "hadith",
            "answerable": answerable,
            "body_status": body_status,
            "assembly_strategy": "domain_evidence_graph",
        }
        metadata["orchestration"] = {
            "resolver": "hadith",
            "decisions": [
                {
                    "code": decision.code,
                    "reason": decision.reason,
                    "source_block_refs": list(decision.source_block_refs),
                    "confidence": decision.confidence,
                }
            ],
        }
        parser_warnings = self._block_warnings(blocks)
        if parser_warnings:
            extraction_quality = dict(metadata.get("extraction_quality") or {})
            existing_warnings = extraction_quality.get("parser_warnings")
            merged_warnings = [
                warning
                for warning in existing_warnings
                if isinstance(warning, dict)
            ] if isinstance(existing_warnings, list) else []
            seen = {
                (
                    warning.get("code"),
                    warning.get("block_type"),
                    warning.get("page"),
                    warning.get("message"),
                )
                for warning in merged_warnings
            }
            for warning in parser_warnings:
                key = (
                    warning.get("code"),
                    warning.get("block_type"),
                    warning.get("page"),
                    warning.get("message"),
                )
                if key in seen:
                    continue
                seen.add(key)
                merged_warnings.append(warning)
            extraction_quality["parser_warnings"] = merged_warnings
            metadata["extraction_quality"] = extraction_quality
        if context.preserve_original_blocks:
            metadata["provenance"] = {
                "source": "mineru_content_list",
                "blocks": [
                    self._provenance_block(header, role="reference_header", context=context),
                    *[
                        self._provenance_block(
                            block,
                            role="reference_body" if index == 0 else "reference_continuation",
                            context=context,
                        )
                        for index, block in enumerate(body_blocks)
                    ],
                ],
            }
        return CanonicalUnit(
            text=text,
            source_location=source_location,
            metadata=metadata,
            runtime_source_id=context.runtime_source_id,
            content_type=(
                "reference_provenance"
                if not answerable
                and context.reference_semantics
                and context.reference_semantics.header_only_policy == "provenance_only"
                else context.content_type
            ),
            preview_ref=reference,
            decisions=(decision,),
        )

    def _block_warnings(self, blocks: list[EvidenceBlockView]) -> list[dict[str, object]]:
        warnings: list[dict[str, object]] = []
        seen: set[tuple[object, object, object, object]] = set()
        for block in blocks:
            for warning in block.parser_warnings:
                key = (
                    warning.get("code"),
                    warning.get("block_type"),
                    warning.get("page"),
                    warning.get("message"),
                )
                if key in seen:
                    continue
                seen.add(key)
                warnings.append(dict(warning))
        return warnings

    def _provenance_block(
        self,
        block: EvidenceBlockView,
        *,
        role: str,
        context: ResolverContext,
    ) -> dict[str, object]:
        preview_chars = max(0, context.block_preview_chars)
        text = block.text.strip()
        item: dict[str, object] = {
            "role": role,
            "block_type": block.block_type,
            "page_start": block.page_start,
            "page_end": block.page_end,
            "source_block_ref": block.source_ref.key,
            "text_preview": text[:preview_chars] if preview_chars else "",
        }
        if context.store_text_hash and text:
            item["text_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if block.parser_warnings:
            item["warning_codes"] = [
                warning["code"]
                for warning in block.parser_warnings
                if isinstance(warning.get("code"), str)
            ]
        return {key: value for key, value in item.items() if value not in (None, [], "")}

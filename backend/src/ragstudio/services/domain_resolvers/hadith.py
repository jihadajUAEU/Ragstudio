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
        return (context.domain_metadata.domain or "").strip().casefold() == "hadith"

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
            if block.has_text and HADITH_HEADER_RE.search(block.text)
        ]
        if len(header_blocks) != 1:
            return []

        units: list[CanonicalUnit] = []
        for block in header_blocks:
            match = HADITH_HEADER_RE.search(block.text)
            if match is None or not self._is_late_header(block):
                continue
            body_blocks = self._prior_unambiguous_body_blocks(graph, block, context=context)
            if not body_blocks or not any("arabic" in item.scripts for item in body_blocks):
                continue
            if not self._covers_all_text_blocks(graph, header=block, body_blocks=body_blocks):
                continue
            units.append(
                self._unit_from_blocks(
                    header=block,
                    body_blocks=body_blocks,
                    match=match,
                    context=context,
                )
            )
        return units

    def _is_late_header(self, block: EvidenceBlockView) -> bool:
        return block.block_type in {"header", "footer", "page_footnote", "page_header"}

    def _prior_unambiguous_body_blocks(
        self,
        graph: EvidenceGraph,
        header: EvidenceBlockView,
        *,
        context: ResolverContext,
    ) -> list[EvidenceBlockView]:
        candidates = graph.neighborhood(header, before=3, after=0)
        if any(HADITH_HEADER_RE.search(candidate.text) for candidate in candidates):
            return []
        selected = [
            candidate
            for candidate in candidates
            if candidate.has_text and ("arabic" in candidate.scripts or "latin" in candidate.scripts)
        ]
        if not self._within_page_gap(selected, header, max_page_gap=context.max_page_gap):
            return []
        return selected

    def _covers_all_text_blocks(
        self,
        graph: EvidenceGraph,
        *,
        header: EvidenceBlockView,
        body_blocks: list[EvidenceBlockView],
    ) -> bool:
        handled_refs = {header.source_ref.key, *(block.source_ref.key for block in body_blocks)}
        text_refs = {block.source_ref.key for block in graph.blocks if block.has_text}
        return handled_refs == text_refs

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
            if header_page - block_page > max_page_gap:
                return False
        return True

    def _unit_from_blocks(
        self,
        *,
        header: EvidenceBlockView,
        body_blocks: list[EvidenceBlockView],
        match: re.Match[str],
        context: ResolverContext,
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
            code="late_header_body_reassociated",
            reason="Reference header appeared after nearby body blocks in parser order.",
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
            "answerable": True,
            "body_status": "assembled",
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
            content_type=context.content_type,
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

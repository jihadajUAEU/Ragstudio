from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from ragstudio.services.reference_metadata import ReferenceSemantics


@dataclass(frozen=True)
class ReferenceSourceBlock:
    text: str
    page_start: int | None = None
    page_end: int | None = None
    block_type: str | None = None
    parser_warning_codes: tuple[str, ...] = ()
    parser_warnings: tuple[dict[str, Any], ...] = ()
    role: str = "body"
    source_block_ref: str | None = None


@dataclass(frozen=True)
class AssembledReferenceUnit:
    text: str
    source_location: dict[str, Any]
    metadata: dict[str, Any]
    runtime_source_id: str | None
    content_type: str
    preview_ref: str | None


@dataclass
class _OpenReferenceUnit:
    reference: dict[str, int | str]
    blocks: list[ReferenceSourceBlock]
    body_blocks: list[ReferenceSourceBlock]


class ReferenceUnitAssembler:
    def assemble(
        self,
        blocks: list[ReferenceSourceBlock],
        *,
        semantics: ReferenceSemantics,
        parent_metadata: dict[str, Any],
        parent_source_location: dict[str, Any],
        runtime_source_id: str | None,
        content_type: str,
        preview_ref: str | None,
    ) -> list[AssembledReferenceUnit]:
        if not semantics.canonical_units_enabled:
            return []

        units: list[AssembledReferenceUnit] = []
        current: _OpenReferenceUnit | None = None
        for block in self._expand_multi_reference_blocks(blocks, semantics):
            text = block.text.strip()
            references = semantics.extract_chunk_references(text) if text else []
            if references:
                if current is not None:
                    units.append(
                        self._finish_unit(
                            current,
                            semantics=semantics,
                            parent_metadata=parent_metadata,
                            parent_source_location=parent_source_location,
                            runtime_source_id=runtime_source_id,
                            content_type=content_type,
                            preview_ref=preview_ref,
                        )
                    )
                reference = references[0]
                is_header_only = self._is_header_only_reference(text, reference)
                role = "reference_header" if is_header_only else "reference_body"
                unit_block = replace(block, role=role)
                current = _OpenReferenceUnit(
                    reference=reference,
                    blocks=[unit_block],
                    body_blocks=[] if is_header_only else [unit_block],
                )
                continue

            if current is None:
                if self._should_emit_provenance(block):
                    units.append(
                        self._provenance_unit(
                            [replace(block, role="unassigned")],
                            semantics=semantics,
                            parent_metadata=parent_metadata,
                            parent_source_location=parent_source_location,
                            runtime_source_id=runtime_source_id,
                            preview_ref=preview_ref,
                            reason="unassigned_before_first_reference",
                        )
                    )
                continue
            if not semantics.carry_forward_body_blocks:
                if self._should_emit_provenance(block):
                    units.append(
                        self._provenance_unit(
                            [replace(block, role="unassigned")],
                            semantics=semantics,
                            parent_metadata=parent_metadata,
                            parent_source_location=parent_source_location,
                            runtime_source_id=runtime_source_id,
                            preview_ref=preview_ref,
                            reason="carry_forward_disabled",
                        )
                    )
                continue
            if not self._within_page_gap(current.blocks[-1], block, semantics.max_page_gap):
                units.append(
                    self._finish_unit(
                        current,
                        semantics=semantics,
                        parent_metadata=parent_metadata,
                        parent_source_location=parent_source_location,
                        runtime_source_id=runtime_source_id,
                        content_type=content_type,
                        preview_ref=preview_ref,
                    )
                )
                current = None
                if self._should_emit_provenance(block):
                    units.append(
                        self._provenance_unit(
                            [replace(block, role="unassigned")],
                            semantics=semantics,
                            parent_metadata=parent_metadata,
                            parent_source_location=parent_source_location,
                            runtime_source_id=runtime_source_id,
                            preview_ref=preview_ref,
                            reason="max_page_gap_exceeded",
                        )
                    )
                continue
            if text:
                role = "reference_body" if not current.body_blocks else "reference_continuation"
                body_block = replace(block, role=role)
                current.blocks.append(body_block)
                current.body_blocks.append(body_block)
            elif self._should_emit_provenance(block):
                current.blocks.append(replace(block, role="parser_warning"))

        if current is not None:
            units.append(
                self._finish_unit(
                    current,
                    semantics=semantics,
                    parent_metadata=parent_metadata,
                    parent_source_location=parent_source_location,
                    runtime_source_id=runtime_source_id,
                    content_type=content_type,
                    preview_ref=preview_ref,
                )
            )
        return units

    def _finish_unit(
        self,
        unit: _OpenReferenceUnit,
        *,
        semantics: ReferenceSemantics,
        parent_metadata: dict[str, Any],
        parent_source_location: dict[str, Any],
        runtime_source_id: str | None,
        content_type: str,
        preview_ref: str | None,
    ) -> AssembledReferenceUnit:
        source_location = self._source_location(parent_source_location, unit.blocks)
        has_body = any(block.text.strip() for block in unit.body_blocks)
        is_provenance_only = (
            not has_body and semantics.header_only_policy == "provenance_only"
        )
        output_content_type = "reference_provenance" if is_provenance_only else content_type
        text = "\n\n".join(block.text.strip() for block in unit.blocks if block.text.strip())
        reference = str(unit.reference.get("ref") or unit.reference.get("raw") or "").strip()

        metadata = dict(parent_metadata)
        metadata["reference_metadata"] = self._reference_metadata(
            semantics,
            text,
            unit.reference,
            source_location,
        )
        metadata["canonical_reference_unit"] = {
            "reference": reference,
            "raw_reference": unit.reference.get("raw"),
            "unit": semantics.chunk_unit,
            "answerable": not is_provenance_only,
            "body_status": "assembled"
            if len(unit.body_blocks) > 1
            else "single_block"
            if has_body
            else "header_only",
            "assembly_strategy": "structured_reference_metadata",
        }
        if semantics.preserve_original_blocks:
            metadata["provenance"] = {
                "source": "mineru_content_list",
                "blocks": [
                    self._provenance_block(block, semantics=semantics)
                    for block in unit.blocks
                ],
            }
        self._merge_parser_warnings(metadata, self._block_warnings(unit.blocks))

        if is_provenance_only:
            parser_metadata = dict(metadata.get("parser_metadata") or {})
            parser_metadata["provenance_only"] = True
            metadata["parser_metadata"] = parser_metadata
            metadata["quality_action_policy"] = provenance_only_quality_policy()
            metadata["quality_flags"] = ["provenance_only"]

        return AssembledReferenceUnit(
            text=text,
            source_location=source_location,
            metadata=metadata,
            runtime_source_id=runtime_source_id,
            content_type=output_content_type,
            preview_ref=reference or preview_ref,
        )

    def _provenance_unit(
        self,
        blocks: list[ReferenceSourceBlock],
        *,
        semantics: ReferenceSemantics,
        parent_metadata: dict[str, Any],
        parent_source_location: dict[str, Any],
        runtime_source_id: str | None,
        preview_ref: str | None,
        reason: str,
    ) -> AssembledReferenceUnit:
        source_location = self._source_location(parent_source_location, blocks)
        text = "\n\n".join(block.text.strip() for block in blocks if block.text.strip())
        if not text:
            text = self._warning_only_text(blocks)

        metadata = dict(parent_metadata)
        parser_metadata = dict(metadata.get("parser_metadata") or {})
        parser_metadata["provenance_only"] = True
        parser_metadata["provenance_reason"] = reason
        metadata["parser_metadata"] = parser_metadata
        metadata["quality_action_policy"] = provenance_only_quality_policy()
        metadata["quality_flags"] = ["provenance_only"]
        metadata["canonical_reference_unit"] = {
            "reference": None,
            "unit": semantics.chunk_unit,
            "answerable": False,
            "body_status": (
                "unassigned"
                if any(block.text.strip() for block in blocks)
                else "warning_only"
            ),
            "assembly_strategy": "structured_reference_metadata",
            "provenance_reason": reason,
        }
        if semantics.preserve_original_blocks:
            metadata["provenance"] = {
                "source": "mineru_content_list",
                "blocks": [
                    self._provenance_block(block, semantics=semantics)
                    for block in blocks
                ],
            }
        self._merge_parser_warnings(metadata, self._block_warnings(blocks))

        return AssembledReferenceUnit(
            text=text,
            source_location=source_location,
            metadata=metadata,
            runtime_source_id=runtime_source_id,
            content_type="reference_provenance",
            preview_ref=preview_ref,
        )

    def _reference_metadata(
        self,
        semantics: ReferenceSemantics,
        text: str,
        reference: dict[str, int | str],
        source_location: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = semantics.derive_reference_metadata(text, source_location)
        if metadata:
            return metadata
        canonical_reference = str(reference.get("ref") or reference.get("raw") or "")
        return {
            "reference_type": semantics.reference_type,
            "references": [canonical_reference],
            **self._page_range(source_location),
        }

    def _expand_multi_reference_blocks(
        self,
        blocks: list[ReferenceSourceBlock],
        semantics: ReferenceSemantics,
    ) -> list[ReferenceSourceBlock]:
        expanded: list[ReferenceSourceBlock] = []
        for block in blocks:
            if len(semantics.extract_chunk_references(block.text)) <= 1:
                expanded.append(block)
                continue
            units = semantics.split_reference_units(block.text)
            if len(units) <= 1:
                expanded.append(block)
                continue
            for index, text in enumerate(units):
                source_block_ref = block.source_block_ref
                if source_block_ref:
                    source_block_ref = f"{source_block_ref}:ref{index}"
                expanded.append(
                    replace(
                        block,
                        text=text,
                        source_block_ref=source_block_ref,
                    )
                )
        return expanded

    def _is_header_only_reference(
        self,
        text: str,
        reference: dict[str, int | str],
    ) -> bool:
        raw = str(reference.get("raw") or "").strip()
        if not raw:
            return False
        start = text.casefold().find(raw.casefold())
        if start < 0:
            return False
        remainder = f"{text[:start]}{text[start + len(raw):]}"
        return not re.sub(r"[\s\-\:\.,;()\[\]]+", "", remainder)

    def _within_page_gap(
        self,
        previous: ReferenceSourceBlock,
        block: ReferenceSourceBlock,
        max_page_gap: int | None,
    ) -> bool:
        if max_page_gap is None:
            return True
        if previous.page_end is None or block.page_start is None:
            return True
        return block.page_start - previous.page_end <= max_page_gap

    def _should_emit_provenance(self, block: ReferenceSourceBlock) -> bool:
        return bool(
            block.text.strip()
            or block.parser_warnings
            or block.parser_warning_codes
        )

    def _source_location(
        self,
        parent_source_location: dict[str, Any],
        blocks: list[ReferenceSourceBlock],
    ) -> dict[str, Any]:
        source_location = dict(parent_source_location)
        page_starts = [block.page_start for block in blocks if block.page_start is not None]
        page_ends = [block.page_end for block in blocks if block.page_end is not None]
        if page_starts:
            source_location["page_start"] = min(page_starts)
        if page_ends:
            source_location["page_end"] = max(page_ends)
        return source_location

    def _page_range(self, source_location: dict[str, Any]) -> dict[str, Any]:
        page_start = source_location.get("page_start", source_location.get("page"))
        page_end = source_location.get("page_end", source_location.get("page"))
        pages: dict[str, Any] = {}
        if page_start is not None:
            pages["page_start"] = page_start
        if page_end is not None:
            pages["page_end"] = page_end
        return pages

    def _provenance_block(
        self,
        block: ReferenceSourceBlock,
        *,
        semantics: ReferenceSemantics,
    ) -> dict[str, Any]:
        preview_chars = max(0, semantics.block_preview_chars)
        item: dict[str, Any] = {
            "role": block.role,
            "page_start": block.page_start,
            "page_end": block.page_end,
            "block_type": block.block_type,
            "parser_warning_codes": self._warning_codes(block),
            "text_preview": block.text[:preview_chars],
        }
        if block.source_block_ref:
            item["source_block_ref"] = block.source_block_ref
        if semantics.store_text_hash:
            item["text_hash"] = hashlib.sha256(block.text.encode("utf-8")).hexdigest()
        return {key: value for key, value in item.items() if value not in (None, [], "")}

    def _warning_only_text(self, blocks: list[ReferenceSourceBlock]) -> str:
        codes = sorted(
            {
                code
                for block in blocks
                for code in self._warning_codes(block)
                if code
            }
        )
        if codes:
            return (
                "[Parser quality provenance retained warning-only block: "
                f"{', '.join(codes)}.]"
            )
        return "[Reference provenance retained block with no trusted text.]"

    def _warning_codes(self, block: ReferenceSourceBlock) -> list[str]:
        codes = [
            warning.get("code")
            for warning in block.parser_warnings
            if isinstance(warning.get("code"), str)
        ]
        codes.extend(block.parser_warning_codes)
        return list(dict.fromkeys(code for code in codes if isinstance(code, str) and code))

    def _block_warnings(self, blocks: list[ReferenceSourceBlock]) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        seen: set[str] = set()
        seen_codes: set[tuple[str, str | None, int | None]] = set()
        for block in blocks:
            for warning in block.parser_warnings:
                if not isinstance(warning, dict):
                    continue
                item = dict(warning)
                if "block_type" not in item and block.block_type:
                    item["block_type"] = block.block_type
                if "page" not in item and block.page_start is not None:
                    item["page"] = block.page_start
                key = json.dumps(item, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                code = item.get("code")
                if isinstance(code, str):
                    seen_codes.add((code, item.get("block_type"), item.get("page")))
                warnings.append(item)
            for code in block.parser_warning_codes:
                key_tuple = (code, block.block_type, block.page_start)
                if key_tuple in seen_codes:
                    continue
                item: dict[str, Any] = {"code": code}
                if block.block_type:
                    item["block_type"] = block.block_type
                if block.page_start is not None:
                    item["page"] = block.page_start
                key = json.dumps(item, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                seen_codes.add(key_tuple)
                warnings.append(item)
        return warnings

    def _merge_parser_warnings(
        self,
        metadata: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> None:
        if not warnings:
            return
        extraction_quality = metadata.get("extraction_quality")
        if isinstance(extraction_quality, dict):
            extraction_quality = dict(extraction_quality)
        else:
            extraction_quality = {}
        parser_warnings = extraction_quality.get("parser_warnings")
        merged = list(parser_warnings) if isinstance(parser_warnings, list) else []
        seen = {
            json.dumps(warning, sort_keys=True, default=str)
            for warning in merged
            if isinstance(warning, dict)
        }
        for warning in warnings:
            key = json.dumps(warning, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
        extraction_quality["parser_warnings"] = merged
        metadata["extraction_quality"] = extraction_quality


def provenance_only_quality_policy() -> dict[str, Any]:
    return {
        "persist_chunk": True,
        "index_vector": False,
        "index_exact_arabic": False,
        "project_graph": False,
        "graph_confidence": "provenance_only",
        "quality_flags": ["provenance_only"],
    }

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata

TEXT_BLOCK_TYPES = frozenset(
    {
        "caption",
        "heading",
        "list",
        "list_item",
        "paragraph",
        "para",
        "section",
        "table",
        "table_body",
        "text",
        "title",
    }
)
EQUATION_BLOCK_TYPES = frozenset({"equation", "equation_interline", "interline_equation"})


@dataclass(frozen=True)
class ExpectedContentProfile:
    expected_scripts: frozenset[str] = field(default_factory=frozenset)
    allowed_block_types: frozenset[str] = field(default_factory=lambda: TEXT_BLOCK_TYPES)
    reference_patterns: tuple[str, ...] = ()
    content_domain: str = "generic"
    parser_strictness: str = "normal"
    recover_text_bearing_blocks_as_prose: bool = False

    @classmethod
    def from_domain_metadata(cls, domain_metadata: DomainMetadata) -> ExpectedContentProfile:
        custom_json = (
            domain_metadata.custom_json if isinstance(domain_metadata.custom_json, dict) else {}
        )
        parser_json = _dict_value(custom_json, "parser_normalization")
        if parser_json is None:
            parser_json = _dict_value(custom_json, "content_profile") or {}

        expected_scripts = _configured_set(parser_json.get("expected_scripts"))
        if not expected_scripts:
            expected_scripts = _scripts_from_metadata(domain_metadata)

        allowed_block_types = _configured_set(parser_json.get("allowed_block_types"))
        if not allowed_block_types:
            allowed_block_types = set(TEXT_BLOCK_TYPES)
            if _metadata_allows_equations(domain_metadata, parser_json):
                allowed_block_types.update(EQUATION_BLOCK_TYPES)

        reference_patterns = []
        if domain_metadata.reference_pattern:
            reference_patterns.append(domain_metadata.reference_pattern)
        reference_patterns.extend(_configured_strings(parser_json.get("reference_patterns")))

        parser_strictness = parser_json.get("parser_strictness") or parser_json.get("strictness")
        if not isinstance(parser_strictness, str) or not parser_strictness.strip():
            parser_strictness = "strict" if reference_patterns or expected_scripts else "normal"
        recover_text_bearing_blocks_as_prose = bool(
            parser_json.get("recover_text_bearing_blocks_as_prose")
        )

        return cls(
            expected_scripts=frozenset(expected_scripts),
            allowed_block_types=frozenset(_normalize_token(item) for item in allowed_block_types),
            reference_patterns=tuple(reference_patterns),
            content_domain=_normalize_token(domain_metadata.domain or "generic"),
            parser_strictness=parser_strictness.strip().lower(),
            recover_text_bearing_blocks_as_prose=recover_text_bearing_blocks_as_prose,
        )

    def allows_block_type(self, block_type: str) -> bool:
        return _normalize_token(block_type) in self.allowed_block_types

    def allows_equations_as_content(self) -> bool:
        return bool(self.allowed_block_types.intersection(EQUATION_BLOCK_TYPES))


@dataclass(frozen=True)
class NormalizationWarning:
    code: str
    message: str
    block_type: str
    page: int | None = None
    recovery_source: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "block_type": self.block_type,
        }
        if self.page is not None:
            metadata["page"] = self.page
        if self.recovery_source:
            metadata["recovery_source"] = self.recovery_source
        return metadata


@dataclass(frozen=True)
class BlockRecovery:
    text: str
    source: str


@dataclass(frozen=True)
class NormalizedBlock:
    text: str
    page: int | None
    block_type: str
    source_item: dict[str, Any]
    warnings: tuple[NormalizationWarning, ...] = ()
    recovery: BlockRecovery | None = None

    def warning_metadata(self) -> list[dict[str, Any]]:
        return [warning.to_metadata() for warning in self.warnings]


class MinerUContentNormalizer:
    def normalize_content_list(
        self,
        data: Any,
        *,
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
        artifact_root: Path | str | None = None,
        content_list_path: Path | str | None = None,
    ) -> list[NormalizedBlock]:
        if expected_profile is None:
            expected_profile = ExpectedContentProfile.from_domain_metadata(
                domain_metadata or DomainMetadata()
            )
        if not isinstance(data, list):
            return []

        artifact_root_path = Path(artifact_root).resolve() if artifact_root else None
        content_list_file = Path(content_list_path).resolve() if content_list_path else None

        normalized: list[NormalizedBlock] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            block_type = _block_type(item)
            page = _page_number(item)
            text = self._extract_text(item, block_type=block_type).replace("\x00", "").strip()
            recovery = self._extract_recovery(
                item,
                block_type=block_type,
                artifact_root=artifact_root_path,
                content_list_path=content_list_file,
            )

            if (
                block_type in EQUATION_BLOCK_TYPES
                and not expected_profile.allows_equations_as_content()
            ):
                recover_text = (
                    recovery.text.replace("\x00", "").strip()
                    if recovery and recovery.text.strip()
                    else text
                    if expected_profile.recover_text_bearing_blocks_as_prose
                    else ""
                )
                warning = self._warning_for_misclassified_equation(
                    block_type,
                    page,
                    recovered=bool(recover_text),
                    recovery_source=recovery.source if recovery else None,
                )
                if recover_text:
                    normalized.append(
                        NormalizedBlock(
                            text=recover_text,
                            page=page,
                            block_type=block_type,
                            source_item=item,
                            warnings=(warning,),
                            recovery=recovery,
                        )
                    )
                else:
                    normalized.append(
                        NormalizedBlock(
                            text="",
                            page=page,
                            block_type=block_type,
                            source_item=item,
                            warnings=(warning,),
                        )
                    )
                continue

            if not expected_profile.allows_block_type(block_type):
                if text or (recovery and recovery.text.strip()):
                    recover_text = (
                        recovery.text.replace("\x00", "").strip()
                        if recovery and recovery.text.strip()
                        else text
                        if expected_profile.recover_text_bearing_blocks_as_prose
                        else ""
                    )
                    warning = self._warning_for_disallowed_block(
                        block_type,
                        page,
                        recovered=bool(recover_text),
                        recovery_source=recovery.source if recovery else None,
                    )
                    normalized.append(
                        NormalizedBlock(
                            text=recover_text,
                            page=page,
                            block_type=block_type,
                            source_item=item,
                            warnings=(warning,),
                            recovery=recovery,
                        )
                    )
                continue

            if text:
                normalized.append(
                    NormalizedBlock(
                        text=text,
                        page=page,
                        block_type=block_type,
                        source_item=item,
                    )
                )

        return normalized

    def _extract_text(self, value: Any, *, block_type: str | None = None) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            keys = ["text", "content", "paragraph_content", "table_body"]
            if block_type in EQUATION_BLOCK_TYPES:
                keys.append("latex")
            for key in keys:
                if key in value:
                    text = self._extract_text(value[key], block_type=block_type)
                    if text.strip():
                        return text
            return ""
        if isinstance(value, list):
            parts = [self._extract_text(item, block_type=block_type).strip() for item in value]
            return " ".join(part for part in parts if part)
        return ""

    def _extract_recovery(
        self,
        item: dict[str, Any],
        *,
        block_type: str,
        artifact_root: Path | None,
        content_list_path: Path | None,
    ) -> BlockRecovery | None:
        recovered_text = item.get("recovered_text")
        if isinstance(recovered_text, str) and recovered_text.strip():
            return BlockRecovery(text=_clean_text(recovered_text), source="recovered_text")

        recovery = item.get("recovery")
        if isinstance(recovery, dict):
            text = recovery.get("text")
            source = recovery.get("source") or "recovery.text"
            if isinstance(text, str) and text.strip() and isinstance(source, str):
                return BlockRecovery(text=_clean_text(text), source=source)
        pdf_recovery = self._extract_pdf_text_layer_recovery(
            item,
            block_type=block_type,
            artifact_root=artifact_root,
            content_list_path=content_list_path,
        )
        if pdf_recovery is not None:
            return pdf_recovery
        return None

    def _extract_pdf_text_layer_recovery(
        self,
        item: dict[str, Any],
        *,
        block_type: str,
        artifact_root: Path | None,
        content_list_path: Path | None,
    ) -> BlockRecovery | None:
        if block_type not in EQUATION_BLOCK_TYPES:
            return None
        if not (item.get("img_path") or item.get("image_path")):
            return None
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            return None
        pdf_path = _source_pdf_path(
            artifact_root=artifact_root,
            content_list_path=content_list_path,
        )
        if pdf_path is None:
            return None

        try:
            import fitz  # type: ignore[import-not-found]
        except Exception:
            return None

        try:
            with fitz.open(pdf_path) as document:
                page_index = _page_index(item)
                if page_index is None:
                    page_index = 0
                if page_index < 0 or page_index >= document.page_count:
                    if document.page_count == 1:
                        page_index = 0
                    else:
                        return None
                page = document[page_index]
                target = _scaled_bbox_to_page_rect(bbox, page.rect, fitz)
                text = _overlapping_pdf_line_text(page, target, fitz)
        except Exception:
            return None

        if not text:
            return None
        source = "pdf_text_layer"
        if content_list_path is not None:
            try:
                relative_pdf_path = pdf_path.resolve().relative_to(
                    content_list_path.parent.resolve()
                )
                source = f"pdf_text_layer:{relative_pdf_path.as_posix()}"
            except ValueError:
                source = "pdf_text_layer"
        return BlockRecovery(text=_clean_text(text), source=source)

    def _warning_for_misclassified_equation(
        self,
        block_type: str,
        page: int | None,
        *,
        recovered: bool,
        recovery_source: str | None,
    ) -> NormalizationWarning:
        if recovered:
            return NormalizationWarning(
                code="recovered_text_from_misclassified_block",
                message=(
                    "Used parser-provided recovered text for a block misclassified as an "
                    "equation."
                ),
                block_type=block_type,
                page=page,
                recovery_source=recovery_source,
            )
        return NormalizationWarning(
            code="suspected_text_misclassified_as_equation",
            message=(
                "Quarantined equation block because the expected content profile does not "
                "allow equations as prose content."
            ),
            block_type=block_type,
            page=page,
        )

    def _warning_for_disallowed_block(
        self,
        block_type: str,
        page: int | None,
        *,
        recovered: bool,
        recovery_source: str | None,
    ) -> NormalizationWarning:
        if recovered:
            return NormalizationWarning(
                code="recovered_text_from_disallowed_block",
                message=(
                    "Used parser-provided recovered text for a disallowed block type."
                ),
                block_type=block_type,
                page=page,
                recovery_source=recovery_source,
            )
        return NormalizationWarning(
            code="disallowed_block_type_quarantined",
            message=(
                "Quarantined text-bearing block because the expected content profile "
                "does not allow this block type."
            ),
            block_type=block_type,
            page=page,
        )


def _dict_value(value: dict[str, Any], key: str) -> dict[str, Any] | None:
    candidate = value.get(key)
    return candidate if isinstance(candidate, dict) else None


def _configured_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {_normalize_token(value)}
    if isinstance(value, list | tuple | set | frozenset):
        return {_normalize_token(item) for item in value if isinstance(item, str) and item.strip()}
    return set()


def _configured_strings(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list | tuple):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _scripts_from_metadata(domain_metadata: DomainMetadata) -> set[str]:
    scripts: set[str] = set()
    script = _normalize_token(domain_metadata.script)
    language = _normalize_token(domain_metadata.language)
    tags = {_normalize_token(tag) for tag in domain_metadata.tags}

    mixed_script_aliases = {"mixed", "arabic_english", "arabic_latin"}
    latin_aliases = {"english", "latin", "translation"}

    if script in {"arabic", "latin"}:
        scripts.add(script)
    if script in mixed_script_aliases:
        scripts.update({"arabic", "latin"})
    if language == "arabic" or "arabic" in tags:
        scripts.add("arabic")
    if language in latin_aliases or tags.intersection(latin_aliases):
        scripts.add("latin")
    if language in mixed_script_aliases:
        scripts.update({"arabic", "latin"})
    if tags.intersection(mixed_script_aliases):
        scripts.update({"arabic", "latin"})
    return scripts


def _metadata_allows_equations(
    domain_metadata: DomainMetadata,
    parser_json: dict[str, Any],
) -> bool:
    configured = parser_json.get("allow_equations_as_content")
    if isinstance(configured, bool):
        return configured

    fields = {
        _normalize_token(domain_metadata.domain),
        _normalize_token(domain_metadata.document_type),
        _normalize_token(domain_metadata.content_role),
        *{_normalize_token(tag) for tag in domain_metadata.tags},
    }
    equation_terms = {"equation", "math", "mathematics", "physics", "science"}
    expected_structure_terms = _structured_terms(domain_metadata.expected_structure)
    return bool(
        fields.intersection(equation_terms)
        or expected_structure_terms.intersection(equation_terms)
    )


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().casefold()


def _clean_text(value: str) -> str:
    return value.replace("\x00", "").strip()


def _structured_terms(value: Any) -> set[str]:
    normalized = _normalize_token(value)
    if not normalized:
        return set()
    return {term for term in re.split(r"[^a-z0-9]+", normalized) if term}


def _block_type(item: dict[str, Any]) -> str:
    for key in ("type", "block_type", "category"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_token(value)
    return "text"


def _page_number(item: dict[str, Any]) -> int | None:
    page_idx = item.get("page_idx")
    if type(page_idx) is int:
        return page_idx + 1
    page = item.get("page")
    return page if type(page) is int else None


def _page_index(item: dict[str, Any]) -> int | None:
    page_idx = item.get("page_idx")
    if type(page_idx) is int:
        return page_idx
    page = item.get("page")
    if type(page) is int and page > 0:
        return page - 1
    return None


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    coords: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            return None
        coords.append(float(item))
    x0, y0, x1, y1 = coords
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _source_pdf_path(
    *,
    artifact_root: Path | None,
    content_list_path: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if content_list_path is not None:
        candidates.extend(
            [
                content_list_path.parent / "source_origin.pdf",
                content_list_path.parent / "source.pdf",
            ]
        )
    if artifact_root is not None:
        candidates.extend(sorted(artifact_root.rglob("source_origin.pdf")))
        candidates.extend(sorted(artifact_root.rglob("source.pdf")))

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        if artifact_root is not None:
            root = artifact_root.resolve()
            if resolved != root and root not in resolved.parents:
                continue
        return resolved
    return None


def _scaled_bbox_to_page_rect(
    bbox: tuple[float, float, float, float],
    page_rect: Any,
    fitz: Any,
) -> Any:
    x0, y0, x1, y1 = bbox
    target = fitz.Rect(
        x0 * page_rect.width / 1000,
        y0 * page_rect.height / 1000,
        x1 * page_rect.width / 1000,
        y1 * page_rect.height / 1000,
    )
    return fitz.Rect(
        max(page_rect.x0, target.x0 - 4),
        max(page_rect.y0, target.y0 - 6),
        min(page_rect.x1, target.x1 + 4),
        min(page_rect.y1, target.y1 + 6),
    )


def _overlapping_pdf_line_text(page: Any, target: Any, fitz: Any) -> str:
    best_text = ""
    best_score = 0.0
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if not isinstance(block, dict) or block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if not isinstance(line, dict) or "bbox" not in line:
                continue
            line_rect = fitz.Rect(line["bbox"])
            overlap = line_rect & target
            score = max(0.0, overlap.width) * max(0.0, overlap.height)
            if score <= best_score:
                continue
            text = "".join(
                str(span.get("text") or "")
                for span in line.get("spans", [])
                if isinstance(span, dict)
            ).strip()
            if not text:
                continue
            best_score = score
            best_text = text
    return best_text

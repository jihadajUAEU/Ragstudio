from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
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
IMAGE_BLOCK_TYPES = frozenset({"figure", "image", "picture"})
VISION_TARGET_BLOCK_TYPES = IMAGE_BLOCK_TYPES | EQUATION_BLOCK_TYPES
VISION_RECOVERY_TRIGGERS = frozenset(
    {
        "missing_pdf_text_layer",
        "suspected_text_misclassified_as_equation",
        "missing_required_script",
    }
)
VISION_RECOVERY_MAX_TOTAL_BLOCKS = 40
VISION_IMAGE_MAX_BYTES = 4_000_000
SCRIPT_PATTERNS = {
    "arabic": re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"),
    "latin": re.compile(r"[A-Za-z]"),
}


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
class VisionRecoveryConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_ms: int = 10_000
    enabled: bool = False
    target_block_types: frozenset[str] = field(default_factory=lambda: VISION_TARGET_BLOCK_TYPES)
    triggers: frozenset[str] = field(default_factory=lambda: VISION_RECOVERY_TRIGGERS)
    languages: frozenset[str] = field(default_factory=frozenset)
    max_blocks_per_page: int = 3
    max_total_blocks: int = VISION_RECOVERY_MAX_TOTAL_BLOCKS
    failure_action: str = "warn"
    prompt_hint: str | None = None

    @classmethod
    def from_runtime_profile(
        cls,
        domain_metadata: DomainMetadata,
        profile: Any,
    ) -> VisionRecoveryConfig | None:
        custom_json = (
            domain_metadata.custom_json if isinstance(domain_metadata.custom_json, dict) else {}
        )
        policy = _dict_value(custom_json, "vision_recovery_policy") or {}
        if policy.get("enabled") is not True:
            return None

        base_url = _string_value(getattr(profile, "vision_base_url", None)) or (
            _string_value(getattr(profile, "llm_base_url", None))
            if "vision" in (getattr(profile, "llm_capabilities", None) or [])
            else None
        )
        model = _string_value(getattr(profile, "vision_model", None)) or _string_value(
            getattr(profile, "llm_model", None)
        )
        if not base_url or not model:
            return None

        target_block_types = _configured_set(policy.get("target_block_types"))
        triggers = _configured_set(policy.get("triggers"))
        languages = {
            _normalize_script_label(item)
            for item in _configured_set(policy.get("languages"))
            if _normalize_script_label(item)
        }
        max_blocks_per_page = _bounded_int(
            policy.get("max_blocks_per_page"),
            default=3,
            minimum=1,
            maximum=20,
        )
        max_total_blocks = _bounded_int(
            policy.get("max_total_blocks"),
            default=VISION_RECOVERY_MAX_TOTAL_BLOCKS,
            minimum=1,
            maximum=500,
        )
        return cls(
            base_url=base_url,
            model=model,
            api_key=_string_value(getattr(profile, "vision_api_key", None))
            or _string_value(getattr(profile, "llm_api_key", None)),
            timeout_ms=_bounded_int(
                getattr(profile, "vision_timeout_ms", None),
                default=10_000,
                minimum=1_000,
                maximum=300_000,
            ),
            enabled=True,
            target_block_types=frozenset(target_block_types or VISION_TARGET_BLOCK_TYPES),
            triggers=frozenset(triggers or VISION_RECOVERY_TRIGGERS),
            languages=frozenset(languages),
            max_blocks_per_page=max_blocks_per_page,
            max_total_blocks=max_total_blocks,
            failure_action=_string_value(policy.get("failure_action")) or "warn",
            prompt_hint=_string_value(policy.get("prompt_hint")),
        )


@dataclass
class _VisionRecoveryState:
    total_calls: int = 0
    per_page_calls: dict[int, int] = field(default_factory=dict)

    def reserve(self, page: int | None, config: VisionRecoveryConfig) -> bool:
        if self.total_calls >= config.max_total_blocks:
            return False
        page_key = page if page is not None else -1
        if self.per_page_calls.get(page_key, 0) >= config.max_blocks_per_page:
            return False
        self.total_calls += 1
        self.per_page_calls[page_key] = self.per_page_calls.get(page_key, 0) + 1
        return True


class VisionBlockRecoveryClient:
    def recover_text(
        self,
        *,
        image_data_url: str,
        block_type: str,
        page: int | None,
        triggers: list[str],
        existing_text: str,
        config: VisionRecoveryConfig,
    ) -> str | None:
        prompt = _vision_recovery_prompt(
            block_type=block_type,
            page=page,
            triggers=triggers,
            existing_text=existing_text,
            config=config,
        )
        payload = {
            "model": config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }
        headers = {"content-type": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"

        url = f"{config.base_url.rstrip('/')}/chat/completions"
        try:
            with httpx.Client(timeout=config.timeout_ms / 1000) as client:
                response = client.post(url, headers=headers, json=payload)
                if response.status_code in {400, 422}:
                    fallback_payload = dict(payload)
                    fallback_payload.pop("response_format", None)
                    response = client.post(url, headers=headers, json=fallback_payload)
                response.raise_for_status()
                response_payload = response.json()
        except httpx.HTTPError:
            return None
        except ValueError:
            return None
        return _parse_vision_recovery_text(response_payload)


@dataclass(frozen=True)
class _PdfTextLayerRecoveryContext:
    pdf_path: Path
    document: Any
    fitz: Any
    content_list_path: Path | None

    def close(self) -> None:
        try:
            self.document.close()
        except Exception:
            pass

    def source_label(self) -> str:
        source = "pdf_text_layer"
        if self.content_list_path is None:
            return source
        try:
            relative_pdf_path = self.pdf_path.resolve().relative_to(
                self.content_list_path.parent.resolve()
            )
        except ValueError:
            return source
        return f"pdf_text_layer:{relative_pdf_path.as_posix()}"


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
    def __init__(
        self,
        *,
        vision_recovery_client: VisionBlockRecoveryClient | None = None,
    ) -> None:
        self.vision_recovery_client = vision_recovery_client or VisionBlockRecoveryClient()

    def normalize_content_list(
        self,
        data: Any,
        *,
        domain_metadata: DomainMetadata | None = None,
        expected_profile: ExpectedContentProfile | None = None,
        artifact_root: Path | str | None = None,
        content_list_path: Path | str | None = None,
        vision_recovery_config: VisionRecoveryConfig | None = None,
    ) -> list[NormalizedBlock]:
        domain_metadata = domain_metadata or DomainMetadata()
        if expected_profile is None:
            expected_profile = ExpectedContentProfile.from_domain_metadata(domain_metadata)
        if not isinstance(data, list):
            return []

        artifact_root_path = Path(artifact_root).resolve() if artifact_root else None
        content_list_file = Path(content_list_path).resolve() if content_list_path else None
        pdf_recovery_context = self._open_pdf_text_layer_recovery_context(
            artifact_root=artifact_root_path,
            content_list_path=content_list_file,
        )
        vision_recovery_state = _VisionRecoveryState()

        normalized: list[NormalizedBlock] = []
        try:
            for item in data:
                if not isinstance(item, dict):
                    continue

                block_type = _block_type(item)
                page = _page_number(item)
                text = self._extract_text(item, block_type=block_type).replace("\x00", "").strip()
                recovery = self._extract_recovery(
                    item,
                    block_type=block_type,
                    existing_text=text,
                    domain_metadata=domain_metadata,
                    expected_profile=expected_profile,
                    pdf_recovery_context=pdf_recovery_context,
                    artifact_root=artifact_root_path,
                    content_list_path=content_list_file,
                    vision_recovery_config=vision_recovery_config,
                    vision_recovery_state=vision_recovery_state,
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
            if pdf_recovery_context is not None:
                normalized = self._recover_reference_header_gaps(
                    normalized,
                    pdf_recovery_context=pdf_recovery_context,
                )
        finally:
            if pdf_recovery_context is not None:
                pdf_recovery_context.close()

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
        existing_text: str,
        domain_metadata: DomainMetadata,
        expected_profile: ExpectedContentProfile,
        pdf_recovery_context: _PdfTextLayerRecoveryContext | None,
        artifact_root: Path | None,
        content_list_path: Path | None,
        vision_recovery_config: VisionRecoveryConfig | None,
        vision_recovery_state: _VisionRecoveryState,
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
            pdf_recovery_context=pdf_recovery_context,
        )
        vision_recovery = self._extract_vision_recovery(
            item,
            block_type=block_type,
            existing_text=pdf_recovery.text if pdf_recovery is not None else existing_text,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
            pdf_recovery=pdf_recovery,
            pdf_recovery_context=pdf_recovery_context,
            artifact_root=artifact_root,
            content_list_path=content_list_path,
            vision_recovery_config=vision_recovery_config,
            vision_recovery_state=vision_recovery_state,
        )
        if vision_recovery is not None:
            return vision_recovery
        if pdf_recovery is not None:
            return pdf_recovery
        return None

    def _extract_vision_recovery(
        self,
        item: dict[str, Any],
        *,
        block_type: str,
        existing_text: str,
        domain_metadata: DomainMetadata,
        expected_profile: ExpectedContentProfile,
        pdf_recovery: BlockRecovery | None,
        pdf_recovery_context: _PdfTextLayerRecoveryContext | None,
        artifact_root: Path | None,
        content_list_path: Path | None,
        vision_recovery_config: VisionRecoveryConfig | None,
        vision_recovery_state: _VisionRecoveryState,
    ) -> BlockRecovery | None:
        config = vision_recovery_config
        if config is None or not config.enabled:
            return None
        normalized_block_type = _normalize_token(block_type)
        if not _vision_target_allows_block_type(normalized_block_type, config.target_block_types):
            return None

        triggers = self._vision_recovery_triggers(
            existing_text=existing_text,
            block_type=block_type,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
            pdf_recovery=pdf_recovery,
        )
        active_triggers = [trigger for trigger in triggers if trigger in config.triggers]
        if not active_triggers:
            return None

        image_data_url = _image_data_url_for_item(
            item,
            artifact_root=artifact_root,
            content_list_path=content_list_path,
            pdf_recovery_context=pdf_recovery_context,
        )
        if image_data_url is None:
            return None

        page = _page_number(item)
        if not vision_recovery_state.reserve(page, config):
            return None

        recovered_text = self.vision_recovery_client.recover_text(
            image_data_url=image_data_url,
            block_type=block_type,
            page=page,
            triggers=active_triggers,
            existing_text=existing_text,
            config=config,
        )
        if not recovered_text or not recovered_text.strip():
            return None
        if not _vision_recovery_text_is_usable(
            recovered_text,
            existing_text=existing_text,
            domain_metadata=domain_metadata,
            expected_profile=expected_profile,
            active_triggers=active_triggers,
        ):
            return None
        return BlockRecovery(
            text=_clean_text(recovered_text),
            source=f"vision_model:{config.model}",
        )

    def _vision_recovery_triggers(
        self,
        *,
        existing_text: str,
        block_type: str,
        domain_metadata: DomainMetadata,
        expected_profile: ExpectedContentProfile,
        pdf_recovery: BlockRecovery | None,
    ) -> list[str]:
        triggers: list[str] = []
        has_existing_text = bool(existing_text.strip())
        if not has_existing_text and pdf_recovery is None:
            triggers.append("missing_pdf_text_layer")
        if block_type in EQUATION_BLOCK_TYPES and not (
            has_existing_text or expected_profile.allows_equations_as_content()
        ):
            triggers.append("suspected_text_misclassified_as_equation")

        required_scripts = _required_scripts_for_vision(domain_metadata, expected_profile)
        if required_scripts and _missing_scripts(existing_text, required_scripts):
            triggers.append("missing_required_script")
        return list(dict.fromkeys(triggers))

    def _open_pdf_text_layer_recovery_context(
        self,
        *,
        artifact_root: Path | None,
        content_list_path: Path | None,
    ) -> _PdfTextLayerRecoveryContext | None:
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
            document = fitz.open(pdf_path)
        except Exception:
            return None
        return _PdfTextLayerRecoveryContext(
            pdf_path=pdf_path,
            document=document,
            fitz=fitz,
            content_list_path=content_list_path,
        )

    def _extract_pdf_text_layer_recovery(
        self,
        item: dict[str, Any],
        *,
        block_type: str,
        pdf_recovery_context: _PdfTextLayerRecoveryContext | None,
    ) -> BlockRecovery | None:
        if block_type not in EQUATION_BLOCK_TYPES | IMAGE_BLOCK_TYPES:
            return None
        if not (item.get("img_path") or item.get("image_path")):
            return None
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            return None
        if pdf_recovery_context is None:
            return None

        try:
            document = pdf_recovery_context.document
            fitz = pdf_recovery_context.fitz
            page_index = _page_index(item)
            if page_index is None:
                page_index = 0
            if page_index < 0 or page_index >= document.page_count:
                if document.page_count == 1:
                    page_index = 0
                else:
                    return None
            page = document[page_index]
            target = _scaled_bbox_to_page_rect(bbox, page.rect, fitz, padding=0)
            text = _overlapping_pdf_line_text(page, target, fitz)
            if not text:
                target = _scaled_bbox_to_page_rect(bbox, page.rect, fitz)
                text = _overlapping_pdf_line_text(page, target, fitz)
        except Exception:
            return None

        if not text:
            return None
        return BlockRecovery(text=_clean_text(text), source=pdf_recovery_context.source_label())

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

    def _recover_reference_header_gaps(
        self,
        normalized: list[NormalizedBlock],
        *,
        pdf_recovery_context: _PdfTextLayerRecoveryContext,
    ) -> list[NormalizedBlock]:
        indexed_blocks = list(enumerate(normalized))
        visual_blocks = sorted(
            indexed_blocks,
            key=lambda item: _visual_order_key(item[0], item[1]),
        )
        insertions: dict[int, list[NormalizedBlock]] = {}
        seen_recoveries: set[tuple[int, tuple[float, float, float, float], str]] = set()

        for visual_index, (original_index, header) in enumerate(visual_blocks):
            if not _looks_like_reference_header(header.text):
                continue
            header_bbox = _bbox(header.source_item.get("bbox"))
            if header.page is None or header_bbox is None:
                continue
            body = _next_latin_body_block(visual_blocks, visual_index, header)
            if body is None:
                continue
            _body_index, body_block = body
            body_bbox = _bbox(body_block.source_item.get("bbox"))
            if body_block.page is None or body_bbox is None:
                continue

            regions = _reference_gap_regions(
                header_page=header.page,
                header_bbox=header_bbox,
                body_page=body_block.page,
                body_bbox=body_bbox,
            )
            for region_page, region_bbox in regions:
                if _has_arabic_block_in_region(visual_blocks, region_page, region_bbox):
                    continue

                recovered_text = _pdf_arabic_lines_text_in_region(
                    pdf_recovery_context,
                    page_number=region_page,
                    content_bbox=region_bbox,
                )
                if not recovered_text:
                    continue
                recovery_key = (region_page, region_bbox, recovered_text)
                if recovery_key in seen_recoveries:
                    continue
                seen_recoveries.add(recovery_key)

                warning = NormalizationWarning(
                    code="recovered_text_from_disallowed_block",
                    message=(
                        "Recovered omitted reference text from the PDF text layer between "
                        "a verse header and its translation."
                    ),
                    block_type="pdf_text_gap",
                    page=region_page,
                    recovery_source=pdf_recovery_context.source_label(),
                )
                insertions.setdefault(original_index, []).append(
                    NormalizedBlock(
                        text=recovered_text,
                        page=region_page,
                        block_type="pdf_text_gap",
                        source_item={
                            "type": "pdf_text_gap",
                            "bbox": list(region_bbox),
                            "page_idx": region_page - 1,
                            "reference_header": header.text,
                            "synthetic": True,
                        },
                        warnings=(warning,),
                        recovery=BlockRecovery(
                            text=recovered_text,
                            source=pdf_recovery_context.source_label(),
                        ),
                    )
                )

        if not insertions:
            return normalized

        recovered: list[NormalizedBlock] = []
        for index, block in enumerate(normalized):
            recovered.append(block)
            recovered.extend(insertions.get(index, []))
        return recovered


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


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, minimum), maximum)


def _normalize_script_label(value: Any) -> str:
    normalized = _normalize_token(value)
    if normalized in {"english", "eng", "latin_script", "roman"}:
        return "latin"
    if normalized in {"arab", "arabic_script"}:
        return "arabic"
    return normalized


def _vision_target_allows_block_type(block_type: str, target_block_types: frozenset[str]) -> bool:
    if block_type in target_block_types:
        return True
    if block_type in EQUATION_BLOCK_TYPES and "equation" in target_block_types:
        return True
    return block_type in IMAGE_BLOCK_TYPES and bool(
        target_block_types.intersection(IMAGE_BLOCK_TYPES | {"image"})
    )


def _required_scripts_for_vision(
    domain_metadata: DomainMetadata,
    expected_profile: ExpectedContentProfile,
) -> frozenset[str]:
    del expected_profile
    custom_json = (
        domain_metadata.custom_json if isinstance(domain_metadata.custom_json, dict) else {}
    )
    quality_policy = _dict_value(custom_json, "quality_policy") or {}
    configured_scripts = _configured_set(quality_policy.get("required_scripts"))
    scripts = configured_scripts
    return frozenset(
        script
        for script in (_normalize_script_label(item) for item in scripts)
        if script in SCRIPT_PATTERNS
    )


def _missing_scripts(text: str, scripts: frozenset[str]) -> set[str]:
    return {
        script
        for script in scripts
        if not SCRIPT_PATTERNS.get(script, re.compile(r"$^")).search(text or "")
    }


def _vision_recovery_text_is_usable(
    recovered_text: str,
    *,
    existing_text: str,
    domain_metadata: DomainMetadata,
    expected_profile: ExpectedContentProfile,
    active_triggers: list[str],
) -> bool:
    required_scripts = _required_scripts_for_vision(domain_metadata, expected_profile)
    if "missing_required_script" not in active_triggers:
        return True

    missing_scripts = _missing_scripts(existing_text, required_scripts)
    if not missing_scripts:
        return False
    return not _missing_scripts(recovered_text, frozenset(missing_scripts))


def _image_data_url_for_item(
    item: dict[str, Any],
    *,
    artifact_root: Path | None,
    content_list_path: Path | None,
    pdf_recovery_context: _PdfTextLayerRecoveryContext | None,
) -> str | None:
    for key in ("img_path", "image_path", "path", "src"):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        image_path = _resolve_image_path(
            value.strip(),
            artifact_root=artifact_root,
            content_list_path=content_list_path,
        )
        if image_path is None:
            continue
        data_url = _path_to_image_data_url(image_path)
        if data_url is not None:
            return data_url
    return _render_pdf_crop_data_url(item, pdf_recovery_context=pdf_recovery_context)


def _resolve_image_path(
    value: str,
    *,
    artifact_root: Path | None,
    content_list_path: Path | None,
) -> Path | None:
    raw_path = Path(value)
    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path)
    if content_list_path is not None:
        candidates.append(content_list_path.parent / raw_path)
    if artifact_root is not None:
        candidates.append(artifact_root / raw_path)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if artifact_root is not None and not _path_is_within(resolved, artifact_root.resolve()):
            continue
        return resolved
    return None


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _path_to_image_data_url(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if len(payload) > VISION_IMAGE_MAX_BYTES:
        return None
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return _bytes_to_data_url(payload, mime_type=mime_type)


def _render_pdf_crop_data_url(
    item: dict[str, Any],
    *,
    pdf_recovery_context: _PdfTextLayerRecoveryContext | None,
) -> str | None:
    bbox = _bbox(item.get("bbox"))
    if bbox is None or pdf_recovery_context is None:
        return None
    try:
        document = pdf_recovery_context.document
        fitz = pdf_recovery_context.fitz
        page_index = _page_index(item) or 0
        if page_index < 0 or page_index >= document.page_count:
            return None
        page = document[page_index]
        target = _scaled_bbox_to_page_rect(bbox, page.rect, fitz, padding=(8, 8))
        for scale in (2.0, 1.0):
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                clip=target,
                alpha=False,
            )
            payload = pixmap.tobytes("png")
            if len(payload) <= VISION_IMAGE_MAX_BYTES:
                return _bytes_to_data_url(payload, mime_type="image/png")
    except Exception:
        return None
    return None


def _bytes_to_data_url(payload: bytes, *, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _vision_recovery_prompt(
    *,
    block_type: str,
    page: int | None,
    triggers: list[str],
    existing_text: str,
    config: VisionRecoveryConfig,
) -> str:
    language_hint = ", ".join(sorted(config.languages)) if config.languages else "detected"
    page_hint = f"page {page}" if page is not None else "unknown page"
    existing_preview = existing_text[:600].strip() if existing_text else "[none]"
    prompt_hint = f"\nAdditional document hint: {config.prompt_hint}" if config.prompt_hint else ""
    return (
        "OCR the visible document text in this cropped block image. "
        "Return only text that is visibly present in the image; do not translate, summarize, "
        "invent missing words, or describe layout. Preserve reading order and line breaks when "
        "possible.\n"
        f"Block type: {block_type}\n"
        f"Location: {page_hint}\n"
        f"Recovery triggers: {', '.join(triggers)}\n"
        f"Expected scripts/languages: {language_hint}\n"
        f"Current parser text: {existing_preview}{prompt_hint}\n"
        'Return JSON exactly as {"text": "..."} with an empty string when no text is readable.'
    )


def _parse_vision_recovery_text(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    if not isinstance(content, str) or not content.strip():
        return None

    stripped = _strip_json_code_fence(content.strip())
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    for key in ("text", "ocr_text", "recovered_text"):
        value = parsed.get(key)
        if isinstance(value, str):
            return _clean_text(value)
    return None


def _strip_json_code_fence(value: str) -> str:
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return value


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


def _visual_order_key(index: int, block: NormalizedBlock) -> tuple[int, int, float, float, int]:
    page = block.page
    if page is None:
        return (1, index, 0.0, 0.0, index)
    bbox = _bbox(block.source_item.get("bbox"))
    if bbox is None:
        return (0, page, float(index), 0.0, index)
    x0, y0, _x1, _y1 = bbox
    return (0, page, y0, x0, index)


def _next_latin_body_block(
    visual_blocks: list[tuple[int, NormalizedBlock]],
    visual_index: int,
    header: NormalizedBlock,
) -> tuple[int, NormalizedBlock] | None:
    header_bbox = _bbox(header.source_item.get("bbox"))
    if header.page is None or header_bbox is None:
        return None

    for original_index, block in visual_blocks[visual_index + 1 :]:
        if block.page is None or block.page > header.page + 1:
            break
        if _looks_like_reference_header(block.text):
            break
        if not _has_latin_script(block.text):
            continue
        block_bbox = _bbox(block.source_item.get("bbox"))
        if block_bbox is None:
            continue
        if block.page == header.page and block_bbox[1] <= header_bbox[3]:
            continue
        return original_index, block
    return None


def _reference_gap_regions(
    *,
    header_page: int,
    header_bbox: tuple[float, float, float, float],
    body_page: int,
    body_bbox: tuple[float, float, float, float],
) -> list[tuple[int, tuple[float, float, float, float]]]:
    x0, x1 = _reference_gap_x_range(header_bbox=header_bbox, body_bbox=body_bbox)
    if body_page == header_page:
        region = (x0, header_bbox[3], x1, body_bbox[1])
        return [(body_page, region)] if region[3] - region[1] >= 8 else []
    if body_page != header_page + 1:
        return []

    regions: list[tuple[int, tuple[float, float, float, float]]] = []
    header_page_region = (x0, header_bbox[3], x1, 1000.0)
    if header_page_region[3] - header_page_region[1] >= 8:
        regions.append((header_page, header_page_region))
    body_page_region = (x0, 0.0, x1, body_bbox[1])
    if body_page_region[3] - body_page_region[1] >= 8:
        regions.append((body_page, body_page_region))
    return regions


def _reference_gap_x_range(
    *,
    header_bbox: tuple[float, float, float, float],
    body_bbox: tuple[float, float, float, float],
) -> tuple[float, float]:
    tolerance = 40.0
    if _horizontal_overlap(header_bbox, body_bbox) > 0:
        x0 = min(header_bbox[0], body_bbox[0]) - tolerance
        x1 = max(header_bbox[2], body_bbox[2]) + tolerance
    else:
        x0 = body_bbox[0] - tolerance
        x1 = body_bbox[2] + tolerance
    return max(0.0, x0), min(1000.0, x1)


def _has_arabic_block_in_region(
    visual_blocks: list[tuple[int, NormalizedBlock]],
    page: int,
    content_bbox: tuple[float, float, float, float],
) -> bool:
    for _index, block in visual_blocks:
        if block.page != page or not _has_arabic_script(block.text):
            continue
        block_bbox = _bbox(block.source_item.get("bbox"))
        if block_bbox is None:
            continue
        if _content_bbox_overlaps(block_bbox, content_bbox):
            return True
    return False


def _content_bbox_overlaps(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(
        0.0,
        min(ay1, by1) - max(ay0, by0),
    ) > 0


def _horizontal_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _pdf_arabic_lines_text_in_region(
    pdf_recovery_context: _PdfTextLayerRecoveryContext,
    *,
    page_number: int,
    content_bbox: tuple[float, float, float, float],
) -> str:
    try:
        document = pdf_recovery_context.document
        fitz = pdf_recovery_context.fitz
        page_index = page_number - 1
        if page_index < 0 or page_index >= document.page_count:
            return ""
        page = document[page_index]
        target = _scaled_bbox_to_page_rect(content_bbox, page.rect, fitz, padding=0)
        return _arabic_pdf_line_text(page, target, fitz)
    except Exception:
        return ""


def _scaled_bbox_to_page_rect(
    bbox: tuple[float, float, float, float],
    page_rect: Any,
    fitz: Any,
    *,
    padding: float | tuple[float, float] = (4, 6),
) -> Any:
    x0, y0, x1, y1 = bbox
    target = fitz.Rect(
        x0 * page_rect.width / 1000,
        y0 * page_rect.height / 1000,
        x1 * page_rect.width / 1000,
        y1 * page_rect.height / 1000,
    )
    if isinstance(padding, int | float):
        padding_x = padding_y = float(padding)
    else:
        padding_x, padding_y = float(padding[0]), float(padding[1])
    return fitz.Rect(
        max(page_rect.x0, target.x0 - padding_x),
        max(page_rect.y0, target.y0 - padding_y),
        min(page_rect.x1, target.x1 + padding_x),
        min(page_rect.y1, target.y1 + padding_y),
    )


def _overlapping_pdf_line_text(page: Any, target: Any, fitz: Any) -> str:
    candidates: list[tuple[float, float, float, str]] = []
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
            if score <= 0:
                continue
            comparable_width = min(line_rect.width, target.width)
            if comparable_width > 0 and overlap.width / comparable_width < 0.35:
                continue
            text = "".join(
                str(span.get("text") or "")
                for span in line.get("spans", [])
                if isinstance(span, dict)
            ).strip()
            if not text:
                continue
            candidates.append((line_rect.y0, line_rect.x0, score, text))
    if not candidates:
        return ""

    non_header_candidates = [
        candidate for candidate in candidates if not _looks_like_reference_header(candidate[3])
    ]
    if non_header_candidates:
        candidates = non_header_candidates
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    return "\n".join(candidate[3] for candidate in candidates)


def _arabic_pdf_line_text(page: Any, target: Any, fitz: Any) -> str:
    candidates: list[tuple[float, float, str]] = []
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
            if score <= 0:
                continue
            text = "".join(
                str(span.get("text") or "")
                for span in line.get("spans", [])
                if isinstance(span, dict)
            ).strip()
            if (
                not text
                or not _has_arabic_script(text)
                or _looks_like_reference_header(text)
            ):
                continue
            candidates.append((line_rect.y0, line_rect.x0, text))
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    return "\n".join(candidate[2] for candidate in candidates)


def _has_arabic_script(text: str) -> bool:
    return (
        re.search(
            r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]",
            text,
        )
        is not None
    )


def _has_latin_script(text: str) -> bool:
    return re.search(r"[A-Za-z]", text) is not None


def _looks_like_reference_header(text: str) -> bool:
    return (
        re.fullmatch(
            r"\s*Verse\s+\d{1,4}\s*:\s*\d{1,4}\s*",
            text,
            flags=re.IGNORECASE,
        )
        is not None
    )

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.parser_normalization import (
    VisionBlockRecoveryClient,
    VisionRecoveryConfig,
    _block_type,
    _image_data_url_for_item,
    _page_number,
    _vision_target_allows_block_type,
)
from ragstudio.services.script_detection import SCRIPT_PATTERNS

logger = logging.getLogger(__name__)

SCRIPT_MISSING_WARNING_CODES = frozenset(
    {
        "reference_unit_missing_expected_script",
        "reference_unit_missing_required_script",
    }
)


class VisionRecoveryClient(Protocol):
    async def recover_text(
        self,
        *,
        image_data_url: str,
        block_type: str,
        page: int | None,
        triggers: list[str],
        existing_text: str,
        config: VisionRecoveryConfig,
    ) -> str | None:
        raise NotImplementedError


class TargetedVisionRecoveryService:
    def __init__(
        self,
        client: VisionRecoveryClient | None = None,
        *,
        http_client_provider: HttpClientProviderProtocol | None = None,
    ) -> None:
        self.client = client or VisionBlockRecoveryClient(
            http_client_provider=http_client_provider
        )

    async def recover(
        self,
        chunks: list[AdapterChunk],
        *,
        config: VisionRecoveryConfig | None,
    ) -> dict[str, Any]:
        requests = self._recovery_requests(chunks)
        summary = {
            "targeted_vision_recovery_requests": len(requests),
            "targeted_vision_recovery_attempted": 0,
            "targeted_vision_recovery_succeeded": 0,
            "targeted_vision_recovery_failed": 0,
            "targeted_vision_recovery_not_configured": 0,
            "targeted_vision_recovery_no_evidence": 0,
            "targeted_vision_recovery_samples": [],
        }
        if not requests:
            return summary
        if config is None or not config.enabled:
            for chunk, request in requests:
                self._mark_request(request, status="not_configured")
                self._mark_matching_warnings(chunk, request, status="not_configured")
            summary["targeted_vision_recovery_not_configured"] = len(requests)
            summary["targeted_vision_recovery_samples"] = [request for _, request in requests[:25]]
            return summary

        evidence_cache: dict[tuple[Path, Path], list[dict[str, Any]]] = {}
        total_attempts = 0
        per_page_attempts: dict[int, int] = {}
        for chunk, request in requests:
            trigger = self._request_trigger(request) or "missing_required_script"
            if trigger not in config.triggers:
                self._mark_request(
                    request,
                    status="not_configured",
                    reason="trigger_not_enabled",
                )
                self._mark_matching_warnings(chunk, request, status="not_configured")
                summary["targeted_vision_recovery_not_configured"] += 1
                continue
            if total_attempts >= config.max_total_blocks:
                self._mark_request(request, status="failed", reason="max_total_blocks_reached")
                self._mark_matching_warnings(chunk, request, status="failed")
                summary["targeted_vision_recovery_failed"] += 1
                continue

            candidates = self._candidate_items(
                chunk,
                request,
                config=config,
                evidence_cache=evidence_cache,
            )
            if not candidates:
                self._mark_request(request, status="no_evidence")
                self._mark_matching_warnings(chunk, request, status="no_evidence")
                summary["targeted_vision_recovery_no_evidence"] += 1
                continue

            recovered = False
            for item, artifact_root, content_list_path in candidates:
                page = _page_number(item)
                page_key = page if page is not None else -1
                if per_page_attempts.get(page_key, 0) >= config.max_blocks_per_page:
                    continue
                data_url = _image_data_url_for_item(
                    item,
                    artifact_root=artifact_root,
                    content_list_path=content_list_path,
                    pdf_recovery_context=None,
                )
                if data_url is None:
                    continue
                block_type = _block_type(item)
                total_attempts += 1
                per_page_attempts[page_key] = per_page_attempts.get(page_key, 0) + 1
                summary["targeted_vision_recovery_attempted"] += 1
                try:
                    recovered_text = await self.client.recover_text(
                        image_data_url=data_url,
                        block_type=block_type,
                        page=page,
                        triggers=[trigger],
                        existing_text=chunk.text,
                        config=config,
                    )
                except Exception:
                    logger.exception("Targeted vision recovery failed.")
                    recovered_text = None
                if not self._recovered_text_satisfies(request, recovered_text):
                    continue
                self._append_recovered_text(
                    chunk,
                    recovered_text=str(recovered_text),
                    request=request,
                    item=item,
                    config=config,
                )
                recovered = True
                summary["targeted_vision_recovery_succeeded"] += 1
                break

            if not recovered:
                self._mark_request(request, status="failed")
                self._mark_matching_warnings(chunk, request, status="failed")
                summary["targeted_vision_recovery_failed"] += 1

        summary["targeted_vision_recovery_samples"] = [
            request for _, request in requests[:25]
        ]
        return summary

    def _recovery_requests(
        self,
        chunks: list[AdapterChunk],
    ) -> list[tuple[AdapterChunk, dict[str, Any]]]:
        requests: list[tuple[AdapterChunk, dict[str, Any]]] = []
        for chunk in chunks:
            repair = chunk.metadata.get("quality_repair")
            if not isinstance(repair, dict):
                continue
            chunk_requests = repair.get("targeted_vision_recovery_requests")
            if not isinstance(chunk_requests, list):
                continue
            for request in chunk_requests:
                if isinstance(request, dict):
                    requests.append((chunk, request))
        return requests

    def _candidate_items(
        self,
        chunk: AdapterChunk,
        request: dict[str, Any],
        *,
        config: VisionRecoveryConfig,
        evidence_cache: dict[tuple[Path, Path], list[dict[str, Any]]],
    ) -> list[tuple[dict[str, Any], Path, Path]]:
        artifact_root, content_list_path = self._content_list_paths(chunk)
        if artifact_root is None or content_list_path is None:
            return []
        cache_key = (artifact_root, content_list_path)
        if cache_key not in evidence_cache:
            evidence_cache[cache_key] = self._read_content_list(content_list_path)
        items = evidence_cache[cache_key]
        source_indices = self._source_block_indices(chunk, content_list_path)
        page_start = self._int_value(request.get("page_start"))
        page_end = self._int_value(request.get("page_end")) or page_start
        candidates: list[tuple[dict[str, Any], Path, Path]] = []
        for index, item in enumerate(items):
            if source_indices and index not in source_indices:
                continue
            block_type = _block_type(item)
            if not _vision_target_allows_block_type(block_type, config.target_block_types):
                continue
            page = _page_number(item)
            if not self._page_matches(page, page_start, page_end):
                continue
            candidates.append((item, artifact_root, content_list_path))
        if candidates or not source_indices:
            return candidates
        for item in items:
            block_type = _block_type(item)
            if not _vision_target_allows_block_type(block_type, config.target_block_types):
                continue
            page = _page_number(item)
            if self._page_matches(page, page_start, page_end):
                candidates.append((item, artifact_root, content_list_path))
        return candidates

    def _content_list_paths(self, chunk: AdapterChunk) -> tuple[Path | None, Path | None]:
        parser_metadata = chunk.metadata.get("parser_metadata")
        if not isinstance(parser_metadata, dict):
            return None, None
        artifact_extract_dir = parser_metadata.get("artifact_extract_dir")
        content_list_ref = parser_metadata.get("content_list_ref")
        if not isinstance(artifact_extract_dir, str) or not artifact_extract_dir:
            return None, None
        if not isinstance(content_list_ref, str) or not content_list_ref:
            return None, None
        artifact_root = Path(artifact_extract_dir).resolve()
        content_list_path = (artifact_root / content_list_ref).resolve()
        try:
            content_list_path.relative_to(artifact_root)
        except ValueError:
            return None, None
        if not content_list_path.is_file():
            return None, None
        return artifact_root, content_list_path

    def _read_content_list(self, content_list_path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _source_block_indices(self, chunk: AdapterChunk, content_list_path: Path) -> set[int]:
        provenance = chunk.metadata.get("provenance")
        if not isinstance(provenance, dict):
            return set()
        blocks = provenance.get("blocks")
        if not isinstance(blocks, list):
            return set()
        content_ref = content_list_path.name
        indices: set[int] = set()
        for block in blocks:
            if not isinstance(block, dict):
                continue
            source_ref = block.get("source_block_ref")
            if not isinstance(source_ref, str):
                continue
            ref_content, _, ref_index = source_ref.partition(":block:")
            if Path(ref_content).name != content_ref:
                continue
            try:
                indices.add(int(ref_index))
            except ValueError:
                continue
        return indices

    def _append_recovered_text(
        self,
        chunk: AdapterChunk,
        *,
        recovered_text: str,
        request: dict[str, Any],
        item: dict[str, Any],
        config: VisionRecoveryConfig,
    ) -> None:
        cleaned = recovered_text.strip()
        if cleaned and cleaned not in chunk.text:
            object.__setattr__(chunk, "text", "\n\n".join([chunk.text.strip(), cleaned]).strip())
        source = f"vision_model:{config.model}"
        self._mark_request(
            request,
            status="succeeded",
            source=source,
            recovered_text_chars=len(cleaned),
            page=_page_number(item),
            block_type=_block_type(item),
        )
        self._mark_matching_warnings(
            chunk,
            request,
            status="succeeded",
            source=source,
        )
        self._append_recovery_provenance(
            chunk,
            recovered_text=cleaned,
            source=source,
            item=item,
        )

    def _append_recovery_provenance(
        self,
        chunk: AdapterChunk,
        *,
        recovered_text: str,
        source: str,
        item: dict[str, Any],
    ) -> None:
        provenance = chunk.metadata.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
            chunk.metadata["provenance"] = provenance
        blocks = provenance.get("blocks")
        if not isinstance(blocks, list):
            blocks = []
            provenance["blocks"] = blocks
        blocks.append(
            {
                "role": "targeted_vision_recovery",
                "block_type": _block_type(item),
                "page_start": _page_number(item),
                "page_end": _page_number(item),
                "recovery_source": source,
                "text_preview": recovered_text[:240],
            }
        )

    def _mark_matching_warnings(
        self,
        chunk: AdapterChunk,
        request: dict[str, Any],
        *,
        status: str,
        source: str | None = None,
    ) -> None:
        extraction_quality = chunk.metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            return
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list):
            return
        reference = request.get("reference")
        missing_scripts = {
            script for script in request.get("missing_scripts", []) if isinstance(script, str)
        }
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            if warning.get("code") not in SCRIPT_MISSING_WARNING_CODES:
                continue
            if reference and warning.get("reference") not in {None, reference}:
                continue
            expected_script = warning.get("expected_script") or warning.get("required_script")
            if missing_scripts and expected_script not in missing_scripts:
                continue
            warning["vision_recovery_status"] = status
            if status == "succeeded":
                warning["severity"] = "info"
                warning["suppressed_from_counts"] = True
                warning["quality_gate_action"] = "accepted_recovery"
                warning["action"] = "targeted_vision_recovery_succeeded"
                warning["vision_recovery_required"] = False
                if source:
                    warning["recovery_source"] = source
            elif status in {"not_configured", "no_evidence", "failed"}:
                warning["vision_recovery_required"] = True

    def _mark_request(
        self,
        request: dict[str, Any],
        *,
        status: str,
        reason: str | None = None,
        source: str | None = None,
        recovered_text_chars: int | None = None,
        page: int | None = None,
        block_type: str | None = None,
    ) -> None:
        request["vision_recovery_status"] = status
        if reason:
            request["vision_recovery_reason"] = reason
        if source:
            request["recovery_source"] = source
        if recovered_text_chars is not None:
            request["recovered_text_chars"] = recovered_text_chars
        if page is not None:
            request["recovery_page"] = page
        if block_type:
            request["recovery_block_type"] = block_type

    def _recovered_text_satisfies(
        self,
        request: dict[str, Any],
        recovered_text: str | None,
    ) -> bool:
        if not isinstance(recovered_text, str) or not recovered_text.strip():
            return False
        missing_scripts = [
            script for script in request.get("missing_scripts", []) if isinstance(script, str)
        ]
        for script in missing_scripts:
            pattern = SCRIPT_PATTERNS.get(script)
            if pattern is None or not pattern.search(recovered_text):
                return False
        return True

    def _request_trigger(self, request: dict[str, Any]) -> str | None:
        trigger = request.get("trigger")
        if not isinstance(trigger, str) or not trigger.strip():
            return None
        return trigger.strip()

    def _page_matches(
        self,
        page: int | None,
        page_start: int | None,
        page_end: int | None,
    ) -> bool:
        if page_start is None:
            return True
        if page is None:
            return False
        upper = page_end if page_end is not None else page_start
        return page_start <= page <= upper

    def _int_value(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        return value if isinstance(value, int) else None

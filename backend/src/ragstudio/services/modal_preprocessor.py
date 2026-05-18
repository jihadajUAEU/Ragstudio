from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ragstudio.schemas.parsing import DomainMetadata
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.modal_router import StudioModalRouter

MODAL_ROUTER_PROCESSED_FLAG = "modal_router_processed"


class ModalPreprocessor:
    def preprocess(
        self,
        adapter_chunks: list[AdapterChunk],
        *,
        domain_metadata: DomainMetadata,
    ) -> list[AdapterChunk]:
        if not adapter_chunks:
            return adapter_chunks

        if adapter_chunks[0].metadata.get(MODAL_ROUTER_PROCESSED_FLAG) is True:
            return adapter_chunks

        parser_metadata = adapter_chunks[0].metadata.get("parser_metadata", {})
        if not isinstance(parser_metadata, dict):
            return adapter_chunks

        extract_dir = parser_metadata.get("artifact_extract_dir")
        content_ref = parser_metadata.get("content_list_ref")
        if not isinstance(extract_dir, str) or not isinstance(content_ref, str):
            return adapter_chunks
        if not extract_dir.strip() or not content_ref.strip():
            return adapter_chunks
        if not self._has_shared_content_list(adapter_chunks, extract_dir, content_ref):
            return adapter_chunks

        root = Path(extract_dir).resolve()
        target = (root / content_ref).resolve()
        try:
            target.relative_to(root)
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return adapter_chunks
        except (OSError, ValueError):
            return adapter_chunks

        modal_blocks = StudioModalRouter().route(data, domain_metadata=domain_metadata)

        results: list[AdapterChunk] = []
        for index, block in enumerate(modal_blocks):
            metadata: dict[str, Any] = {
                "parser_metadata": dict(parser_metadata),
                MODAL_ROUTER_PROCESSED_FLAG: True,
                "modality": block.modality.value,
                "structured_data": block.structured_data,
                "chunk_index": index,
            }
            if block.page is not None:
                metadata["page"] = block.page
            if block.warnings:
                metadata["extraction_quality"] = {"parser_warnings": block.warnings}

            results.append(
                AdapterChunk(
                    text=block.text,
                    source_location={"artifact": content_ref, "block_index": index},
                    metadata=metadata,
                    runtime_source_id=adapter_chunks[0].runtime_source_id,
                    content_type="application/json",
                    preview_ref=adapter_chunks[0].preview_ref,
                )
            )

        return results if results else adapter_chunks

    def _has_shared_content_list(
        self,
        adapter_chunks: list[AdapterChunk],
        extract_dir: str,
        content_ref: str,
    ) -> bool:
        for chunk in adapter_chunks:
            parser_metadata = chunk.metadata.get("parser_metadata", {})
            if not isinstance(parser_metadata, dict):
                return False
            if parser_metadata.get("artifact_extract_dir") != extract_dir:
                return False
            if parser_metadata.get("content_list_ref") != content_ref:
                return False
        return True

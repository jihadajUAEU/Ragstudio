from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ragstudio.services.adapter import AdapterChunk


@dataclass(frozen=True)
class LayoutRepairDiagnostic:
    chunk_index: int
    code: str
    detail: str
    before: dict[str, Any]
    after: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "code": self.code,
            "detail": self.detail,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class LayoutAutoRepairResult:
    chunks: list[AdapterChunk]
    diagnostics: list[LayoutRepairDiagnostic]

    @property
    def repaired_count(self) -> int:
        return len({diagnostic.chunk_index for diagnostic in self.diagnostics})

    def diagnostics_payload(self) -> dict[str, Any]:
        return {
            "version": 1,
            "strategy": "local_layout_auto_repair",
            "repaired_count": self.repaired_count,
            "diagnostics": [diagnostic.as_dict() for diagnostic in self.diagnostics],
        }


class LayoutAutoRepairService:
    def repair(self, chunks: list[AdapterChunk]) -> LayoutAutoRepairResult:
        repaired_chunks: list[AdapterChunk] = []
        diagnostics: list[LayoutRepairDiagnostic] = []

        for index, chunk in enumerate(chunks):
            source_location = dict(chunk.source_location or {})
            chunk_diagnostics = self._repair_source_location(index, source_location)
            diagnostics.extend(chunk_diagnostics)

            if not chunk_diagnostics:
                repaired_chunks.append(chunk)
                continue

            metadata = dict(chunk.metadata)
            metadata["layout_auto_repair"] = {
                "version": 1,
                "strategy": "local_layout_auto_repair",
                "diagnostics": [
                    diagnostic.as_dict() for diagnostic in chunk_diagnostics
                ],
            }
            repaired_chunks.append(
                AdapterChunk(
                    text=chunk.text,
                    source_location=source_location,
                    metadata=metadata,
                    runtime_source_id=chunk.runtime_source_id,
                    content_type=chunk.content_type,
                    preview_ref=chunk.preview_ref,
                )
            )

        return LayoutAutoRepairResult(chunks=repaired_chunks, diagnostics=diagnostics)

    def _repair_source_location(
        self,
        chunk_index: int,
        source_location: dict[str, Any],
    ) -> list[LayoutRepairDiagnostic]:
        diagnostics: list[LayoutRepairDiagnostic] = []

        page = self._positive_int(source_location.get("page"))
        page_start = self._positive_int(source_location.get("page_start"))
        page_end = self._positive_int(source_location.get("page_end"))

        if page_start is None and page_end is None and page is not None:
            before = self._source_location_snapshot(source_location)
            source_location["page_start"] = page
            source_location["page_end"] = page
            source_location.pop("page", None)
            diagnostics.append(
                LayoutRepairDiagnostic(
                    chunk_index=chunk_index,
                    code="single_page_promoted_to_range",
                    detail="Promoted explicit page metadata to an equivalent page range.",
                    before=before,
                    after=self._source_location_snapshot(source_location),
                )
            )
            page_start = page
            page_end = page

        if page_start is not None and page_end is None:
            before = self._source_location_snapshot(source_location)
            source_location["page_end"] = page_start
            source_location.pop("page", None)
            diagnostics.append(
                LayoutRepairDiagnostic(
                    chunk_index=chunk_index,
                    code="missing_page_end_filled",
                    detail="Filled missing page_end from explicit page_start.",
                    before=before,
                    after=self._source_location_snapshot(source_location),
                )
            )
            page_end = page_start

        if page_end is not None and page_start is None:
            before = self._source_location_snapshot(source_location)
            source_location["page_start"] = page_end
            source_location.pop("page", None)
            diagnostics.append(
                LayoutRepairDiagnostic(
                    chunk_index=chunk_index,
                    code="missing_page_start_filled",
                    detail="Filled missing page_start from explicit page_end.",
                    before=before,
                    after=self._source_location_snapshot(source_location),
                )
            )
            page_start = page_end

        if page_start is not None and page_end is not None and page_start > page_end:
            before = self._source_location_snapshot(source_location)
            source_location["page_start"] = page_end
            source_location["page_end"] = page_start
            source_location.pop("page", None)
            diagnostics.append(
                LayoutRepairDiagnostic(
                    chunk_index=chunk_index,
                    code="page_range_reordered",
                    detail="Reordered an inverted page range.",
                    before=before,
                    after=self._source_location_snapshot(source_location),
                )
            )
            page_start, page_end = page_end, page_start

        if (
            page is not None
            and "page" in source_location
            and (page_start is not None or page_end is not None)
        ):
            before = self._source_location_snapshot(source_location)
            source_location.pop("page", None)
            diagnostics.append(
                LayoutRepairDiagnostic(
                    chunk_index=chunk_index,
                    code="redundant_page_removed",
                    detail=(
                        "Removed stale page metadata because page_start/page_end is "
                        "authoritative."
                    ),
                    before=before,
                    after=self._source_location_snapshot(source_location),
                )
            )

        return diagnostics

    def _positive_int(self, value: Any) -> int | None:
        if type(value) is int and value >= 1:
            return value
        return None

    def _source_location_snapshot(self, source_location: dict[str, Any]) -> dict[str, Any]:
        return {
            key: source_location[key]
            for key in ("page", "page_start", "page_end", "reference", "artifact")
            if key in source_location
        }

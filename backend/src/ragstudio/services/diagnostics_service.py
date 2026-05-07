from typing import Any

from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.adapter import RAGAnythingAdapter


class DiagnosticsService:
    def __init__(self, adapter: RAGAnythingAdapter | None = None):
        self.adapter = adapter or RAGAnythingAdapter()

    def get_diagnostics(self) -> DiagnosticsOut:
        report = self.adapter.capability_report()
        raganything_available = bool(report.get("raganything_available"))
        warnings = []
        if not raganything_available:
            warnings.append("raganything dependency is not available; using fallback adapter.")

        return DiagnosticsOut(
            capabilities={
                "raganything_available": raganything_available,
                "fallback_active": report.get("active_backend") == "fallback",
                "indexing": bool(report.get("indexing")),
                "query": bool(report.get("query")),
                "graph": bool(report.get("graph")),
            },
            dependency_status=self._dependency_status(report),
            warnings=warnings,
        )

    def _dependency_status(self, report: dict[str, Any]) -> dict[str, Any]:
        return {
            "raganything": "available" if report.get("raganything_available") else "missing",
            "active_backend": report.get("active_backend"),
            "indexing": report.get("indexing"),
            "query": report.get("query"),
            "graph": report.get("graph"),
        }

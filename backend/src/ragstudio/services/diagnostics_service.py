from typing import Any

from ragstudio.config import AppSettings
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.schemas.runtime import RuntimeOverallStatus
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy.ext.asyncio import AsyncSession


class DiagnosticsService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        settings: AppSettings | None = None,
        adapter: RAGAnythingAdapter | None = None,
        health_service: RuntimeHealthService | None = None,
    ):
        self.session = session
        self.settings = settings
        self.adapter = adapter or RAGAnythingAdapter()
        self.health_service = health_service

    def get_diagnostics(self) -> Any:
        if self.session is None or self.settings is None:
            return self._legacy_diagnostics()
        return self._get_diagnostics_async(self.session, self.settings)

    async def _get_diagnostics_async(
        self,
        session: AsyncSession,
        settings: AppSettings,
    ) -> DiagnosticsOut:
        report = self.adapter.capability_report()
        profile = None
        warnings = []
        try:
            profile = await RuntimeProfileService(
                session,
                settings,
            ).get_active_profile()
        except RuntimeProfileNotConfiguredError as exc:
            warnings.append(str(exc))

        health_service = self.health_service or RuntimeHealthService(
            session,
            verify_storage=True,
        )
        checks = await health_service.check(profile)
        blocking = health_service.blocking_failures(checks)
        runtime_mode = profile.runtime_mode if profile else "fallback"
        overall_status = self._overall_status(runtime_mode, checks, blocking)
        dependency_report = (
            report
            if runtime_mode == "fallback"
            else self._runtime_dependency_report(checks, blocking)
        )
        raganything_available = bool(dependency_report.get("raganything_available"))

        if not raganything_available:
            warnings.append(
                "raganything runtime dependencies are not importable in this Python "
                "environment; runtime mode cannot execute. Run ./scripts/setup.sh."
            )
        if runtime_mode == "fallback":
            warnings.append(
                "Graph is unavailable because fallback mode uses the local placeholder "
                "adapter. Native graph support requires runtime mode with healthy "
                "RAG-Anything and Neo4j dependencies."
            )

        return DiagnosticsOut(
            capabilities={
                "raganything_available": raganything_available,
                "fallback_active": runtime_mode == "fallback",
                "indexing": not blocking,
                "query": not blocking,
                "graph": dependency_report.get("graph") == "neo4j",
                "native_scoped_query": dependency_report.get("native_scoped_query") is True,
                "scoped_query_fallback": (
                    dependency_report.get("scoped_query") == "mirrored_chunks_fallback"
                ),
            },
            dependency_status=self._dependency_status(dependency_report),
            warnings=warnings,
            runtime_mode=runtime_mode,
            overall_status=overall_status,
            checks=checks,
        )

    def _legacy_diagnostics(self) -> DiagnosticsOut:
        report = self.adapter.capability_report()
        raganything_available = bool(report.get("raganything_available"))
        warnings = []
        if not raganything_available:
            warnings.append(
                "raganything runtime dependencies are not importable in this Python "
                "environment; running the local fallback adapter. Run ./scripts/setup.sh or "
                "python -m pip install -e 'backend[dev]' to enable the package."
            )

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
            "native_scoped_query": report.get("native_scoped_query"),
            "scoped_query": report.get("scoped_query"),
            "scoped_query_detail": report.get("scoped_query_detail"),
        }

    def _runtime_dependency_report(
        self,
        checks: list[Any],
        blocking: list[Any],
    ) -> dict[str, Any]:
        by_name = {item.name: item for item in checks}
        runtime_available = not blocking
        graph_available = (
            runtime_available
            and by_name.get("neo4j") is not None
            and by_name["neo4j"].status == "ok"
        )
        raganything_available = (
            by_name.get("raganything") is not None
            and by_name["raganything"].status == "ok"
        )
        return {
            "raganything_available": raganything_available,
            "active_backend": "runtime",
            "indexing": "raganything" if runtime_available else "unavailable",
            "query": "raganything" if runtime_available else "unavailable",
            "graph": "neo4j" if graph_available else "unavailable",
            "native_scoped_query": runtime_available,
            "scoped_query": (
                "raganything_full_doc_id_vector" if runtime_available else "unavailable"
            ),
            "scoped_query_detail": (
                "Native RAG-Anything query scopes selected documents through LightRAG "
                "chunk full_doc_id filtering with vector retrieval; graph modes are not "
                "used under document scope."
                if runtime_available
                else "Native RAG-Anything scoped query is unavailable because runtime "
                "health checks are blocking."
            ),
        }

    def _overall_status(
        self,
        runtime_mode: str,
        checks: list[Any],
        blocking: list[Any],
    ) -> RuntimeOverallStatus:
        if runtime_mode == "fallback":
            return "fallback"
        if blocking:
            return "failed"
        if any(item.status == "warning" for item in checks):
            return "degraded"
        return "ready"

from typing import Any

from ragstudio.config import AppSettings
from ragstudio.db.models import GraphProjectionRecord
from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.schemas.runtime import RuntimeOverallStatus
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)
from sqlalchemy import select
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
        profile = None
        warnings = []
        try:
            profile = await RuntimeProfileService(
                session,
                settings,
            ).get_active_profile()
        except (RuntimeProfileNotConfiguredError, ValueError) as exc:
            warnings.append(str(exc))

        health_service = self.health_service or RuntimeHealthService(
            session,
            verify_storage=True,
        )
        checks = await health_service.check(profile)
        blocking = health_service.blocking_failures(checks)
        runtime_mode = profile.runtime_mode if profile else "runtime"
        overall_status = self._overall_status(runtime_mode, checks, blocking)
        dependency_report = self._runtime_dependency_report(checks, blocking)
        dependency_report.update(
            await self._graph_projection_report(
                session,
                runtime_profile_id=profile.id if profile else None,
            )
        )
        raganything_available = bool(dependency_report.get("raganything_available"))

        if not raganything_available:
            warnings.append(
                "raganything runtime dependencies are not importable in this Python "
                "environment; runtime mode cannot execute. Run ./scripts/setup.sh."
            )
        graph_projection = dependency_report.get("graph_projection")
        if graph_projection in {"pending", "failed", "skipped"}:
            detail = dependency_report.get("graph_projection_detail")
            suffix = f": {detail}" if detail else "."
            if graph_projection in {"failed", "skipped"}:
                warnings.append(f"Graph projection {graph_projection}{suffix}")
            else:
                warnings.append(f"Graph projection is {graph_projection}{suffix}")

        return DiagnosticsOut(
            capabilities={
                "raganything_available": raganything_available,
                "fallback_active": False,
                "indexing": self._capability_available(dependency_report.get("indexing")),
                "query": self._capability_available(dependency_report.get("query")),
                "graph": dependency_report.get("graph") in {"neo4j", "relationship_metadata"},
            },
            dependency_status=self._dependency_status(dependency_report),
            warnings=warnings,
            runtime_mode=runtime_mode,
            overall_status=overall_status,
            checks=checks,
        )

    def _legacy_diagnostics(self) -> DiagnosticsOut:
        report = self._fallback_dependency_report(
            self.adapter.capability_report(),
            graph="unavailable",
        )
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
                "fallback_active": report.get("active_backend") in {"fallback", "local_parser"},
                "indexing": self._capability_available(report.get("indexing")),
                "query": self._capability_available(report.get("query")),
                "graph": report.get("graph") == "relationship_metadata",
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
            "graph_projection": report.get("graph_projection"),
            "graph_projection_detail": report.get("graph_projection_detail"),
            "native_scoped_query": report.get("native_scoped_query"),
            "scoped_query": report.get("scoped_query"),
            "scoped_query_detail": report.get("scoped_query_detail"),
        }

    def _fallback_dependency_report(
        self,
        report: dict[str, Any],
        *,
        graph: str,
    ) -> dict[str, Any]:
        return {
            **report,
            "active_backend": report.get("active_backend") or "local_parser",
            "indexing": report.get("indexing") or "line_split_local",
            "query": "unavailable",
            "graph": graph,
            "native_scoped_query": False,
            "scoped_query": "unavailable",
            "scoped_query_detail": (
                "Native runtime query is unavailable while runtime mode is inactive."
            ),
        }

    def _capability_available(self, value: Any) -> bool:
        return value not in {None, False, "unavailable"}

    def _runtime_dependency_report(
        self,
        checks: list[Any],
        blocking: list[Any],
    ) -> dict[str, Any]:
        by_name = {item.name: item for item in checks}
        runtime_available = bool(checks) and not blocking and not any(
            item.status == "skipped" for item in checks
        )
        graph_available = (
            runtime_available
            and by_name.get("neo4j") is not None
            and by_name["neo4j"].status == "ok"
        )
        raganything_available = (
            by_name.get("raganything") is not None and by_name["raganything"].status == "ok"
        )
        scoped_query: str = "requires_storage_verification"
        native_scoped_query: bool | str = "conditional"
        scoped_query_detail = (
            "Selected-document native query requires LightRAG chunk storage with "
            "full_doc_id filtering support; the storage backend is verified when "
            "a scoped query initializes LightRAG."
        )
        if not runtime_available:
            scoped_query = "unavailable"
            native_scoped_query = False
            scoped_query_detail = (
                "Selected-document native query is unavailable until runtime dependencies "
                "are healthy."
            )
        return {
            "raganything_available": raganything_available,
            "active_backend": "runtime",
            "indexing": "raganything" if runtime_available else "unavailable",
            "query": "raganything" if runtime_available else "unavailable",
            "graph": "neo4j" if graph_available else "unavailable",
            "native_scoped_query": native_scoped_query,
            "scoped_query": scoped_query,
            "scoped_query_detail": scoped_query_detail,
        }

    async def _graph_projection_report(
        self,
        session: AsyncSession,
        *,
        runtime_profile_id: str | None = None,
    ) -> dict[str, Any]:
        statement = select(GraphProjectionRecord)
        if runtime_profile_id is not None:
            statement = statement.where(
                GraphProjectionRecord.runtime_profile_id == runtime_profile_id
            )
        record = await session.scalar(
            statement.order_by(GraphProjectionRecord.created_at.desc()).limit(1)
        )
        if record is None:
            return {}
        detail = None
        if record.error:
            detail = record.error
        elif record.status == "succeeded":
            detail = f"{record.node_count} nodes, {record.edge_count} edges"
        return {
            "graph_projection": record.status,
            "graph_projection_detail": detail,
        }

    def _overall_status(
        self,
        runtime_mode: str,
        checks: list[Any],
        blocking: list[Any],
    ) -> RuntimeOverallStatus:
        if runtime_mode == "fallback":
            return "failed"
        if blocking:
            return "failed"
        if any(item.status == "warning" for item in checks):
            return "degraded"
        return "ready"

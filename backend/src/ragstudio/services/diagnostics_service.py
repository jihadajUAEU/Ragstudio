from typing import Any

from ragstudio.schemas.diagnostics import DiagnosticsOut
from ragstudio.services.adapter import RAGAnythingAdapter
from ragstudio.services.runtime_health_service import RuntimeHealthService
from ragstudio.services.runtime_profile_service import (
    RuntimeProfileNotConfiguredError,
    RuntimeProfileService,
)


class DiagnosticsService:
    def __init__(
        self,
        session: Any | None = None,
        settings: Any | None = None,
        adapter: RAGAnythingAdapter | None = None,
        health_service: RuntimeHealthService | None = None,
    ):
        self.session = session
        self.settings = settings
        self.adapter = adapter or RAGAnythingAdapter()
        self.health_service = health_service or RuntimeHealthService()

    def get_diagnostics(self) -> Any:
        if self.session is None or self.settings is None:
            return self._legacy_diagnostics()
        return self._get_diagnostics_async()

    async def _get_diagnostics_async(self) -> DiagnosticsOut:
        report = self.adapter.capability_report()
        profile = None
        warnings = []
        try:
            profile = await RuntimeProfileService(
                self.session,
                self.settings,
            ).get_active_profile()
        except RuntimeProfileNotConfiguredError as exc:
            warnings.append(str(exc))

        checks = await self.health_service.check(profile)
        blocking = self.health_service.blocking_failures(checks)
        runtime_mode = profile.runtime_mode if profile else "fallback"
        overall_status = self._overall_status(runtime_mode, checks, blocking)
        raganything_available = bool(report.get("raganything_available"))

        if not raganything_available:
            warnings.append(
                "raganything dependency is not installed in this Python environment; runtime "
                "mode cannot execute."
            )

        return DiagnosticsOut(
            capabilities={
                "raganything_available": raganything_available,
                "fallback_active": runtime_mode == "fallback",
                "indexing": not blocking,
                "query": not blocking,
                "graph": any(
                    item.name == "neo4j" and item.status == "ok" for item in checks
                ),
            },
            dependency_status=self._dependency_status(report),
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
                "raganything dependency is not installed in this Python environment; "
                "running the local fallback adapter. Run ./scripts/setup.sh or "
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
        }

    def _overall_status(self, runtime_mode: str, checks: list[Any], blocking: list[Any]) -> str:
        if runtime_mode == "fallback":
            return "fallback"
        if blocking:
            return "failed"
        if any(item.status == "warning" for item in checks):
            return "degraded"
        return "ready"

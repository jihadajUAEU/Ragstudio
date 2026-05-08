import asyncio
from collections.abc import Iterable
from importlib import import_module
from typing import Any

from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeProfile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RuntimeHealthService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        verify_storage: bool = False,
        neo4j_driver_factory: Any | None = None,
    ):
        self.session = session
        self.verify_storage = verify_storage
        self.neo4j_driver_factory = neo4j_driver_factory

    async def check(self, profile: RuntimeProfile | None) -> list[RuntimeHealthCheck]:
        if profile is None:
            return [
                RuntimeHealthCheck(
                    name="runtime_profile",
                    status="skipped",
                    detail=(
                        "Default runtime profile is not configured; legacy fallback "
                        "indexing and querying remain active."
                    ),
                    remediation=(
                        "Save Settings only when you want to configure a native "
                        "RAG-Anything runtime."
                    ),
                )
            ]

        if profile.runtime_mode == "fallback":
            return [
                RuntimeHealthCheck(
                    name="runtime_mode",
                    status="skipped",
                    detail=(
                        "Explicit fallback mode is active; native RAG-Anything checks "
                        "are skipped."
                    ),
                )
            ]

        return [
            self._package_check("raganything", "RAG-Anything package"),
            self._package_check("lightrag", "LightRAG package"),
            RuntimeHealthCheck(
                name="native_runtime_adapter",
                status="failed",
                severity="blocking",
                detail=(
                    "Native RAG-Anything adapter mapping is not implemented yet; "
                    "use fallback mode until the upstream adapter is completed."
                ),
                error_type="runtime_adapter_not_implemented",
                remediation="Set runtime mode to fallback or implement the native adapter.",
            ),
            self._required_url_check("llm", profile.llm_base_url, "LLM base URL"),
            self._vision_check(profile),
            self._required_url_check(
                "embedding",
                profile.embedding_base_url,
                "Embedding base URL",
            ),
            self._reranker_check(profile),
            await self._pgvector_check(profile),
            await self._neo4j_check(profile),
            self._required_text_check("parser", profile.parser, "Parser"),
        ]

    def blocking_failures(
        self,
        checks: Iterable[RuntimeHealthCheck],
    ) -> list[RuntimeHealthCheck]:
        return [
            item
            for item in checks
            if item.status == "failed" and item.severity == "blocking"
        ]

    def _package_check(self, module: str, label: str) -> RuntimeHealthCheck:
        try:
            import_module(module)
        except Exception as exc:
            return RuntimeHealthCheck(
                name=module,
                status="failed",
                severity="blocking",
                detail=f"{label} is not importable in this Python environment: {exc}",
                error_type="dependency_import",
                remediation="Run ./scripts/setup.sh.",
            )
        return RuntimeHealthCheck(
            name=module,
            status="ok",
            detail=f"{label} is importable.",
        )

    def _required_url_check(
        self,
        name: str,
        value: str | None,
        label: str,
    ) -> RuntimeHealthCheck:
        if not value:
            return RuntimeHealthCheck(
                name=name,
                status="failed",
                severity="blocking",
                detail=f"{label} is not configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(
            name=name,
            status="ok",
            detail=f"{label} is configured.",
        )

    def _required_text_check(
        self,
        name: str,
        value: str | None,
        label: str,
    ) -> RuntimeHealthCheck:
        if not value:
            return RuntimeHealthCheck(
                name=name,
                status="failed",
                severity="blocking",
                detail=f"{label} is not configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(
            name=name,
            status="ok",
            detail=f"{label} is configured.",
        )

    async def _pgvector_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if not profile.pgvector_schema:
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail="PGVector schema is not configured.",
                error_type="configuration",
            )
        if not self.verify_storage:
            return RuntimeHealthCheck(
                name="pgvector",
                status="warning",
                severity="warning",
                detail="PGVector schema is configured; connectivity was not verified.",
            )
        if self.session is None:
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail="PGVector connectivity cannot be verified without a database session.",
                error_type="storage_health_unavailable",
            )

        bind = self.session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else "unknown"
        if dialect_name != "postgresql":
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail=(
                    "PGVector requires the metadata database to use PostgreSQL; "
                    f"active dialect is {dialect_name}."
                ),
                error_type="storage_backend_mismatch",
            )

        try:
            extension_ready = await self.session.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
            schema_ready = await self.session.scalar(
                text(
                    """
                    SELECT 1
                    FROM information_schema.schemata
                    WHERE schema_name = :schema
                    """
                ),
                {"schema": profile.pgvector_schema},
            )
        except Exception as exc:
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail=f"PGVector health check failed: {exc}",
                error_type="storage_connectivity",
            )

        if extension_ready != 1:
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail="PostgreSQL vector extension is not installed.",
                error_type="storage_extension_missing",
                remediation="Run CREATE EXTENSION IF NOT EXISTS vector on the Ragstudio database.",
            )
        if schema_ready != 1:
            return RuntimeHealthCheck(
                name="pgvector",
                status="failed",
                severity="blocking",
                detail=f"PGVector schema '{profile.pgvector_schema}' does not exist.",
                error_type="storage_schema_missing",
            )
        return RuntimeHealthCheck(
            name="pgvector",
            status="ok",
            detail="PGVector extension and schema are reachable.",
        )

    async def _neo4j_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if not profile.neo4j_uri:
            return RuntimeHealthCheck(
                name="neo4j",
                status="failed",
                severity="blocking",
                detail="Neo4j URI is not configured.",
                error_type="configuration",
            )
        if not self.verify_storage:
            return RuntimeHealthCheck(
                name="neo4j",
                status="warning",
                severity="warning",
                detail="Neo4j URI is configured; connectivity was not verified.",
            )

        if (profile.neo4j_username and not profile.neo4j_password) or (
            profile.neo4j_password and not profile.neo4j_username
        ):
            return RuntimeHealthCheck(
                name="neo4j",
                status="failed",
                severity="blocking",
                detail="Neo4j username and password must be configured together.",
                error_type="configuration",
            )

        try:
            if self.neo4j_driver_factory is None:
                graph_database = import_module("neo4j").GraphDatabase
                driver_factory = graph_database.driver
            else:
                driver_factory = self.neo4j_driver_factory
        except Exception as exc:
            return RuntimeHealthCheck(
                name="neo4j",
                status="failed",
                severity="blocking",
                detail=f"Neo4j driver is not importable: {exc}",
                error_type="dependency_import",
            )

        auth = None
        if profile.neo4j_username or profile.neo4j_password:
            auth = (profile.neo4j_username or "", profile.neo4j_password or "")

        driver = None
        try:
            driver = driver_factory(
                profile.neo4j_uri,
                auth=auth,
                connection_timeout=3.0,
                max_transaction_retry_time=1.0,
            )
            await asyncio.wait_for(
                asyncio.to_thread(driver.verify_connectivity),
                timeout=5.0,
            )
        except Exception as exc:
            return RuntimeHealthCheck(
                name="neo4j",
                status="failed",
                severity="blocking",
                detail=f"Neo4j health check failed: {exc}",
                error_type="storage_connectivity",
            )
        finally:
            if driver is not None:
                await asyncio.to_thread(driver.close)

        return RuntimeHealthCheck(
            name="neo4j",
            status="ok",
            detail="Neo4j connectivity and authentication succeeded.",
        )

    def _vision_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if "vision" in profile.llm_capabilities:
            return RuntimeHealthCheck(
                name="vision",
                status="ok",
                detail="Vision is available through the configured LLM endpoint.",
            )
        if profile.vision_base_url:
            return RuntimeHealthCheck(
                name="vision",
                status="ok",
                detail="Vision endpoint is configured.",
            )
        return RuntimeHealthCheck(
            name="vision",
            status="warning",
            severity="warning",
            detail="No vision-capable endpoint is configured.",
            error_type="capability_mismatch",
        )

    def _reranker_check(self, profile: RuntimeProfile) -> RuntimeHealthCheck:
        if profile.reranker_provider == "disabled":
            return RuntimeHealthCheck(
                name="reranker",
                status="skipped",
                detail="Reranker is disabled for this profile.",
            )
        if not profile.reranker_base_url:
            return RuntimeHealthCheck(
                name="reranker",
                status="failed",
                severity="blocking",
                detail="Reranker is enabled but no base URL is configured.",
                error_type="configuration",
            )
        return RuntimeHealthCheck(
            name="reranker",
            status="ok",
            detail="Reranker endpoint is configured.",
        )

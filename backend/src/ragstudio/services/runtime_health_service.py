from collections.abc import Iterable
from importlib.util import find_spec

from ragstudio.schemas.runtime import RuntimeHealthCheck, RuntimeProfile


class RuntimeHealthService:
    async def check(self, profile: RuntimeProfile | None) -> list[RuntimeHealthCheck]:
        if profile is None:
            return [
                RuntimeHealthCheck(
                    name="runtime_profile",
                    status="failed",
                    severity="blocking",
                    detail="Default runtime profile is not configured.",
                    error_type="configuration",
                    remediation="Save Settings before indexing or querying.",
                )
            ]

        return [
            self._package_check("raganything", "RAG-Anything package"),
            self._package_check("lightrag", "LightRAG package"),
            self._required_url_check("llm", profile.llm_base_url, "LLM base URL"),
            self._vision_check(profile),
            self._required_url_check(
                "embedding",
                profile.embedding_base_url,
                "Embedding base URL",
            ),
            self._reranker_check(profile),
            self._required_text_check("pgvector", profile.pgvector_schema, "PGVector schema"),
            self._required_url_check("neo4j", profile.neo4j_uri, "Neo4j URI"),
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
        if find_spec(module) is None:
            return RuntimeHealthCheck(
                name=module,
                status="failed",
                severity="blocking",
                detail=f"{label} is not installed in this Python environment.",
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

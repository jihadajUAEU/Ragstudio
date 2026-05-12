from time import perf_counter

from ragstudio.schemas.chunks import ChunkOut
from ragstudio.schemas.settings import RerankerConnectionTestOut, SettingsProfileIn
from ragstudio.services.reranker_service import RerankerService


class RerankerConnectionService:
    def __init__(self, allowed_hosts: list[str] | None = None):
        self.allowed_hosts = allowed_hosts

    async def test(self, settings: SettingsProfileIn) -> RerankerConnectionTestOut:
        started = perf_counter()
        chunks = [
            ChunkOut(
                id="reranker-test-weak",
                document_id="reranker-test",
                text="Ragstudio checks parser health.",
                source_location={},
                metadata={},
            ),
            ChunkOut(
                id="reranker-test-strong",
                document_id="reranker-test",
                text="Ragstudio reranks retrieved evidence before answering.",
                source_location={},
                metadata={},
            ),
        ]
        _, traces = await RerankerService(allowed_hosts=self.allowed_hosts).rerank(
            "Which passage is most relevant to Ragstudio reranking?",
            chunks,
            settings,
        )
        latency_ms = int((perf_counter() - started) * 1000)
        ok = self._primary_returned_ranked_results(settings, traces)
        model = settings.reranker_model
        if settings.reranker_provider == "llm" and not model:
            model = settings.llm_model
        base_url = (
            settings.llm_base_url
            if settings.reranker_provider == "llm"
            else settings.reranker_base_url
        )
        return RerankerConnectionTestOut(
            ok=ok,
            provider=settings.reranker_provider,
            model=model,
            base_url=base_url,
            latency_ms=latency_ms,
            detail=(
                "Reranker returned ranked results."
                if ok
                else self._failure_detail(traces[0] if traces else {})
            ),
        )

    def _primary_returned_ranked_results(
        self,
        settings: SettingsProfileIn,
        traces: list[dict[str, object]],
    ) -> bool:
        expected_provider = (
            "llm" if settings.reranker_provider == "llm" else settings.reranker_provider
        )
        return any(
            trace.get("provider") == expected_provider
            and "fallback_provider" not in trace
            and "rank" in trace
            and "score" in trace
            for trace in traces
        )

    def _failure_detail(self, trace: dict[str, object]) -> str:
        status = str(trace.get("status") or "failed")
        reason = trace.get("reason")
        detail = trace.get("detail")
        if status == "blocked_endpoint":
            return (
                "Reranker endpoint host is not allowed. "
                "Add it to RAGSTUDIO_ALLOWED_RERANKER_HOSTS."
            )
        if status == "disabled":
            return "Reranker is disabled for this profile."
        if status == "skipped":
            return f"Reranker test skipped: {reason or 'not configured'}."
        if detail:
            return str(detail)
        return f"Reranker test returned {status}."

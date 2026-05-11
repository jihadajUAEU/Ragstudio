from __future__ import annotations

from typing import Any


class RetrievalObservability:
    def __init__(self) -> None:
        self.trace: dict[str, Any] = {"stages": [], "cache": [], "final_evidence_ids": []}

    def record_stage(self, stage: str, *, candidate_count: int, latency_ms: float) -> None:
        self.trace["stages"].append(
            {
                "stage": stage,
                "candidate_count": candidate_count,
                "latency_ms": latency_ms,
            }
        )

    def cache_decision(
        self,
        *,
        query: str,
        document_ids: list[str],
        query_type: str,
    ) -> dict[str, Any]:
        if query_type in {"exact_arabic_token", "exact_reference"}:
            decision = {
                "answer_cache": "bypass",
                "reason": "direct_evidence_query",
                "query": query,
                "document_ids": document_ids,
            }
        else:
            decision = {
                "answer_cache": "eligible",
                "reason": "semantic_query",
                "query": query,
                "document_ids": document_ids,
            }
        self.trace["cache"].append(decision)
        return decision

    def record_final_evidence(self, evidence_ids: list[str], *, grounding_status: str) -> None:
        self.trace["final_evidence_ids"] = evidence_ids
        self.trace["grounding_status"] = grounding_status


def retrieval_cache_key(
    *,
    query: str,
    document_ids: list[str],
    index_version: str,
    runtime_profile: str,
    parser_mode: str,
    embedding_model_id: str,
    embedding_dimension: int,
    reranker_enabled: bool,
) -> str:
    parts = [
        query,
        ",".join(sorted(document_ids)),
        index_version,
        runtime_profile,
        parser_mode,
        embedding_model_id,
        str(embedding_dimension),
        f"reranker={reranker_enabled}",
    ]
    return "|".join(parts)

from __future__ import annotations

from typing import Any

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.retrieval_orchestrator import RetrievalOrchestrator
from ragstudio.services.runtime_types import RuntimeQueryResult
from sqlalchemy import select


class EmptyMetadataRetrievalService:
    async def retrieve(
        self,
        query: str,
        *,
        understanding: Any,
        document_ids: list[str],
        variant_id: str,
        limit: int,
        search_weights: dict[str, Any] | None = None,
    ) -> tuple[list[Any], dict[str, Any]]:
        return [], {
            "stage": "metadata_retrieval",
            "status": "empty_for_vector_regression",
            "passes": [],
        }


class ContractBackedChunkService:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def domain_metadata_for_documents(self, document_ids: list[str]) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(Document.id, Document.index_contract).where(Document.id.in_(document_ids))
            )
        ).all()
        metadata: list[dict[str, Any]] = []
        for document_id, index_contract in rows:
            if not isinstance(index_contract, dict):
                continue
            domain_metadata = index_contract.get("domain_metadata")
            if not isinstance(domain_metadata, dict):
                continue
            metadata.append(
                {
                    **domain_metadata,
                    "document_id": document_id,
                    "contract_status": index_contract.get("contract_status"),
                }
            )
        return metadata

    async def search(self, search_in: Any) -> Any:
        return type("SearchResult", (), {"items": [], "total": 0})()


class EmptyRuntime:
    async def query(self, query: str, *, document_ids: list[str], query_config: dict[str, Any]):
        return RuntimeQueryResult(
            answer="",
            sources=[],
            timings={"runtime_query_ms": 0, "native_scoped_query": True},
        )


class CapturingAnswerService:
    def __init__(self) -> None:
        self.evidence = []

    async def answer(self, query: str, evidence: list[Any], profile: Any):
        self.evidence = evidence
        return "Recovered layout evidence is available.", {"prompt_tokens": 8}


class PassthroughRerankerService:
    async def rerank(self, query: str, chunks: list[Any], profile: Any):
        return chunks, [{"provider": "disabled", "status": "disabled"}]


class NoopGraphExpansionService:
    async def expand(
        self,
        query: str,
        *,
        seeds: list[Any],
        profile: Any,
        document_ids: list[str],
        limit: int,
    ):
        return [], [{"stage": "graph_expansion", "status": "disabled_for_regression"}]


@pytest.mark.asyncio
async def test_domain_contract_quality_policy_and_layout_metadata_drive_vector_retrieval(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    async with factory() as session:
        session.add(
            Document(
                id="doc-domain-layout",
                filename="layout-reference.pdf",
                content_type="application/pdf",
                sha256="domain-layout-sha",
                artifact_path=str(tmp_path / "layout-reference.pdf"),
                status="ready",
                index_contract={
                    "contract_version": 1,
                    "contract_status": "compiled_reference_contract",
                    "domain_metadata": {
                        "domain": "quran_tafseer",
                        "language": "english",
                        "document_type": "commentary",
                        "tags": ["quran", "reference"],
                    },
                    "reference_contract": {
                        "schema_type": "chapter_verse",
                        "canonical_units": True,
                    },
                    "layout_context": {"vision_recovery_enabled": True},
                    "retrieval_contract": {
                        "source_of_truth": "postgres_canonical_evidence"
                    },
                },
            )
        )
        session.add_all(
            [
                Chunk(
                    id="chunk-repaired",
                    document_id="doc-domain-layout",
                    text=(
                        "Figure recovered layout reference 1:5 preserves the straight "
                        "path evidence from a vision fallback block."
                    ),
                    source_location={"page": 7, "reference": "1:5"},
                    metadata_json={
                        "reference_metadata": {
                            "references": ["1:5"],
                            "chapter_start": 1,
                            "chapter_end": 1,
                            "verse_start": 5,
                            "verse_end": 5,
                        },
                        "layout_context": {
                            "source": "vision_recovery",
                            "layout_type": "figure",
                            "reading_order": "visual_fallback",
                        },
                        "provenance": {
                            "blocks": [
                                {
                                    "role": "figure",
                                    "block_type": "vision_recovered_text",
                                    "text_preview": "straight path evidence",
                                }
                            ]
                        },
                        "quality_action_policy": {
                            "index_vector": True,
                            "project_graph": True,
                            "graph_confidence": "trusted",
                        },
                    },
                ),
                Chunk(
                    id="chunk-blocked",
                    document_id="doc-domain-layout",
                    text=(
                        "Figure recovered layout reference 1:5 should not become "
                        "vector evidence when the quality gate blocks it."
                    ),
                    source_location={"page": 8, "reference": "1:5"},
                    metadata_json={
                        "reference_metadata": {"references": ["1:5"]},
                        "layout_context": {
                            "source": "vision_recovery",
                            "layout_type": "figure",
                        },
                        "quality_action_policy": {
                            "index_vector": False,
                            "project_graph": False,
                            "reasons": ["vision_recovery_below_threshold"],
                        },
                    },
                ),
            ]
        )
        await session.commit()

        answer_service = CapturingAnswerService()
        orchestrator = RetrievalOrchestrator(
            chunk_service=ContractBackedChunkService(session),
            answer_service=answer_service,
            reranker_service=PassthroughRerankerService(),
            graph_expansion_service=NoopGraphExpansionService(),
            metadata_retrieval_service=EmptyMetadataRetrievalService(),
        )

        result = await orchestrator.query(
            "figure recovered layout reference 1:5",
            runtime=EmptyRuntime(),
            profile=type(
                "Profile",
                (),
                {
                    "id": "profile-test",
                    "enable_rerank": False,
                    "reranker_provider": "disabled",
                },
            )(),
            document_ids=["doc-domain-layout"],
            variant_id="variant-test",
            query_config={
                "limit": 5,
                "graph_expansion_enabled": False,
                "enable_query_hypothesis": False,
                "query_hypothesis_required": False,
                "enable_rerank": False,
                "vector_baseline_gate": {"passed": True},
            },
        )

    await engine.dispose()

    assert result.error is None
    assert any(source["chunk_id"] == "chunk-repaired" for source in result.sources)
    assert not any(source["chunk_id"] == "chunk-blocked" for source in result.sources)
    assert any(candidate.chunk_id == "chunk-repaired" for candidate in answer_service.evidence)
    assert not any(candidate.chunk_id == "chunk-blocked" for candidate in answer_service.evidence)
    assert any(
        trace.get("stage") == "retrieval_route_plan"
        and trace.get("domain_profile_id") == "reference_heavy"
        and trace.get("source_of_truth") == "postgres_canonical_evidence"
        for trace in result.chunk_traces
    )
    assert any(
        trace.get("stage") == "vector_retrieval" and trace.get("status") == "ran"
        for trace in result.chunk_traces
    )
    assert any(
        trace.get("stage") == "retrieval_lane_result"
        and trace.get("lane") == "vector"
        and trace.get("status") == "ran"
        and trace.get("canonical_chunk_ids") == ["chunk-repaired"]
        for trace in result.chunk_traces
    )

    source = next(source for source in result.sources if source["chunk_id"] == "chunk-repaired")
    metadata = source["metadata"]
    assert metadata["retrieval_tool"] == "pgvector"
    assert metadata["retrieval_pass"] == "vector_db"
    assert metadata["vector_retrieval"]["hydrated_to_canonical"] is True
    assert metadata["quality_action_policy"]["index_vector"] is True
    assert metadata["layout_context"]["source"] == "vision_recovery"
    assert metadata["provenance"]["blocks"][0]["block_type"] == "vision_recovered_text"

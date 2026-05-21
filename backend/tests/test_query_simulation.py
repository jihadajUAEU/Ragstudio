import pytest
from ragstudio.db.models import Chunk, Document, Run, Variant
from ragstudio.schemas.chunks import HybridSearchWeights
from ragstudio.schemas.common import StageStatus
from ragstudio.schemas.query import SimulateRetrievalIn
from ragstudio.services.query_service import QueryService
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_simulate_retrieval_ranks_chunks_without_persisting_runs(client):
    app = client._transport.app
    async with app.state.session_factory() as session:
        document = Document(
            filename="simulation-source.txt",
            content_type="text/plain",
            sha256="simulation-source",
            artifact_path=str(app.state.settings.data_dir / "simulation-source.txt"),
            status=StageStatus.SUCCEEDED.value,
        )
        variant = Variant(name="Simulation", preset="balanced", parameters={})
        session.add_all([document, variant])
        await session.flush()
        metadata_match = Chunk(
            document_id=document.id,
            text="General collection overview.",
            source_location={"page": 1},
            metadata_json={"domain_metadata": {"domain": "hadith"}},
        )
        lexical_match = Chunk(
            document_id=document.id,
            text="hadith hadith lexical result",
            source_location={"page": 2},
            metadata_json={},
        )
        session.add_all([metadata_match, lexical_match])
        await session.commit()

        before_count = await session.scalar(select(func.count()).select_from(Run))

        result = await QueryService(session, app.state.settings.data_dir).simulate_retrieval(
            SimulateRetrievalIn(
                query="hadith",
                document_ids=[document.id],
                variant_ids=[variant.id],
                limit=2,
                search_weights=HybridSearchWeights(
                    exact_phrase=0,
                    term_coverage=0,
                    semantic_density=0,
                    metadata_boost=2,
                ),
            )
        )

        after_count = await session.scalar(select(func.count()).select_from(Run))

    assert [chunk.id for chunk in result.items] == [metadata_match.id]
    assert result.total == 1
    assert before_count == after_count

from types import SimpleNamespace

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document, GraphProjectionRecord, IndexRecord
from ragstudio.schemas.common import StageStatus
from ragstudio.services.graph_materialization_service import GraphMaterializationService
from ragstudio.services.query_service import QueryService


class FakeSession:
    def __init__(self, *, fail: bool = False, count_rows=None):
        self.calls = []
        self.fail = fail
        self.count_rows = count_rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, query, **params):
        if self.fail:
            raise RuntimeError("neo4j write failed")
        self.calls.append((query, params))
        if "RETURN count(DISTINCT n) AS node_count" in query:
            return self.count_rows
        return []

    def execute_write(self, callback):
        return callback(self)


class FakeDriver:
    def __init__(self, *, fail: bool = False, count_rows=None):
        self.session_instance = FakeSession(fail=fail, count_rows=count_rows)
        self.closed = False

    def session(self):
        return self.session_instance

    def close(self):
        self.closed = True


def profile():
    return SimpleNamespace(
        id="default",
        neo4j_uri="bolt://neo4j:7687",
        neo4j_username="neo4j",
        neo4j_password="secret",
    )


def chunk_with_relationships():
    return Chunk(
        id="chunk-1",
        document_id="doc-1",
        text="Book 53, Hadith 17 says justice among people is charity.",
        source_location={"page": 10},
        metadata_json={
            "runtime_source_id": "runtime-1",
            "reference_metadata": {
                "references": ["book:53:hadith:17"],
                "next_ref": "book:53:hadith:18",
            },
            "relationship_metadata": {
                "references": ["book:53:hadith:17"],
                "graph_relationships": [
                    {
                        "type": "references",
                        "source": "chunk:0",
                        "target": "ref:book:53:hadith:17",
                        "evidence": "reference_metadata",
                    },
                    {
                        "type": "next_hadith",
                        "source": "ref:book:53:hadith:17",
                        "target": "ref:book:53:hadith:18",
                        "evidence": "reference_metadata",
                    },
                ],
            },
        },
        runtime_profile_id="default",
        runtime_source_id="runtime-1",
        content_type="text",
    )


@pytest.mark.asyncio
async def test_replace_document_graph_deletes_and_rebuilds_projection():
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk_with_relationships()],
    )

    calls = driver.session_instance.calls
    delete_call = next(call for call in calls if "DETACH DELETE" in call[0])
    node_call = next(call for call in calls if "UNWIND $chunk_nodes AS node" in call[0])
    reference_call = next(call for call in calls if "UNWIND $reference_nodes AS node" in call[0])
    relationship_calls = [call for call in calls if "UNWIND $relationships AS rel" in call[0]]
    assert delete_call[1]["document_id"] == "doc-1"
    assert node_call[1]["chunk_nodes"][0]["chunk_id"] == "chunk-1"
    assert node_call[1]["chunk_nodes"][0]["id"] == "chunk:doc-1:chunk-1"
    assert node_call[1]["chunk_nodes"][0]["page"] == 10
    assert "reference_nodes" not in node_call[1]
    assert reference_call[1]["reference_nodes"][0]["id"] == "ref:doc-1:book:53:hadith:17"
    assert "chunk_nodes" not in reference_call[1]
    relationship_types = {
        relationship["type"]
        for _, params in relationship_calls
        for relationship in params["relationships"]
    }
    assert relationship_types == {"REFERENCES", "NEXT_HADITH"}
    assert result.status == "succeeded"
    assert result.node_count == 3
    assert result.edge_count == 2
    assert driver.closed is True


@pytest.mark.asyncio
async def test_replace_document_graph_resolves_preserved_chunk_source_alias_to_current_chunk():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    relationship_metadata = dict(metadata["relationship_metadata"])
    relationship_metadata["references"] = ["existing:1"]
    relationship_metadata["graph_relationships"] = [
        {
            "type": "custom",
            "source": "chunk:legacy",
            "target": "ref:existing:1",
            "evidence": "existing",
        }
    ]
    metadata["relationship_metadata"] = relationship_metadata
    chunk.metadata_json = metadata
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    relationship_call = next(
        call for call in driver.session_instance.calls if "UNWIND $relationships AS rel" in call[0]
    )
    relationship_payload = relationship_call[1]["relationships"][0]
    assert result.status == "succeeded"
    assert relationship_payload["source"] == "chunk:doc-1:chunk-1"
    assert relationship_payload["target"] == "ref:doc-1:existing:1"
    assert relationship_payload["type"] == "CUSTOM"


@pytest.mark.asyncio
async def test_replace_document_graph_prefers_current_chunk_for_duplicate_source_aliases():
    first = Chunk(
        id="chunk-a",
        document_id="doc-1",
        text="First split chunk with preserved relationship.",
        source_location={},
        metadata_json={
            "relationship_metadata": {
                "references": ["existing:1"],
                "graph_relationships": [
                    {
                        "type": "custom",
                        "source": "chunk:shared-runtime",
                        "target": "ref:existing:1",
                        "evidence": "existing",
                    }
                ],
            },
        },
        runtime_profile_id="default",
        runtime_source_id="shared-runtime",
        content_type="text",
    )
    second = Chunk(
        id="chunk-b",
        document_id="doc-1",
        text="Second split chunk with the same runtime source.",
        source_location={},
        metadata_json={},
        runtime_profile_id="default",
        runtime_source_id="shared-runtime",
        content_type="text",
    )
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[first, second],
    )

    relationship_call = next(
        call for call in driver.session_instance.calls if "UNWIND $relationships AS rel" in call[0]
    )
    relationship_payload = relationship_call[1]["relationships"][0]
    assert result.status == "succeeded"
    assert relationship_payload["source"] == "chunk:doc-1:chunk-a"
    assert relationship_payload["target"] == "ref:doc-1:existing:1"


@pytest.mark.asyncio
async def test_replace_document_graph_resolves_preserved_chunk_target_alias_to_current_chunk():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    relationship_metadata = dict(metadata["relationship_metadata"])
    relationship_metadata["references"] = ["existing:1"]
    relationship_metadata["graph_relationships"] = [
        {
            "type": "custom",
            "source": "ref:existing:1",
            "target": "chunk:legacy",
            "evidence": "existing",
        }
    ]
    metadata["relationship_metadata"] = relationship_metadata
    chunk.metadata_json = metadata
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    relationship_call = next(
        call for call in driver.session_instance.calls if "UNWIND $relationships AS rel" in call[0]
    )
    relationship_payload = relationship_call[1]["relationships"][0]
    assert result.status == "succeeded"
    assert relationship_payload["source"] == "ref:doc-1:existing:1"
    assert relationship_payload["target"] == "chunk:doc-1:chunk-1"


@pytest.mark.asyncio
async def test_replace_document_graph_skips_unresolved_chunk_aliases():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    relationship_metadata = dict(metadata["relationship_metadata"])
    relationship_metadata["references"] = ["existing:1"]
    relationship_metadata["graph_relationships"] = [
        {
            "type": "custom",
            "source": "chunk:not-this-chunk",
            "target": "ref:existing:1",
            "evidence": "existing",
        },
        {
            "type": "custom",
            "source": "ref:existing:1",
            "target": "chunk:not-this-chunk",
            "evidence": "existing",
        },
    ]
    metadata["relationship_metadata"] = relationship_metadata
    chunk.metadata_json = metadata
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    relationship_calls = [
        call for call in driver.session_instance.calls if "UNWIND $relationships AS rel" in call[0]
    ]
    assert result.status == "succeeded"
    assert relationship_calls == []


@pytest.mark.asyncio
async def test_replace_document_graph_skips_when_neo4j_uri_missing():
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: None)
    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=SimpleNamespace(id="default", neo4j_uri=None),
        chunks=[chunk_with_relationships()],
    )

    assert result.status == "skipped"
    assert result.reason == "neo4j_uri_missing"
    assert result.node_count == 0
    assert result.edge_count == 0


@pytest.mark.asyncio
async def test_replace_document_graph_soft_fails_when_neo4j_write_fails():
    driver = FakeDriver(fail=True)
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk_with_relationships()],
    )

    assert result.status == "failed"
    assert result.reason == "neo4j write failed"
    assert result.node_count == 0
    assert result.edge_count == 0
    assert driver.closed is True


@pytest.mark.asyncio
async def test_delete_document_graph_removes_document_projection():
    driver = FakeDriver(count_rows=[{"node_count": 3, "edge_count": 2}])
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.delete_document_graph(
        document_id="doc-1",
        profile=profile(),
    )

    queries = [query for query, _ in driver.session_instance.calls]
    assert any("RETURN count(DISTINCT n) AS node_count" in query for query in queries)
    assert any("DETACH DELETE n" in query for query in queries)
    assert result.status == "succeeded"
    assert result.node_count == 3
    assert result.edge_count == 2
    assert driver.closed is True


@pytest.mark.asyncio
async def test_replace_document_graph_creates_projection_indexes_without_apoc():
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk_with_relationships()],
    )

    queries = "\n".join(query for query, _ in driver.session_instance.calls)
    assert "CREATE INDEX ragstudio_chunk_projection IF NOT EXISTS" in queries
    assert "CREATE INDEX ragstudio_reference_projection IF NOT EXISTS" in queries
    assert "apoc." not in queries


@pytest.mark.asyncio
async def test_replace_document_graph_json_encodes_complex_relationship_evidence():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    relationship_metadata = dict(metadata["relationship_metadata"])
    relationship = dict(relationship_metadata["graph_relationships"][0])
    relationship["evidence"] = {"source": "metadata", "confidence": 0.9}
    relationship_metadata["graph_relationships"] = [relationship]
    metadata["relationship_metadata"] = relationship_metadata
    chunk.metadata_json = metadata
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    relationship_call = next(
        call for call in driver.session_instance.calls if "UNWIND $relationships AS rel" in call[0]
    )
    relationship_payload = relationship_call[1]["relationships"][0]
    assert result.status == "succeeded"
    assert relationship_payload["evidence"] is None
    assert relationship_payload["evidence_json"] == '{"source": "metadata", "confidence": 0.9}'


@pytest.mark.asyncio
async def test_replace_document_graph_sanitizes_complex_source_location_properties():
    chunk = chunk_with_relationships()
    chunk.source_location = {
        "page": {"start": 1},
        "section": ["primitive", {"nested": "no"}],
        "start_index": 4,
        "end_index": 9,
    }
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    node_call = next(
        call for call in driver.session_instance.calls if "UNWIND $chunk_nodes" in call[0]
    )
    chunk_node = node_call[1]["chunk_nodes"][0]
    assert result.status == "succeeded"
    assert chunk_node["page"] is None
    assert chunk_node["section"] is None
    assert chunk_node["start_index"] == 4
    assert chunk_node["end_index"] == 9
    assert '"page": {"start": 1}' in chunk_node["source_location_json"]


@pytest.mark.asyncio
async def test_replace_document_graph_sanitizes_complex_source_id_metadata():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    metadata["source_id"] = {"artifact": "doc-1"}
    chunk.metadata_json = metadata
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    node_call = next(
        call for call in driver.session_instance.calls if "UNWIND $chunk_nodes" in call[0]
    )
    assert result.status == "succeeded"
    assert node_call[1]["chunk_nodes"][0]["source_id"] is None


@pytest.mark.asyncio
async def test_replace_document_graph_drops_mixed_primitive_list_properties():
    chunk = chunk_with_relationships()
    metadata = dict(chunk.metadata_json)
    metadata["source_id"] = ["doc", 1]
    chunk.metadata_json = metadata
    chunk.source_location = {"section": ["alpha", 2]}
    driver = FakeDriver()
    service = GraphMaterializationService(driver_factory=lambda *args, **kwargs: driver)

    result = await service.replace_document_graph(
        document_id="doc-1",
        profile=profile(),
        chunks=[chunk],
    )

    node_call = next(
        call for call in driver.session_instance.calls if "UNWIND $chunk_nodes" in call[0]
    )
    chunk_node = node_call[1]["chunk_nodes"][0]
    assert result.status == "succeeded"
    assert chunk_node["source_id"] is None
    assert chunk_node["section"] is None


@pytest.mark.asyncio
async def test_graph_projection_record_is_separate_from_index_readiness(
    tmp_path,
    database_url,
):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine)

    async with session_factory() as session:
        document = Document(
            filename="doc.pdf",
            content_type="application/pdf",
            sha256="graph-projection-record-sha",
            artifact_path=str(tmp_path / "doc.pdf"),
            status=StageStatus.SUCCEEDED.value,
        )
        session.add(document)
        await session.flush()
        index_shape = {
            "embedding_model": "text-embedding-3-large",
            "graph_storage": "neo4j",
        }
        session.add(
            IndexRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status=StageStatus.SUCCEEDED.value,
                index_shape=index_shape,
                chunk_count=1,
            )
        )
        session.add(
            GraphProjectionRecord(
                document_id=document.id,
                runtime_profile_id="default",
                status="pending",
                node_count=0,
                edge_count=0,
            )
        )
        await session.commit()

        await QueryService(session, tmp_path)._validate_index_readiness(
            [document.id],
            "default",
            index_shape,
        )

    await engine.dispose()

from types import SimpleNamespace

import pytest
from ragstudio.db.models import Chunk
from ragstudio.services.graph_materialization_service import GraphMaterializationService


class FakeSession:
    def __init__(self, *, fail: bool = False):
        self.calls = []
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, query, **params):
        if self.fail:
            raise RuntimeError("neo4j write failed")
        self.calls.append((query, params))
        return []

    def execute_write(self, callback):
        return callback(self)


class FakeDriver:
    def __init__(self, *, fail: bool = False):
        self.session_instance = FakeSession(fail=fail)
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
    relationship_calls = [call for call in calls if "UNWIND $relationships AS rel" in call[0]]
    assert delete_call[1]["document_id"] == "doc-1"
    assert node_call[1]["chunk_nodes"][0]["chunk_id"] == "chunk-1"
    assert node_call[1]["chunk_nodes"][0]["id"] == "chunk:doc-1:chunk-1"
    assert node_call[1]["chunk_nodes"][0]["page"] == 10
    assert node_call[1]["reference_nodes"][0]["id"] == "ref:doc-1:book:53:hadith:17"
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

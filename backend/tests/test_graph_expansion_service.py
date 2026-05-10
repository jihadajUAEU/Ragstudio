from types import SimpleNamespace

import pytest
from ragstudio.services.graph_expansion_service import GraphExpansionService
from ragstudio.services.retrieval_evidence import EvidenceCandidate


class FakeRecord(dict):
    def __getitem__(self, key):
        return self.get(key)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, query, **params):
        self.calls.append((query, params))
        return self.rows


class FakeDriver:
    def __init__(self, rows):
        self.session_instance = FakeSession(rows)
        self.closed = False

    def session(self):
        return self.session_instance

    def close(self):
        self.closed = True


def seed_candidate(**overrides):
    values = {
        "candidate_id": "metadata:seed-1",
        "text": "Book 1 Hadith 1",
        "document_id": "doc-1",
        "chunk_id": "seed-1",
        "source_location": {"page": 1},
        "metadata": {"runtime_source_id": "seed-runtime"},
        "tool": "metadata",
        "tool_rank": 1,
        "base_score": 10.0,
    }
    values.update(overrides)
    return EvidenceCandidate(**values)


def profile(**overrides):
    values = {
        "id": "tenant`one",
        "neo4j_uri": "bolt://127.0.0.1:7687",
        "neo4j_username": "neo4j",
        "neo4j_password": "secret",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_graph_expansion_scopes_query_to_workspace_label():
    row = FakeRecord(
        relationship_id="rel-1",
        relationship_type="NEXT",
        relationship_properties={"weight": 0.8},
        seed_properties={"chunk_id": "seed-1"},
        neighbor_id="node-2",
        neighbor_labels=["ragstudio_tenant_one", "Chunk"],
        neighbor_properties={
            "chunk_id": "neighbor-1",
            "document_id": "doc-1",
            "text_preview": "Book 1 Hadith 2",
            "page": 2,
        },
    )
    driver = FakeDriver([row])
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: driver)

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate()],
        profile=profile(),
        document_ids=["doc-1"],
        limit=4,
    )

    query, params = driver.session_instance.calls[0]
    assert "CALL {" in query
    assert (
        "MATCH (seed:`ragstudio_tenant_one`)-[relationship]-"
        "(neighbor:`ragstudio_tenant_one`:RagstudioChunk)"
    ) in query
    assert "RagstudioReference" in query
    assert params["seed_ids"] == ["seed-1", "seed-runtime"]
    assert params["document_ids"] == ["doc-1"]
    assert params["limit"] == 4
    assert candidates[0].tool == "graph"
    assert candidates[0].chunk_id == "neighbor-1"
    assert candidates[0].text == "Book 1 Hadith 2"
    assert candidates[0].metadata["graph_relationship"]["type"] == "NEXT"
    assert candidates[0].metadata["graph_relationship"]["properties"] == {"weight": 0.8}
    assert traces[0]["stage"] == "graph_expansion"
    assert traces[0]["expanded_candidates"] == 1
    assert driver.closed is True


@pytest.mark.asyncio
async def test_graph_expansion_converts_neighbor_rows_to_candidates():
    driver = FakeDriver(
        [
            FakeRecord(
                relationship_id="rel-2",
                relationship_type="MENTIONS",
                relationship_properties={"confidence": 0.7},
                seed_properties={"runtime_source_id": "seed-runtime"},
                neighbor_id="node-3",
                neighbor_labels=["Entity"],
                bridge_relationship_types=["NEXT_HADITH"],
                graph_path="reference_hop",
                neighbor_properties={
                    "runtime_source_id": "runtime-neighbor",
                    "full_doc_id": "doc-2",
                    "content": "Related entity summary",
                    "section": "Biography",
                },
            )
        ]
    )
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: driver)

    candidates, _ = await service.expand(
        "show related people",
        seeds=[seed_candidate(chunk_id=None)],
        profile=profile(),
        document_ids=[],
        limit=2,
    )

    assert candidates == [
        EvidenceCandidate(
            candidate_id="graph:node-3",
            text="Related entity summary",
            document_id="doc-2",
            chunk_id="runtime-neighbor",
            source_location={"section": "Biography"},
            metadata={
                "runtime_source_id": "runtime-neighbor",
                "full_doc_id": "doc-2",
                "content": "Related entity summary",
                "section": "Biography",
                "graph_relationship": {
                    "id": "rel-2",
                    "type": "MENTIONS",
                    "properties": {"confidence": 0.7},
                    "seed": {"runtime_source_id": "seed-runtime"},
                    "bridge_relationship_types": ["NEXT_HADITH"],
                    "path": "reference_hop",
                },
                "graph_labels": ["Entity"],
            },
            tool="graph",
            tool_rank=1,
            base_score=17.0,
            boost_score=2.0,
            final_score=19.0,
            reasons=["graph_neighbor"],
        )
    ]


@pytest.mark.asyncio
async def test_graph_expansion_returns_trace_when_neo4j_uri_is_missing():
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: None)

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate()],
        profile=profile(neo4j_uri=None),
        document_ids=["doc-1"],
        limit=4,
    )

    assert candidates == []
    assert traces == [
        {
            "stage": "graph_expansion",
            "status": "skipped",
            "reason": "neo4j_uri_missing",
        }
    ]


@pytest.mark.asyncio
async def test_graph_expansion_returns_trace_when_no_seed_ids():
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: FakeDriver([]))

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate(chunk_id=None, metadata={})],
        profile=profile(),
        document_ids=["doc-1"],
        limit=4,
    )

    assert candidates == []
    assert traces == [
        {
            "stage": "graph_expansion",
            "status": "skipped",
            "reason": "no_seed_ids",
        }
    ]


@pytest.mark.asyncio
async def test_graph_expansion_returns_trace_when_driver_is_unavailable():
    service = GraphExpansionService(driver_factory=lambda *args, **kwargs: None)

    candidates, traces = await service.expand(
        "show related hadith",
        seeds=[seed_candidate()],
        profile=profile(),
        document_ids=["doc-1"],
        limit=4,
    )

    assert candidates == []
    assert traces == [
        {
            "stage": "graph_expansion",
            "status": "skipped",
            "reason": "driver_unavailable",
        }
    ]

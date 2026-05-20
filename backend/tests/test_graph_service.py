from datetime import UTC, datetime, timedelta

import pytest
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Chunk, Document
from ragstudio.services.graph_service import GraphService


def _relationship_chunk(
    *,
    chunk_id: str,
    document_id: str,
    source: str,
    target: str,
    created_at: datetime,
) -> Chunk:
    return Chunk(
        id=chunk_id,
        document_id=document_id,
        text=f"{source} relates to {target}",
        metadata_json={
            "relationship_metadata": {
                "graph_relationships": [
                    {"source": source, "target": target, "type": "related"}
                ]
            }
        },
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.mark.asyncio
async def test_relationship_metadata_graph_scopes_document_before_paginating(
    database_url,
    tmp_path,
):
    engine = make_engine(database_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    now = datetime(2026, 5, 20, tzinfo=UTC)

    async with factory() as session:
        documents = [
            Document(
                id="doc-a",
                filename="a.txt",
                content_type="text/plain",
                sha256="sha-a",
                artifact_path=str(tmp_path / "a.txt"),
                status="succeeded",
            ),
            Document(
                id="doc-b",
                filename="b.txt",
                content_type="text/plain",
                sha256="sha-b",
                artifact_path=str(tmp_path / "b.txt"),
                status="succeeded",
            ),
        ]
        session.add_all(documents)
        await session.flush()
        session.add_all(
            [
                _relationship_chunk(
                    chunk_id="doc-a-newest",
                    document_id="doc-a",
                    source="a-newest",
                    target="a-newest-target",
                    created_at=now,
                ),
                _relationship_chunk(
                    chunk_id="doc-a-middle",
                    document_id="doc-a",
                    source="a-middle",
                    target="a-middle-target",
                    created_at=now - timedelta(minutes=1),
                ),
                _relationship_chunk(
                    chunk_id="doc-a-oldest",
                    document_id="doc-a",
                    source="a-oldest",
                    target="a-oldest-target",
                    created_at=now - timedelta(minutes=2),
                ),
                _relationship_chunk(
                    chunk_id="doc-b-newest",
                    document_id="doc-b",
                    source="b-newest",
                    target="b-newest-target",
                    created_at=now + timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()

        graph = await GraphService(session)._relationship_metadata_graph(
            document_id="doc-a",
            limit=1,
            offset=1,
        )

    await engine.dispose()

    assert graph["total"] == 3
    assert graph["limit"] == 1
    assert graph["offset"] == 1
    assert graph["has_more"] is True
    assert {node["id"] for node in graph["nodes"]} == {
        "doc-a:a-middle",
        "doc-a:a-middle-target",
    }
    assert [edge["id"] for edge in graph["edges"]] == [
        "doc-a:a-middle-a-middle-target-related"
    ]


@pytest.mark.asyncio
async def test_graph_route_preserves_default_shape_and_exposes_page_info(client):
    response = await client.get("/api/graph")

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [],
        "edges": [],
        "detail": "No runtime graph or relationship metadata is available.",
    }

    paged_response = await client.get("/api/graph?limit=1&offset=0")

    assert paged_response.status_code == 200
    payload = paged_response.json()
    assert payload["total"] == 0
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is False

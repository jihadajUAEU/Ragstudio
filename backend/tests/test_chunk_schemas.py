from ragstudio.db.models import Chunk
from ragstudio.schemas.chunks import ChunkOut


def test_chunk_out_serializes_metadata_json_as_metadata():
    chunk = Chunk(
        id="chunk_1",
        document_id="doc_1",
        text="A useful chunk",
        source_location={"page": 1},
        metadata_json={"heading": "Intro"},
    )

    dumped = ChunkOut.model_validate(chunk).model_dump()

    assert dumped["metadata"] == {"heading": "Intro"}
    assert "metadata_json" not in dumped

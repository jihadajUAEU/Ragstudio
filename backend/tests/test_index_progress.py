from ragstudio.services.index_progress import (
    IndexStage,
    stage_payload,
    stage_progress,
    update_job_stage,
)


class FakeJob:
    def __init__(self):
        self.progress = 0
        self.logs = []
        self.result = {}


def test_stage_progress_is_monotonic():
    stages = [
        IndexStage.QUEUED,
        IndexStage.MINERU_PARSING,
        IndexStage.MINERU_VALIDATED,
        IndexStage.CHUNKS_PERSISTED,
        IndexStage.SEARCH_READY,
        IndexStage.RUNTIME_ENRICHING,
        IndexStage.GRAPH_ENRICHING,
        IndexStage.READY,
    ]

    values = [stage_progress(stage) for stage in stages]

    assert values == sorted(values)
    assert values[0] == 1
    assert values[-1] == 100


def test_stage_payload_has_ui_safe_fields():
    payload = stage_payload(
        IndexStage.CHUNKS_PERSISTED,
        detail="Persisted 1754 chunks.",
        chunk_count=1754,
    )

    assert payload["stage"] == "chunks_persisted"
    assert payload["label"] == "Chunks persisted"
    assert payload["detail"] == "Persisted 1754 chunks."
    assert payload["chunk_count"] == 1754


def test_update_job_stage_preserves_existing_result_and_caps_logs():
    job = FakeJob()
    job.result = {"mineru": {"status": "ready"}}
    job.logs = [f"log {index}" for index in range(25)]

    update_job_stage(
        job,
        IndexStage.SEARCH_READY,
        detail="Lexical retrieval is ready.",
        chunk_count=1754,
    )

    assert job.progress == 75
    assert job.result["mineru"] == {"status": "ready"}
    assert job.result["indexing_stage"]["stage"] == "search_ready"
    assert job.result["indexing_stage"]["chunk_count"] == 1754
    assert job.logs[-1] == "Search ready: Lexical retrieval is ready."
    assert len(job.logs) == 20

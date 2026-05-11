import pytest
from ragstudio.services.vector_index_policy import (
    VectorIndexPolicy,
    VectorReadinessError,
)


def test_query_dimension_must_match_active_profile():
    policy = VectorIndexPolicy()

    with pytest.raises(VectorReadinessError, match="embedding_dimension_mismatch"):
        policy.assert_query_dimension([0.1, 0.2, 0.3], expected_dimension=2)


def test_query_dimension_passes_when_profile_matches():
    report = VectorIndexPolicy().assert_query_dimension([0.1, 0.2, 0.3], expected_dimension=3)

    assert report["status"] == "ready"
    assert report["observed_dimension"] == 3


def test_pgvector_readiness_requires_extension_and_index():
    policy = VectorIndexPolicy()

    with pytest.raises(VectorReadinessError, match="pgvector_index_unavailable"):
        policy.validate_pgvector_ready(
            {"extension_available": True, "index_type": None, "hnsw_supported": True}
        )


def test_pgvector_prefers_hnsw_and_marks_ivfflat_compatibility():
    policy = VectorIndexPolicy()

    hnsw = policy.validate_pgvector_ready(
        {"extension_available": True, "index_type": "hnsw", "hnsw_supported": True}
    )
    ivfflat = policy.validate_pgvector_ready(
        {"extension_available": True, "index_type": "ivfflat", "hnsw_supported": False}
    )

    assert hnsw["index_type"] == "hnsw"
    assert hnsw["status"] == "ready"
    assert ivfflat["index_type"] == "ivfflat"
    assert ivfflat["status"] == "compatibility"

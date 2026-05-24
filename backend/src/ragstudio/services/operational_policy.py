from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    max_upload_bytes: int = 25 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024


@dataclass(frozen=True, slots=True)
class WorkerPolicy:
    lease_seconds: int = 300
    job_max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class ChunkPersistencePolicy:
    min_expected_chunks: int = 2
    max_expected_chunks: int = 5000
    persist_batch_size: int = 500


@dataclass(frozen=True, slots=True)
class ChunkSearchPolicy:
    fallback_candidate_limit: int = 100


@dataclass(frozen=True, slots=True)
class CandidateDiversityPolicy:
    similarity_threshold: float = 0.65


@dataclass(frozen=True, slots=True)
class RetrievalMetricGatePolicy:
    min_precision_at_k: float = 0.75
    min_recall_at_k: float = 0.70
    min_mrr: float = 0.80
    min_hit_rate: float = 1.0


@dataclass(frozen=True, slots=True)
class EvaluationScoringPolicy:
    expected_answer_weight: float = 50.0
    must_include_weight: float = 35.0
    must_avoid_weight: float = 15.0


@dataclass(frozen=True, slots=True)
class OperationalPolicy:
    policy_version: str = "2026-05-24"
    upload: UploadPolicy = field(default_factory=UploadPolicy)
    worker: WorkerPolicy = field(default_factory=WorkerPolicy)
    chunk_persistence: ChunkPersistencePolicy = field(default_factory=ChunkPersistencePolicy)
    chunk_search: ChunkSearchPolicy = field(default_factory=ChunkSearchPolicy)
    candidate_diversity: CandidateDiversityPolicy = field(default_factory=CandidateDiversityPolicy)
    retrieval_metrics: RetrievalMetricGatePolicy = field(default_factory=RetrievalMetricGatePolicy)
    evaluation: EvaluationScoringPolicy = field(default_factory=EvaluationScoringPolicy)
    variant_presets: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "balanced": {"top_k": 5, "temperature": 0.2, "enable_rerank": True},
            "precise": {"top_k": 3, "temperature": 0.1, "enable_rerank": True},
            "broad": {"top_k": 12, "temperature": 0.3, "enable_rerank": True},
            "fast": {"top_k": 4, "temperature": 0.0, "enable_rerank": False},
        }
    )


DEFAULT_OPERATIONAL_POLICY = OperationalPolicy()

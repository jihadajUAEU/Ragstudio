from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ragstudio.services.retrieval_evidence import EvidenceCandidate

VectorRetrievalStatus = Literal["ran", "skipped", "failed"]

_REGRESSION_FLAGS = (
    "direct_hit_regressed",
    "mrr_regressed",
    "ndcg_regressed",
    "recall_regressed",
    "latency_budget_regressed",
)


@dataclass(frozen=True, slots=True)
class VectorRetrievalDiagnostics:
    status: VectorRetrievalStatus
    reason: str
    candidate_count: int = 0
    hydrated_count: int = 0
    failed_candidate_ids: tuple[str, ...] = ()
    warning_flags: tuple[str, ...] = ()
    gate: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": "vector_retrieval",
            "status": self.status,
            "reason": self.reason,
            "candidate_count": self.candidate_count,
            "hydrated_count": self.hydrated_count,
            "failed_candidate_ids": list(self.failed_candidate_ids),
            "warning_flags": list(self.warning_flags),
            "gate": self.gate,
        }


@dataclass(frozen=True, slots=True)
class VectorRetrievalResult:
    candidates: tuple[EvidenceCandidate, ...]
    diagnostics: VectorRetrievalDiagnostics

    @property
    def status(self) -> VectorRetrievalStatus:
        return self.diagnostics.status

    @property
    def reason(self) -> str:
        return self.diagnostics.reason

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_trace() for candidate in self.candidates],
            "diagnostics": self.diagnostics.as_dict(),
        }


def vector_lane_allowed(
    metadata: Mapping[str, Any] | None,
    *,
    baseline_gate: Mapping[str, Any] | bool | None = None,
) -> bool:
    return _vector_lane_decision(metadata, baseline_gate=baseline_gate)[0]


def vector_lane_diagnostics(
    metadata: Mapping[str, Any] | None,
    *,
    baseline_gate: Mapping[str, Any] | bool | None = None,
) -> VectorRetrievalDiagnostics:
    allowed, reason, gate = _vector_lane_decision(metadata, baseline_gate=baseline_gate)
    return VectorRetrievalDiagnostics(
        status="ran" if allowed else "skipped",
        reason=reason,
        gate=gate,
    )


def prepare_vector_candidates(
    raw_candidates: Sequence[Mapping[str, Any]],
    *,
    metadata: Mapping[str, Any] | None = None,
    baseline_gate: Mapping[str, Any] | bool | None = None,
    canonical_chunks: Mapping[str, Mapping[str, Any]] | None = None,
) -> VectorRetrievalResult:
    allowed, reason, gate = _vector_lane_decision(metadata, baseline_gate=baseline_gate)
    candidate_count = len(raw_candidates)
    if not allowed:
        return VectorRetrievalResult(
            candidates=(),
            diagnostics=VectorRetrievalDiagnostics(
                status="skipped",
                reason=reason,
                candidate_count=candidate_count,
                gate=gate,
            ),
        )

    hydrated: list[EvidenceCandidate] = []
    failed_candidate_ids: list[str] = []
    for rank, raw_candidate in enumerate(raw_candidates, start=1):
        candidate = _hydrate_candidate(
            raw_candidate,
            rank=rank,
            canonical_chunks=canonical_chunks,
        )
        if candidate is None:
            failed_candidate_ids.append(_raw_candidate_id(raw_candidate, rank))
            continue
        hydrated.append(candidate)

    if failed_candidate_ids:
        return VectorRetrievalResult(
            candidates=(),
            diagnostics=VectorRetrievalDiagnostics(
                status="failed",
                reason="canonical_hydration_failed",
                candidate_count=candidate_count,
                hydrated_count=len(hydrated),
                failed_candidate_ids=tuple(failed_candidate_ids),
                warning_flags=("vector_candidates_not_hydrated",),
                gate=gate,
            ),
        )

    return VectorRetrievalResult(
        candidates=tuple(hydrated),
        diagnostics=VectorRetrievalDiagnostics(
            status="ran",
            reason="vector_candidates_hydrated_to_canonical_chunks",
            candidate_count=candidate_count,
            hydrated_count=len(hydrated),
            gate=gate,
        ),
    )


def _vector_lane_decision(
    metadata: Mapping[str, Any] | None,
    *,
    baseline_gate: Mapping[str, Any] | bool | None,
) -> tuple[bool, str, dict[str, Any]]:
    quality_policy = _mapping_value(metadata, "quality_action_policy")
    if quality_policy is not None:
        if quality_policy.get("action") == "block":
            return False, "vector_lane_blocked_by_quality_policy", _gate_payload(baseline_gate)
        if quality_policy.get("index_vector") is False:
            return False, "vector_lane_blocked_by_quality_policy", _gate_payload(baseline_gate)

    gate_passed, gate_reason, gate = _baseline_gate_passed(baseline_gate)
    if not gate_passed:
        return False, gate_reason, gate
    return True, "retrieval_quality_baseline_gate_passed", gate


def _baseline_gate_passed(
    baseline_gate: Mapping[str, Any] | bool | None,
) -> tuple[bool, str, dict[str, Any]]:
    if baseline_gate is None:
        return False, "vector_lane_skipped_baseline_gate_missing", {"provided": False}

    if isinstance(baseline_gate, bool):
        gate = {"provided": True, "passed": baseline_gate}
        reason = (
            "retrieval_quality_baseline_gate_passed"
            if baseline_gate
            else "vector_lane_skipped_baseline_gate_failed"
        )
        return baseline_gate, reason, gate

    gate = _gate_payload(baseline_gate)
    if baseline_gate.get("passed") is True:
        return True, "retrieval_quality_baseline_gate_passed", gate

    regressions = {
        name: bool(baseline_gate.get(name))
        for name in _REGRESSION_FLAGS
        if name in baseline_gate
    }
    if regressions and not any(regressions.values()):
        gate["passed"] = True
        return True, "retrieval_quality_baseline_gate_passed", gate
    if any(regressions.values()):
        gate["regressions"] = [name for name, regressed in regressions.items() if regressed]
        return False, "vector_lane_skipped_baseline_regressed", gate
    return False, "vector_lane_skipped_baseline_gate_failed", gate


def _hydrate_candidate(
    raw_candidate: Mapping[str, Any],
    *,
    rank: int,
    canonical_chunks: Mapping[str, Mapping[str, Any]] | None,
) -> EvidenceCandidate | None:
    chunk_id = _chunk_id(raw_candidate)
    if not chunk_id:
        return None

    canonical = canonical_chunks.get(chunk_id) if canonical_chunks is not None else None
    if canonical_chunks is not None and canonical is None:
        return None
    source = canonical or raw_candidate
    document_id = _string_value(source, "document_id")
    text = _string_value(source, "text")
    if not document_id or text is None:
        return None

    metadata = _metadata(source)
    raw_metadata = _metadata(raw_candidate)
    raw_evidence_context = raw_metadata.get("evidence_context")
    metadata.update(raw_metadata)
    if isinstance(raw_evidence_context, Mapping):
        metadata["evidence_context"] = dict(raw_evidence_context)
    metadata["canonical_chunk_id"] = chunk_id

    score = _score(raw_candidate)
    candidate_rank = _int_value(raw_candidate, "rank") or rank
    original_candidate_id = _string_value(raw_candidate, "candidate_id")
    vector_metadata: dict[str, Any] = {
        "score": score,
        "rank": candidate_rank,
        "hydrated_to_canonical": True,
    }
    if original_candidate_id and original_candidate_id != f"vector:{chunk_id}":
        vector_metadata["original_candidate_id"] = original_candidate_id
    metadata["vector_retrieval"] = vector_metadata

    return EvidenceCandidate(
        candidate_id=f"vector:{chunk_id}",
        text=text,
        document_id=document_id,
        chunk_id=chunk_id,
        source_location=_source_location(source),
        metadata=metadata,
        tool="pgvector",
        tool_rank=candidate_rank,
        base_score=score,
        final_score=score,
        reasons=[
            "retrieval_quality_baseline_gate_passed",
            "canonical_chunk_hydrated",
        ],
        retrieval_pass="vector_db",
        scope_status="in_scope",
    )


def _mapping_value(source: Mapping[str, Any] | None, key: str) -> Mapping[str, Any] | None:
    if source is None:
        return None
    value = source.get(key)
    return value if isinstance(value, Mapping) else None


def _gate_payload(baseline_gate: Mapping[str, Any] | bool | None) -> dict[str, Any]:
    if baseline_gate is None:
        return {"provided": False}
    if isinstance(baseline_gate, bool):
        return {"provided": True, "passed": baseline_gate}
    payload = {key: baseline_gate[key] for key in baseline_gate if isinstance(key, str)}
    payload["provided"] = True
    return payload


def _raw_candidate_id(raw_candidate: Mapping[str, Any], rank: int) -> str:
    return (
        _string_value(raw_candidate, "candidate_id")
        or _string_value(raw_candidate, "chunk_id")
        or _string_value(raw_candidate, "canonical_chunk_id")
        or _string_value(raw_candidate, "id")
        or f"vector:{rank}"
    )


def _chunk_id(raw_candidate: Mapping[str, Any]) -> str | None:
    return (
        _string_value(raw_candidate, "canonical_chunk_id")
        or _string_value(raw_candidate, "chunk_id")
        or _string_value(raw_candidate, "id")
    )


def _metadata(source: Mapping[str, Any]) -> dict[str, Any]:
    metadata = source.get("metadata_json")
    if not isinstance(metadata, Mapping):
        metadata = source.get("metadata")
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _source_location(source: Mapping[str, Any]) -> dict[str, Any]:
    value = source.get("source_location")
    return dict(value) if isinstance(value, Mapping) else {}


def _score(raw_candidate: Mapping[str, Any]) -> float:
    score = _float_value(raw_candidate, "score")
    if score is not None:
        return score
    similarity = _float_value(raw_candidate, "similarity")
    if similarity is not None:
        return similarity
    distance = _float_value(raw_candidate, "distance")
    if distance is not None:
        return 1.0 / (1.0 + max(distance, 0.0))
    return 0.0


def _string_value(source: Mapping[str, Any], key: str) -> str | None:
    value = source.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _int_value(source: Mapping[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _float_value(source: Mapping[str, Any], key: str) -> float | None:
    value = source.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None

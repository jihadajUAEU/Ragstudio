from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

QueryIntent = Literal["count", "title", "reference", "comparison", "summary", "semantic"]


@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    document_ids: list[str]
    limit: int
    intent: QueryIntent
    use_native: bool = True
    use_metadata: bool = True
    use_relationships: bool = True
    candidate_limit: int = 20


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    text: str
    document_id: str | None
    chunk_id: str | None
    source_location: dict[str, Any]
    metadata: dict[str, Any]
    tool: str
    tool_rank: int
    base_score: float
    boost_score: float = 0.0
    final_score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_source(self) -> dict[str, Any]:
        metadata = {
            **self.metadata,
            "retrieval_tool": self.tool,
            "retrieval_rank": self.tool_rank,
            "retrieval_score": self.final_score,
            "retrieval_reasons": self.reasons,
        }
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "text": self.text,
            "source_location": self.source_location,
            "metadata": metadata,
        }

    def to_trace(self) -> dict[str, Any]:
        trace = {
            "candidate_id": self.candidate_id,
            "tool": self.tool,
            "tool_rank": self.tool_rank,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "base_score": self.base_score,
            "boost_score": self.boost_score,
            "final_score": self.final_score,
            "reasons": self.reasons,
        }
        warning_codes = self.metadata.get("parser_quality_warning_codes")
        if isinstance(warning_codes, list) and warning_codes:
            trace["parser_quality_warning_codes"] = warning_codes
        return trace


@dataclass(frozen=True)
class OrchestratedAnswer:
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    reranker_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    token_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


def plan_for_query(query: str, *, document_ids: list[str], limit: int) -> RetrievalPlan:
    normalized = query.casefold()
    intent: QueryIntent = "semantic"
    if re.search(r"\b(how many|count|number of|total)\b", normalized):
        intent = "count"
    elif re.search(r"\b(title|name of|collection)\b", normalized):
        intent = "title"
    elif re.search(r"\b(book|hadith|chapter)\s+\d+", normalized):
        intent = "reference"
    elif re.search(r"\b(compare|difference|similarities)\b", normalized):
        intent = "comparison"
    elif re.search(r"\b(summary|summarize|overview)\b", normalized):
        intent = "summary"

    return RetrievalPlan(
        query=query,
        document_ids=list(document_ids),
        limit=limit,
        intent=intent,
        candidate_limit=max(limit * 2, 20),
    )


def fuse_candidates(
    plan: RetrievalPlan,
    candidates: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    deduped: dict[str, EvidenceCandidate] = {}
    deduped_tools: dict[str, list[str]] = {}

    for candidate in candidates:
        key = _dedupe_key(candidate)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
        else:
            winner = candidate if candidate.base_score > existing.base_score else existing
            loser = existing if winner is candidate else candidate
            deduped[key] = _merge_duplicate_candidate(winner, loser)
        tools = deduped_tools.setdefault(key, [])
        if candidate.tool not in tools:
            tools.append(candidate.tool)

    scored = [
        _score_candidate(plan, candidate, deduped_tools[_dedupe_key(candidate)])
        for candidate in deduped.values()
    ]
    return sorted(
        scored,
        key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
        reverse=True,
    )


def _score_candidate(
    plan: RetrievalPlan,
    candidate: EvidenceCandidate,
    tools: list[str],
) -> EvidenceCandidate:
    reasons: list[str] = []
    boost = candidate.boost_score
    text = candidate.text.casefold()
    title = _metadata_title(candidate.metadata).casefold()
    combined = f"{text} {title}"

    if plan.intent == "count":
        query_terms = _terms(plan.query)
        combined_terms = _terms(combined)
        if re.search(r"\b\d{2,}\b", combined) and query_terms & combined_terms:
            boost += 24.0
            reasons.append("answer_bearing_count")
        if title and query_terms & _terms(title):
            boost += 8.0
            reasons.append("title_match")

    if candidate.tool == "metadata":
        boost += 3.0
        reasons.append("metadata_precision_tool")
    elif candidate.tool == "graph":
        boost += 2.0
        reasons.append("graph_relationship_tool")
    elif candidate.tool == "native":
        boost += 1.0
        reasons.append("native_semantic_tool")

    metadata = {**candidate.metadata, "deduped_tools": tools}
    return EvidenceCandidate(
        candidate_id=candidate.candidate_id,
        text=candidate.text,
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        source_location=candidate.source_location,
        metadata=metadata,
        tool=candidate.tool,
        tool_rank=candidate.tool_rank,
        base_score=candidate.base_score,
        boost_score=boost,
        final_score=candidate.base_score + boost,
        reasons=[*candidate.reasons, *reasons],
    )


def _dedupe_key(candidate: EvidenceCandidate) -> str:
    runtime_source_id = candidate.metadata.get("runtime_source_id")
    if candidate.chunk_id:
        return f"chunk:{candidate.chunk_id}"
    if isinstance(runtime_source_id, str) and runtime_source_id:
        return f"runtime:{runtime_source_id}"
    fingerprint = hashlib.sha1(candidate.text.strip().casefold().encode("utf-8")).hexdigest()
    return f"text:{candidate.document_id or 'unknown'}:{fingerprint}"


def _merge_duplicate_candidate(
    primary: EvidenceCandidate,
    secondary: EvidenceCandidate,
) -> EvidenceCandidate:
    return replace(
        primary,
        metadata=_merge_candidate_metadata(primary.metadata, secondary.metadata),
        reasons=_merge_ordered_strings(primary.reasons, secondary.reasons),
    )


def _merge_candidate_metadata(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    merged = {**secondary, **primary}
    extraction_quality = _merge_extraction_quality(
        secondary.get("extraction_quality"),
        primary.get("extraction_quality"),
    )
    if extraction_quality:
        merged["extraction_quality"] = extraction_quality
    return merged


def _merge_extraction_quality(
    secondary: Any,
    primary: Any,
) -> dict[str, Any]:
    secondary_quality = secondary if isinstance(secondary, dict) else {}
    primary_quality = primary if isinstance(primary, dict) else {}
    merged = {**secondary_quality, **primary_quality}

    parser_warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (secondary_quality, primary_quality):
        warnings = source.get("parser_warnings")
        if not isinstance(warnings, list):
            continue
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            key = json.dumps(warning, sort_keys=True, default=str)
            if key in seen:
                continue
            parser_warnings.append(dict(warning))
            seen.add(key)
    if parser_warnings:
        merged["parser_warnings"] = parser_warnings
    return merged


def _merge_ordered_strings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*primary, *secondary]:
        if item not in merged:
            merged.append(item)
    return merged


def _metadata_title(metadata: dict[str, Any]) -> str:
    document_metadata = metadata.get("document_metadata")
    if isinstance(document_metadata, dict):
        title = document_metadata.get("title")
        if isinstance(title, str):
            return title
    return ""


def _terms(value: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in re.finditer(r"[\w\u0600-\u06FF]+", value, flags=re.UNICODE)
    }

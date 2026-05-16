from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from ragstudio.services.query_understanding import QueryUnderstanding, understand_query

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
    understanding: QueryUnderstanding | None = None
    retrieval_strategy: str = "semantic_hybrid"
    graph_context_required: bool = False


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
    retrieval_pass: str | None = None
    match_features: dict[str, Any] = field(default_factory=dict)
    canonical_reference: str | None = None
    embedding_profile: dict[str, Any] = field(default_factory=dict)
    index_shape: dict[str, Any] = field(default_factory=dict)
    scope_status: str | None = None
    source_quality: dict[str, Any] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)

    def normalized_metadata(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        if self.retrieval_pass:
            metadata["retrieval_pass"] = self.retrieval_pass
        if self.match_features:
            metadata["match_features"] = self.match_features
        if self.canonical_reference:
            metadata["canonical_reference"] = self.canonical_reference
        if self.embedding_profile:
            metadata["embedding_profile"] = self.embedding_profile
        if self.index_shape:
            metadata["index_shape"] = self.index_shape
        if self.scope_status:
            metadata["scope_status"] = self.scope_status
        if self.source_quality:
            metadata["source_quality"] = self.source_quality
        if self.risk_flags:
            metadata["risk_flags"] = self.risk_flags
        return metadata

    def to_source(self) -> dict[str, Any]:
        metadata = {
            **self.normalized_metadata(),
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
        if self.retrieval_pass:
            trace["retrieval_pass"] = self.retrieval_pass
        if self.match_features:
            trace["match_features"] = self.match_features
        if self.canonical_reference:
            trace["canonical_reference"] = self.canonical_reference
        if self.scope_status:
            trace["scope_status"] = self.scope_status
        if self.risk_flags:
            trace["risk_flags"] = self.risk_flags
        return trace


@dataclass(frozen=True)
class OrchestratedAnswer:
    answer: str
    sources: list[dict[str, Any]]
    chunk_traces: list[dict[str, Any]]
    reranker_traces: list[dict[str, Any]]
    timings: dict[str, Any]
    token_metadata: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_type: str | None = None


def plan_for_query(
    query: str,
    *,
    document_ids: list[str],
    limit: int,
    domain_expansion: Any | None = None,
) -> RetrievalPlan:
    understanding = understand_query(query, domain_expansion=domain_expansion)
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

    if understanding.intent in {
        "reference",
        "arabic_exact_token",
        "lexical_expanded_token",
        "phrase_lookup",
    }:
        intent = "reference"
    elif understanding.intent == "count":
        intent = "count"
    elif understanding.intent == "summary":
        intent = "summary"

    return RetrievalPlan(
        query=query,
        document_ids=list(document_ids),
        limit=limit,
        intent=intent,
        candidate_limit=max(limit * 2, 20),
        understanding=understanding,
        retrieval_strategy=understanding.retrieval_strategy,
        graph_context_required=understanding.graph_context_required,
    )


def fuse_candidates(
    plan: RetrievalPlan,
    candidates: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    candidates = _hydrate_parser_warning_metadata(candidates)
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
    ranked = sorted(
        scored,
        key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
        reverse=True,
    )
    return apply_query_aware_ordering(plan, ranked)


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

    if (
        plan.retrieval_strategy in {"reference_first_hybrid", "graph_context_hybrid"}
        and candidate.retrieval_pass == "reference_exact"
    ):
        boost += 12.0
        reasons.append("reference_first_hybrid")

    if plan.graph_context_required and candidate.tool == "graph":
        boost += 8.0
        reasons.append("query_requested_graph_context")

    if plan.retrieval_strategy == "count_metadata_hybrid" and candidate.tool == "metadata":
        boost += 6.0
        reasons.append("count_metadata_hybrid")

    domain_family = _domain_family(candidate.metadata)
    domain_reference_allowed = _quality_allows_domain_reference_boost(candidate.metadata)

    if (
        domain_reference_allowed
        and domain_family in {"tafseer_reference", "hadith_reference", "legal_reference"}
        and candidate.retrieval_pass == "reference_exact"
    ):
        boost += 10.0
        reasons.append(f"{domain_family}_exact")

    if _has_lexical_expanded_evidence(candidate):
        boost += 28.0
        reasons.append("lexical_expanded_exact")

    if (
        domain_family == "tafseer_reference"
        and plan.graph_context_required
        and candidate.tool == "graph"
    ):
        boost += 5.0
        reasons.append("tafseer_graph_context")

    if domain_family == "research_semantic" and candidate.tool == "native":
        boost += 2.0
        reasons.append("research_semantic_native")

    if _has_lexical_expanded_evidence(candidate):
        boost += 28.0
        reasons.append("lexical_expanded_exact")

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
        retrieval_pass=candidate.retrieval_pass,
        match_features=candidate.match_features,
        canonical_reference=candidate.canonical_reference,
        embedding_profile=candidate.embedding_profile,
        index_shape=candidate.index_shape,
        scope_status=candidate.scope_status,
        source_quality=candidate.source_quality,
        risk_flags=candidate.risk_flags,
    )


def _domain_family(metadata: dict[str, Any]) -> str:
    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return "generic"

    raw_tags = domain_metadata.get("tags")
    tags = (
        {str(tag).casefold() for tag in raw_tags if isinstance(tag, str)}
        if isinstance(raw_tags, list)
        else set()
    )
    tokens = {
        str(domain_metadata.get("domain") or "").casefold(),
        str(domain_metadata.get("document_type") or "").casefold(),
        str(domain_metadata.get("collection") or "").casefold(),
        str(domain_metadata.get("content_role") or "").casefold(),
        str(domain_metadata.get("citation_style") or "").casefold(),
        *tags,
    }

    if {"quran_tafseer", "tafseer", "quran"} & tokens:
        return "tafseer_reference"
    if "hadith" in tokens:
        return "hadith_reference"
    if {"legal", "law", "statute", "policy"} & tokens:
        return "legal_reference"
    if {"research", "paper", "report", "scientific"} & tokens:
        return "research_semantic"
    return "generic"


def _quality_allows_domain_reference_boost(metadata: dict[str, Any]) -> bool:
    policy = metadata.get("quality_action_policy")
    if not isinstance(policy, dict):
        return True
    return (
        bool(policy.get("index_exact_arabic", True))
        and policy.get("graph_confidence") != "blocked"
    )


def _has_lexical_expanded_evidence(candidate: EvidenceCandidate) -> bool:
    if candidate.retrieval_pass == "lexical_expanded_token":
        return True

    retrieval_passes = candidate.metadata.get("retrieval_passes")
    if isinstance(retrieval_passes, list) and "lexical_expanded_token" in {
        str(item) for item in retrieval_passes
    }:
        return True

    metadata_match_features = candidate.metadata.get("match_features")
    match_features = (
        metadata_match_features if isinstance(metadata_match_features, dict) else {}
    )
    return bool(
        candidate.match_features.get("lexical_expanded")
        or match_features.get("lexical_expanded")
    )


def _selected_document_count(plan: RetrievalPlan) -> int:
    return len({document_id for document_id in plan.document_ids if document_id})


def _best_candidate_by_document(
    candidates: list[EvidenceCandidate],
) -> dict[str, EvidenceCandidate]:
    best: dict[str, EvidenceCandidate] = {}
    for candidate in candidates:
        if not candidate.document_id:
            continue
        existing = best.get(candidate.document_id)
        if existing is None or candidate.final_score > existing.final_score:
            best[candidate.document_id] = candidate
    return best


def apply_query_aware_ordering(
    plan: RetrievalPlan,
    ranked: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    if _selected_document_count(plan) <= 1:
        return ranked

    best_by_document = _best_candidate_by_document(ranked)
    if len(best_by_document) <= 1:
        return ranked

    if plan.intent == "comparison":
        comparison_head = sorted(
            best_by_document.values(),
            key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
            reverse=True,
        )
        comparison_ids = {candidate.candidate_id for candidate in comparison_head}
        return [
            *comparison_head,
            *[candidate for candidate in ranked if candidate.candidate_id not in comparison_ids],
        ]

    top_window = ranked[: max(plan.limit, 1)]
    top_documents = {candidate.document_id for candidate in top_window if candidate.document_id}
    if len(top_documents) > 1:
        return ranked

    top_score = ranked[0].final_score if ranked else 0.0
    diversity_candidates = [
        candidate
        for candidate in best_by_document.values()
        if candidate.document_id not in top_documents
        and candidate.final_score >= top_score * 0.65
    ]
    if not diversity_candidates:
        return ranked

    diversity_candidate = sorted(
        diversity_candidates,
        key=lambda candidate: (candidate.final_score, -candidate.tool_rank),
        reverse=True,
    )[0]
    return [
        ranked[0],
        diversity_candidate,
        *[
            candidate
            for candidate in ranked[1:]
            if candidate.candidate_id != diversity_candidate.candidate_id
        ],
    ]


def _dedupe_key(candidate: EvidenceCandidate) -> str:
    chunk_identity = candidate.metadata.get("chunk_identity")
    if isinstance(chunk_identity, str) and chunk_identity:
        return f"chunk-identity:{chunk_identity}"
    if candidate.chunk_id:
        return f"chunk:{candidate.chunk_id}"
    canonical_chunk_id = candidate.metadata.get("canonical_chunk_id")
    if isinstance(canonical_chunk_id, str) and canonical_chunk_id:
        return f"canonical-chunk:{canonical_chunk_id}"
    runtime_source_id = candidate.metadata.get("runtime_source_id")
    if isinstance(runtime_source_id, str) and runtime_source_id:
        return f"runtime:{runtime_source_id}"
    fingerprint = hashlib.sha1(candidate.text.strip().casefold().encode("utf-8")).hexdigest()
    return f"text:{candidate.document_id or 'unknown'}:{fingerprint}"


def _hydrate_parser_warning_metadata(
    candidates: list[EvidenceCandidate],
) -> list[EvidenceCandidate]:
    warnings_by_key: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        extraction_quality = candidate.metadata.get("extraction_quality")
        if not isinstance(extraction_quality, dict):
            continue
        warnings = extraction_quality.get("parser_warnings")
        if not isinstance(warnings, list) or not warnings:
            continue
        key = _text_identity_key(candidate)
        warnings_by_key[key] = _merge_extraction_quality(
            warnings_by_key.get(key),
            extraction_quality,
        )

    if not warnings_by_key:
        return candidates

    hydrated: list[EvidenceCandidate] = []
    for candidate in candidates:
        if _parser_warnings(candidate.metadata):
            hydrated.append(candidate)
            continue
        extraction_quality = warnings_by_key.get(_text_identity_key(candidate))
        if not extraction_quality:
            hydrated.append(candidate)
            continue
        merged_quality = _merge_extraction_quality(
            candidate.metadata.get("extraction_quality"),
            extraction_quality,
        )
        hydrated.append(
            replace(
                candidate,
                metadata={
                    **candidate.metadata,
                    "extraction_quality": merged_quality,
                },
            )
        )
    return hydrated


def _text_identity_key(candidate: EvidenceCandidate) -> str:
    fingerprint = hashlib.sha1(candidate.text.strip().casefold().encode("utf-8")).hexdigest()
    return f"{candidate.document_id or 'unknown'}:{fingerprint}"


def _merge_duplicate_candidate(
    primary: EvidenceCandidate,
    secondary: EvidenceCandidate,
) -> EvidenceCandidate:
    match_features = _merge_dict_fields(primary.match_features, secondary.match_features)
    embedding_profile = _merge_dict_fields(
        primary.embedding_profile,
        secondary.embedding_profile,
    )
    index_shape = _merge_dict_fields(primary.index_shape, secondary.index_shape)
    source_quality = _merge_dict_fields(primary.source_quality, secondary.source_quality)
    canonical_reference = primary.canonical_reference or secondary.canonical_reference
    scope_status = primary.scope_status or secondary.scope_status
    risk_flags = _merge_ordered_strings(primary.risk_flags, secondary.risk_flags)
    metadata = _merge_candidate_metadata(
        primary.normalized_metadata(),
        secondary.normalized_metadata(),
    )
    retrieval_passes = _merge_retrieval_passes(primary, secondary)
    if retrieval_passes:
        metadata["retrieval_passes"] = retrieval_passes
    if match_features:
        metadata["match_features"] = match_features
    if canonical_reference:
        metadata["canonical_reference"] = canonical_reference
    if embedding_profile:
        metadata["embedding_profile"] = embedding_profile
    if index_shape:
        metadata["index_shape"] = index_shape
    if scope_status:
        metadata["scope_status"] = scope_status
    if source_quality:
        metadata["source_quality"] = source_quality
    if risk_flags:
        metadata["risk_flags"] = risk_flags
    return replace(
        primary,
        metadata=metadata,
        reasons=_merge_ordered_strings(primary.reasons, secondary.reasons),
        retrieval_pass=primary.retrieval_pass or secondary.retrieval_pass,
        match_features=match_features,
        canonical_reference=canonical_reference,
        embedding_profile=embedding_profile,
        index_shape=index_shape,
        scope_status=scope_status,
        source_quality=source_quality,
        risk_flags=risk_flags,
    )


def _merge_dict_fields(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    merged = {**secondary, **primary}
    for key, value in secondary.items():
        if value and not primary.get(key):
            merged[key] = value
    return merged


def _merge_retrieval_passes(
    primary: EvidenceCandidate,
    secondary: EvidenceCandidate,
) -> list[str]:
    merged: list[str] = []
    for candidate in (primary, secondary):
        passes = candidate.metadata.get("retrieval_passes")
        if isinstance(passes, list):
            for item in passes:
                _append_unique(merged, str(item))
        metadata_pass = candidate.metadata.get("retrieval_pass")
        if isinstance(metadata_pass, str):
            _append_unique(merged, metadata_pass)
        if candidate.retrieval_pass:
            _append_unique(merged, candidate.retrieval_pass)
    return merged


def _append_unique(values: list[str], item: str) -> None:
    if item and item not in values:
        values.append(item)


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


def _parser_warnings(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    extraction_quality = metadata.get("extraction_quality")
    if not isinstance(extraction_quality, dict):
        return []
    warnings = extraction_quality.get("parser_warnings")
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if isinstance(warning, dict)]


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

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.query_hypothesis_service import (
    QueryHypothesis,
    normalize_reference_hypothesis,
)
from ragstudio.services.retrieval_evidence import EvidenceCandidate


@dataclass(frozen=True)
class QueryHypothesisVerification:
    status: str
    reason: str
    target_terms: list[str]
    matched_terms: list[str]
    possible_reference_results: list[dict[str, str | None]] = field(default_factory=list)
    reference: str | None = None
    reference_label: str | None = None
    evidence_candidate_id: str | None = None
    evidence_label: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"

    def to_trace(self) -> dict[str, Any]:
        data = asdict(self)
        data["possible_reference_results"] = self.possible_reference_results or []
        return {"stage": "hypothesis_verification", **data}


class QueryHypothesisVerifier:
    def verify(
        self,
        hypothesis: QueryHypothesis | None,
        evidence: list[EvidenceCandidate],
        *,
        document_ids: list[str],
        expanded_terms: list[str] | None = None,
    ) -> QueryHypothesisVerification:
        if hypothesis is None or not hypothesis.valid:
            return QueryHypothesisVerification(
                status="not_applicable",
                reason=getattr(hypothesis, "reason", None) or "no_valid_hypothesis",
                target_terms=[],
                matched_terms=[],
                possible_reference_results=[],
            )

        target_terms = _verification_terms(hypothesis, expanded_terms=expanded_terms)
        possible_reference_results = _verify_possible_references(
            hypothesis.possible_references,
            evidence,
            document_ids=document_ids,
            target_terms=target_terms,
        )
        confirmed_reference = next(
            (
                item
                for item in possible_reference_results
                if item.get("status") == "confirmed"
            ),
            None,
        )
        if not target_terms:
            if confirmed_reference is not None:
                return QueryHypothesisVerification(
                    status="confirmed",
                    reason="possible_reference_found_in_evidence",
                    target_terms=[],
                    matched_terms=[],
                    possible_reference_results=possible_reference_results,
                    reference=confirmed_reference["reference"],
                    evidence_candidate_id=confirmed_reference["evidence_candidate_id"],
                    evidence_label=confirmed_reference["evidence_label"],
                )
            return QueryHypothesisVerification(
                status="not_applicable",
                reason="no_target_terms",
                target_terms=[],
                matched_terms=[],
                possible_reference_results=possible_reference_results,
            )

        document_id_set = set(document_ids)
        for index, candidate in enumerate(evidence, start=1):
            if document_id_set and candidate.document_id not in document_id_set:
                continue
            matched_terms = _matched_terms(target_terms, candidate)
            if not matched_terms:
                continue
            answer = hypothesis.probable_answer
            reference = _reference(candidate)
            expected_reference = _expected_reference(hypothesis)
            if expected_reference and _normalize_reference(reference) != _normalize_reference(
                expected_reference
            ):
                continue
            return QueryHypothesisVerification(
                status="confirmed",
                reason="target_term_found_in_evidence",
                target_terms=target_terms,
                matched_terms=matched_terms,
                possible_reference_results=possible_reference_results,
                reference=reference or expected_reference,
                reference_label=answer.display_label if answer is not None else None,
                evidence_candidate_id=candidate.candidate_id,
                evidence_label=f"S{index}",
            )

        return QueryHypothesisVerification(
            status="rejected" if evidence else "unverified",
            reason="target_term_not_confirmed_in_evidence",
            target_terms=target_terms,
            matched_terms=[],
            possible_reference_results=possible_reference_results,
        )


def _matched_terms(terms: list[str], candidate: EvidenceCandidate) -> list[str]:
    text = candidate.text
    features = candidate.match_features
    metadata_features = candidate.metadata.get("match_features")
    if not isinstance(metadata_features, dict):
        metadata_features = {}
    feature_terms = {
        str(value)
        for value in [
            features.get("expanded_token"),
            features.get("arabic_token"),
            metadata_features.get("expanded_token"),
            metadata_features.get("arabic_token"),
        ]
        if value
    }
    haystack_arabic = {normalize_arabic_text(token) for token in arabic_tokens(text)}
    haystack_latin = text.casefold()
    matched: list[str] = []
    for term in terms:
        normalized = normalize_arabic_text(term)
        if (
            normalized in haystack_arabic
            or term in feature_terms
            or _latin_term_matches(term, haystack_latin)
        ):
            matched.append(term)
    return list(dict.fromkeys(matched))


def _latin_term_matches(term: str, haystack: str) -> bool:
    if re.search(r"[\u0600-\u06FF]", term):
        return False
    normalized = term.strip().casefold()
    if not normalized:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack) is not None


def _verify_possible_references(
    references: list[str],
    evidence: list[EvidenceCandidate],
    *,
    document_ids: list[str],
    target_terms: list[str],
) -> list[dict[str, str | None]]:
    document_id_set = set(document_ids)
    results: list[dict[str, str | None]] = []
    for reference in references:
        normalized_reference = _normalize_reference(reference)
        match_index: int | None = None
        matched_candidate: EvidenceCandidate | None = None
        rejected_index: int | None = None
        rejected_candidate: EvidenceCandidate | None = None
        for index, candidate in enumerate(evidence, start=1):
            if document_id_set and candidate.document_id not in document_id_set:
                continue
            candidate_references = {
                _normalize_reference(candidate_reference)
                for candidate_reference in _candidate_references(candidate)
            }
            if normalized_reference in candidate_references:
                if target_terms and not _matched_terms(target_terms, candidate):
                    if rejected_candidate is None:
                        rejected_index = index
                        rejected_candidate = candidate
                    continue
                match_index = index
                matched_candidate = candidate
                break

        if matched_candidate is None or match_index is None:
            if rejected_candidate is not None and rejected_index is not None:
                results.append(
                    {
                        "reference": reference,
                        "status": "rejected",
                        "reason": "reference_found_without_target_terms",
                        "evidence_candidate_id": rejected_candidate.candidate_id,
                        "evidence_label": f"S{rejected_index}",
                    }
                )
                continue
            results.append(
                {
                    "reference": reference,
                    "status": "not_found",
                    "reason": "reference_not_in_retrieved_evidence",
                    "evidence_candidate_id": None,
                    "evidence_label": None,
                }
            )
            continue

        results.append(
            {
                "reference": reference,
                "status": "confirmed",
                "reason": "reference_found_in_evidence",
                "evidence_candidate_id": matched_candidate.candidate_id,
                "evidence_label": f"S{match_index}",
            }
        )
    return results


def _candidate_references(candidate: EvidenceCandidate) -> list[str]:
    references: list[str] = []
    if candidate.canonical_reference:
        references.append(candidate.canonical_reference)
    raw_reference = candidate.source_location.get("reference")
    if isinstance(raw_reference, str) and raw_reference:
        references.append(raw_reference)
    reference_metadata = candidate.metadata.get("reference_metadata")
    if isinstance(reference_metadata, dict):
        metadata_references = reference_metadata.get("references")
        if isinstance(metadata_references, list):
            references.extend(str(item) for item in metadata_references if item)
    return list(dict.fromkeys(references))


def _verification_terms(
    hypothesis: QueryHypothesis,
    *,
    expanded_terms: list[str] | None,
) -> list[str]:
    terms = [term.surface for term in hypothesis.target_terms]
    answer = hypothesis.probable_answer
    if answer is not None and answer.matched_term:
        terms.append(answer.matched_term)
    terms.extend(expanded_terms or [])
    return list(dict.fromkeys(term for term in terms if term))


def _expected_reference(hypothesis: QueryHypothesis) -> str | None:
    answer = hypothesis.probable_answer
    if answer is None:
        return None
    return answer.reference


def _reference(candidate: EvidenceCandidate) -> str | None:
    if candidate.canonical_reference:
        return candidate.canonical_reference
    raw_reference = candidate.source_location.get("reference")
    if isinstance(raw_reference, str) and raw_reference:
        return raw_reference
    return None


def _normalize_reference(value: str | None) -> str | None:
    if not value:
        return None
    return normalize_reference_hypothesis(value) or value.strip().casefold()

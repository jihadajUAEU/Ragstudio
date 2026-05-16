from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ragstudio.services.arabic_text import arabic_tokens, normalize_arabic_text
from ragstudio.services.query_hypothesis_service import QueryHypothesis
from ragstudio.services.retrieval_evidence import EvidenceCandidate

_REFERENCE_RE = re.compile(r"\[(?P<reference>\d{1,3}:\d{1,3})\]")


@dataclass(frozen=True)
class QueryHypothesisVerification:
    status: str
    reason: str
    target_terms: list[str]
    matched_terms: list[str]
    reference: str | None = None
    surah: str | None = None
    surah_number: int | None = None
    ayah: int | None = None
    evidence_candidate_id: str | None = None
    evidence_label: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"

    def to_trace(self) -> dict[str, Any]:
        return {"stage": "hypothesis_verification", **asdict(self)}


class QueryHypothesisVerifier:
    def verify(
        self,
        hypothesis: QueryHypothesis | None,
        evidence: list[EvidenceCandidate],
        *,
        document_ids: list[str],
    ) -> QueryHypothesisVerification:
        if hypothesis is None or not hypothesis.valid:
            return QueryHypothesisVerification(
                status="not_applicable",
                reason=getattr(hypothesis, "reason", None) or "no_valid_hypothesis",
                target_terms=[],
                matched_terms=[],
            )

        target_terms = _verification_terms(hypothesis)
        if not target_terms:
            return QueryHypothesisVerification(
                status="not_applicable",
                reason="no_target_terms",
                target_terms=[],
                matched_terms=[],
            )

        for index, candidate in enumerate(evidence, start=1):
            if document_ids and candidate.document_id not in set(document_ids):
                continue
            matched_terms = _matched_terms(target_terms, candidate)
            if not matched_terms:
                continue
            answer = hypothesis.probable_answer
            reference = _reference(candidate, matched_terms=matched_terms)
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
                reference=reference or expected_reference,
                surah=answer.surah if answer is not None else None,
                surah_number=answer.surah_number if answer is not None else None,
                ayah=answer.ayah if answer is not None else None,
                evidence_candidate_id=candidate.candidate_id,
                evidence_label=f"S{index}",
            )

        return QueryHypothesisVerification(
            status="rejected",
            reason="target_term_not_confirmed_in_evidence",
            target_terms=target_terms,
            matched_terms=[],
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
    matched: list[str] = []
    for term in terms:
        normalized = normalize_arabic_text(term)
        if normalized in haystack_arabic or term in feature_terms:
            matched.append(term)
    if not matched and feature_terms and candidate.retrieval_pass == "lexical_expanded_token":
        matched.extend(sorted(feature_terms))
    return list(dict.fromkeys(matched))


def _verification_terms(hypothesis: QueryHypothesis) -> list[str]:
    terms = [term.surface for term in hypothesis.target_terms]
    answer = hypothesis.probable_answer
    if answer is not None and answer.matched_term:
        terms.append(answer.matched_term)
    return list(dict.fromkeys(term for term in terms if term))


def _expected_reference(hypothesis: QueryHypothesis) -> str | None:
    answer = hypothesis.probable_answer
    if answer is None:
        return None
    if answer.reference:
        return answer.reference
    if answer.surah_number is not None and answer.ayah is not None:
        return f"{answer.surah_number}:{answer.ayah}"
    return None


def _reference(candidate: EvidenceCandidate, *, matched_terms: list[str]) -> str | None:
    if candidate.canonical_reference:
        return candidate.canonical_reference
    raw_reference = candidate.source_location.get("reference")
    if isinstance(raw_reference, str) and raw_reference:
        return raw_reference
    section_reference = _section_reference(candidate.text, matched_terms=matched_terms)
    if section_reference:
        return section_reference
    match = _REFERENCE_RE.search(candidate.text)
    return match.group("reference") if match else None


def _section_reference(text: str, *, matched_terms: list[str]) -> str | None:
    matches = list(_REFERENCE_RE.finditer(text))
    if not matches:
        return None
    normalized_terms = {normalize_arabic_text(term) for term in matched_terms if term}
    for index, match in enumerate(matches):
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[section_start:section_end]
        section_tokens = {normalize_arabic_text(token) for token in arabic_tokens(section)}
        if normalized_terms & section_tokens:
            return match.group("reference")
    return None


def _normalize_reference(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().casefold()

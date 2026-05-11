from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ragstudio.services.retrieval_evidence import EvidenceCandidate
from ragstudio.services.retrieval_metrics import candidate_references


@dataclass(frozen=True)
class GroundingValidationResult:
    status: str
    failures: list[dict[str, Any]]
    cited_labels: list[str]
    available_labels: list[str]

    def to_trace(self) -> dict[str, Any]:
        return {
            "stage": "grounding_validation",
            "status": self.status,
            "failures": self.failures,
            "cited_labels": self.cited_labels,
            "available_labels": self.available_labels,
        }


class GroundingValidator:
    SOURCE_RE = re.compile(r"\[S(\d+)\]")

    def validate(
        self,
        *,
        answer: str,
        evidence: list[EvidenceCandidate],
        expected_references: set[str] | None = None,
    ) -> GroundingValidationResult:
        expected_references = expected_references or set()
        available_labels = [f"S{index}" for index, _ in enumerate(evidence, start=1)]
        cited_labels = list(
            dict.fromkeys(f"S{match}" for match in self.SOURCE_RE.findall(answer))
        )
        failures: list[dict[str, Any]] = []

        for label in cited_labels:
            if label not in available_labels:
                failures.append(
                    {
                        "code": "unknown_source_label",
                        "detail": (
                            f"Answer cites [{label}], but "
                            f"{_available_label_message(available_labels)}."
                        ),
                    }
                )

        if _is_no_evidence_answer(answer) and any(_is_direct(candidate) for candidate in evidence):
            failures.append(
                {
                    "code": "direct_evidence_ignored",
                    "detail": (
                        "Answer says evidence is unavailable, but direct evidence was "
                        "retrieved."
                    ),
                }
            )

        available_references = (
            set().union(*(candidate_references(candidate) for candidate in evidence))
            if evidence
            else set()
        )
        missing_expected = sorted(expected_references - available_references)
        if missing_expected:
            failures.append(
                {
                    "code": "expected_reference_not_in_sources",
                    "detail": (
                        "Expected references missing from sources: "
                        f"{', '.join(missing_expected)}"
                    ),
                }
            )

        return GroundingValidationResult(
            status="failed" if failures else "grounded",
            failures=failures,
            cited_labels=cited_labels,
            available_labels=available_labels,
        )


def _available_label_message(labels: list[str]) -> str:
    if not labels:
        return "no source labels are available"
    if len(labels) == 1:
        return f"only [{labels[0]}] is available"
    return f"only {_format_labels(labels)} are available"


def _format_labels(labels: list[str]) -> str:
    return ", ".join(f"[{label}]" for label in labels)


def _is_no_evidence_answer(answer: str) -> bool:
    normalized = answer.casefold()
    return (
        "does not support" in normalized
        or "no evidence" in normalized
        or "not found" in normalized
    )


def _is_direct(candidate: EvidenceCandidate) -> bool:
    metadata_features = candidate.metadata.get("match_features")
    features = candidate.match_features or (
        metadata_features if isinstance(metadata_features, dict) else {}
    )
    return bool(
        features.get("reference_exact")
        or features.get("arabic_exact")
        or features.get("target_phrase")
    )

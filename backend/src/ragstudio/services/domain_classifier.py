from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ragstudio.services.reference_contracts import metadata_list_declares_reference_contract


@dataclass(frozen=True, slots=True)
class DomainClassification:
    domain_profile_id: str
    domain_family: str
    layout_hint: str | None
    materialization_hint: str | None
    reference_heavy: bool
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "domain_profile_id": self.domain_profile_id,
            "domain_family": self.domain_family,
            "layout_hint": self.layout_hint,
            "materialization_hint": self.materialization_hint,
            "reference_heavy": self.reference_heavy,
            "signals": list(self.signals),
        }


class DomainClassifier:
    def __init__(self) -> None:
        self._cache: dict[str, DomainClassification] = {}
        self._hits = 0

    def classify(self, domain_metadata: list[dict[str, Any]]) -> DomainClassification:
        cache_key = _cache_key(domain_metadata)
        if cache_key in self._cache:
            self._hits += 1
            return self._cache[cache_key]

        signals = _signals(domain_metadata)
        layout_hint = _layout_hint(signals)

        if metadata_list_declares_reference_contract(domain_metadata):
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="reference_heavy",
                    domain_family="reference_heavy",
                    layout_hint=layout_hint or "reference",
                    materialization_hint="graph",
                    reference_heavy=True,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"legal", "law", "statute", "policy", "contract"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="legal_reference",
                    domain_family="legal_reference",
                    layout_hint=layout_hint or "reference",
                    materialization_hint="graph",
                    reference_heavy=True,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"medical", "clinical", "medicine", "diagnosis", "patient"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="medical_reference",
                    domain_family="medical_reference",
                    layout_hint=layout_hint,
                    materialization_hint=_materialization_hint(layout_hint, "vector"),
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"finance", "financial", "invoice", "tax", "accounting"} & signals:
            effective_layout_hint = layout_hint or "table"
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="financial_reference",
                    domain_family="financial_reference",
                    layout_hint=effective_layout_hint,
                    materialization_hint=_materialization_hint(effective_layout_hint, "vector"),
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"code", "api", "source_code", "stacktrace", "software"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="code_reference",
                    domain_family="code_reference",
                    layout_hint=layout_hint,
                    materialization_hint="vector",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if layout_hint in {"table", "figure", "equation"}:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="multimodal_layout",
                    domain_family="generic",
                    layout_hint=layout_hint,
                    materialization_hint="full",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        if {"research", "paper", "report", "scientific"} & signals:
            return self._remember(
                cache_key,
                DomainClassification(
                    domain_profile_id="general",
                    domain_family="research_semantic",
                    layout_hint=layout_hint,
                    materialization_hint="vector",
                    reference_heavy=False,
                    signals=tuple(sorted(signals)),
                ),
            )
        return self._remember(
            cache_key,
            DomainClassification(
                domain_profile_id="general",
                domain_family="generic",
                layout_hint=layout_hint,
                materialization_hint="vector",
                reference_heavy=False,
                signals=tuple(sorted(signals)),
            ),
        )

    def _remember(
        self,
        cache_key: str,
        classification: DomainClassification,
    ) -> DomainClassification:
        self._cache[cache_key] = classification
        return classification

    def cache_stats(self) -> dict[str, int]:
        return {"size": len(self._cache), "hits": self._hits}


def _signals(domain_metadata: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        for key in (
            "domain",
            "document_type",
            "collection",
            "content_role",
            "citation_style",
            "language",
            "layout_hint",
            "parser_layout",
        ):
            _add_value(values, metadata.get(key))
        for key in ("tags", "layout_types", "modalities"):
            raw_values = metadata.get(key)
            if isinstance(raw_values, list):
                for item in raw_values:
                    _add_value(values, item)
    return values


def _cache_key(domain_metadata: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for metadata in domain_metadata:
        if not isinstance(metadata, dict):
            continue
        document_id = str(metadata.get("document_id") or "")
        fingerprint = str(
            metadata.get("metadata_fingerprint")
            or metadata.get("fingerprint")
            or metadata.get("metadata_version")
            or metadata.get("updated_at")
            or ""
        )
        parts.append(f"{document_id}:{fingerprint}:{sorted(_metadata_values(metadata))}")
    return "|".join(sorted(parts)) or "empty"


def _metadata_values(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in metadata.items():
        if isinstance(value, str):
            values.append(f"{key}={value.casefold()}")
        elif isinstance(value, list):
            values.append(f"{key}={','.join(str(item).casefold() for item in value)}")
    return values


def _add_value(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        values.add(value.strip().casefold())


def _layout_hint(signals: set[str]) -> str | None:
    for layout in ("table", "figure", "equation", "reference"):
        if layout in signals:
            return layout
    return None


def _materialization_hint(layout_hint: str | None, fallback: str) -> str:
    if layout_hint in {"table", "figure", "equation"}:
        return "full"
    return fallback

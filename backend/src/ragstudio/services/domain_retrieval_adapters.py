"""Adapter-owned retrieval signals for non-generic domain behavior.

Generic scoring code consumes the neutral ``RetrievalScoringSignals`` result;
domain vocabulary stays isolated in this adapter module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalScoringSignals:
    count_answer_terms: frozenset[str] = frozenset()
    exact_script_boost: str | None = None
    reference_label: str | None = None


def scoring_signals_for_metadata(metadata: dict[str, Any]) -> RetrievalScoringSignals:
    domain_metadata = metadata.get("domain_metadata")
    if not isinstance(domain_metadata, dict):
        return RetrievalScoringSignals()
    domain = str(domain_metadata.get("domain") or "").casefold()
    collection = str(domain_metadata.get("collection") or "").casefold()
    tags = {
        str(tag).casefold()
        for tag in domain_metadata.get("tags", [])
        if isinstance(tag, str)
    }
    if domain == "hadith" or "hadith" in tags:
        terms = {"hadith", "collection"}
        if "bukhari" in collection:
            terms.add("bukhari")
        return RetrievalScoringSignals(
            count_answer_terms=frozenset(terms),
            exact_script_boost="arabic",
            reference_label="hadith",
        )
    declared_scripts = _declared_scripts(domain_metadata)
    if "arabic" in declared_scripts:
        return RetrievalScoringSignals(exact_script_boost="arabic")
    return RetrievalScoringSignals()


def _declared_scripts(domain_metadata: dict[str, Any]) -> frozenset[str]:
    scripts = {
        str(script).casefold()
        for script in domain_metadata.get("declared_scripts", [])
        if isinstance(script, str)
    }
    script = domain_metadata.get("script")
    if isinstance(script, str) and script.strip():
        scripts.add(script.strip().casefold())
    custom_json = domain_metadata.get("custom_json")
    if isinstance(custom_json, dict):
        for section_name in ("preprocessing", "preprocessing_policy"):
            section = custom_json.get(section_name)
            if not isinstance(section, dict):
                continue
            scripts.update(
                str(value).casefold()
                for value in section.get("expected_scripts", [])
                if isinstance(value, str)
            )
    return frozenset(scripts)

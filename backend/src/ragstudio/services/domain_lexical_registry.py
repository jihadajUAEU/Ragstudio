from typing import Any, Protocol

from ragstudio.services.domain_classifier import DomainClassifier
from ragstudio.services.domain_lexical_adapters import (
    CODE_LEXICAL_ADAPTER,
    FINANCIAL_LEXICAL_ADAPTER,
    LEGAL_LEXICAL_ADAPTER,
    MEDICAL_LEXICAL_ADAPTER,
)
from ragstudio.services.lexical_language_adapters import ArabicLexicalAdapter, LexicalExpansion


class DomainLexicalAdapter(Protocol):
    def supports_query(self, query: str) -> bool:
        ...

    def expand_query(self, query: str) -> LexicalExpansion:
        ...


class DomainLexicalRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, list[DomainLexicalAdapter]] = {}
        self.register("arabic_religious", ArabicLexicalAdapter())
        self.register("legal_reference", LEGAL_LEXICAL_ADAPTER)
        self.register("medical_reference", MEDICAL_LEXICAL_ADAPTER)
        self.register("financial_reference", FINANCIAL_LEXICAL_ADAPTER)
        self.register("code_reference", CODE_LEXICAL_ADAPTER)
        self._family_triggers: dict[str, set[str]] = {
            "arabic_religious": {
                "quran",
                "tafseer",
                "quran_tafseer",
                "hadith",
                "islamic_text",
                "religious_text",
                "fiqh",
                "fatwa",
                "islamic_law",
            },
            "legal_reference": {
                "case_law",
                "contract",
                "law",
                "legal",
                "legal_reference",
                "regulation",
                "statute",
            },
            "medical_reference": {
                "clinical",
                "diagnosis",
                "healthcare",
                "medical",
                "medical_reference",
                "medicine",
                "patient",
                "treatment",
            },
            "financial_reference": {
                "accounting",
                "banking",
                "finance",
                "financial",
                "financial_reference",
                "investment",
                "invoice",
                "tax",
            },
            "code_reference": {
                "api",
                "code",
                "code_reference",
                "programming",
                "software",
                "source_code",
                "stacktrace",
            },
        }

    def register(self, domain_family: str, adapter: DomainLexicalAdapter) -> None:
        normalized_family = domain_family.strip().casefold()
        if not normalized_family:
            raise ValueError("domain_family must not be empty")
        self._adapters.setdefault(normalized_family, []).append(adapter)

    def replace(self, domain_family: str, adapter: DomainLexicalAdapter) -> None:
        normalized_family = domain_family.strip().casefold()
        if not normalized_family:
            raise ValueError("domain_family must not be empty")
        self._adapters[normalized_family] = [adapter]

    def adapters_for(self, domain_family: str) -> list[DomainLexicalAdapter]:
        return list(self._adapters.get(domain_family.strip().casefold(), []))

    def register_triggers(self, domain_family: str, triggers: set[str] | list[str]) -> None:
        normalized_family = domain_family.strip().casefold()
        if not normalized_family:
            raise ValueError("domain_family must not be empty")
        existing = self._family_triggers.setdefault(normalized_family, set())
        existing.update(t.strip().casefold() for t in triggers if t.strip())

    def resolve_domain_family(self, domain_metadata: list[dict[str, Any]]) -> str:
        return DomainClassifier().classify(domain_metadata).domain_family


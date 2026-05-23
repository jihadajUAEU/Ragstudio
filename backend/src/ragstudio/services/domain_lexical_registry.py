from typing import Any, Protocol

from ragstudio.services.domain_classifier import DomainClassifier
from ragstudio.services.domain_lexical_adapters import (
    CODE_LEXICAL_ADAPTER,
    FINANCIAL_LEXICAL_ADAPTER,
    LEGAL_LEXICAL_ADAPTER,
    MEDICAL_LEXICAL_ADAPTER,
)
from ragstudio.services.lexical_language_adapters import LexicalExpansion


class DomainLexicalAdapter(Protocol):
    def supports_query(self, query: str) -> bool:
        ...

    def expand_query(self, query: str) -> LexicalExpansion:
        ...


class DomainLexicalRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, list[DomainLexicalAdapter]] = {}
        self.register("legal_reference", LEGAL_LEXICAL_ADAPTER)
        self.register("medical_reference", MEDICAL_LEXICAL_ADAPTER)
        self.register("financial_reference", FINANCIAL_LEXICAL_ADAPTER)
        self.register("code_reference", CODE_LEXICAL_ADAPTER)

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

    def resolve_domain_family(self, domain_metadata: list[dict[str, Any]]) -> str:
        return DomainClassifier().classify(domain_metadata).domain_family


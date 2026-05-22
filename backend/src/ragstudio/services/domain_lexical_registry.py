from __future__ import annotations

from typing import Protocol

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

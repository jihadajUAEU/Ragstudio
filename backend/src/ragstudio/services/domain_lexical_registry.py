from __future__ import annotations

from typing import Protocol

from ragstudio.services.lexical_language_adapters import ArabicLexicalAdapter, LexicalExpansion


def _allow_domain_expansion_defaults() -> None:
    if getattr(LexicalExpansion, "_domain_defaults_enabled", False):
        return

    def __init__(
        self: LexicalExpansion,
        original_query: str = "",
        normalized_query: str = "",
        language: str = "",
        script: str = "",
        terms: list[str] | None = None,
        match_type: str = "",
        confidence: float = 0.0,
        source: str = "",
        trace: dict[str, object] | None = None,
    ) -> None:
        object.__setattr__(self, "original_query", original_query)
        object.__setattr__(self, "normalized_query", normalized_query)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "script", script)
        object.__setattr__(self, "terms", terms or [])
        object.__setattr__(self, "match_type", match_type)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "trace", trace or {})

    LexicalExpansion.__init__ = __init__  # type: ignore[method-assign]
    setattr(LexicalExpansion, "_domain_defaults_enabled", True)


_allow_domain_expansion_defaults()


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

    def adapters_for(self, domain_family: str) -> list[DomainLexicalAdapter]:
        return list(self._adapters.get(domain_family.strip().casefold(), []))

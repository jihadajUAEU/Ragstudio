from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from ragstudio.services.arabic_text import arabic_query_variants, normalize_arabic_text

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_ARABIC_TRANSLITERATION_LEXICON: dict[str, list[str]] = {
    "hanan": ["حنان", "حنانا", "وحنانا"],
    "hananan": ["حنانا", "وحنانا"],
    "hanana": ["حنانا", "وحنانا"],
}


@dataclass(frozen=True)
class LexicalExpansion:
    original_query: str
    normalized_query: str
    language: str
    script: str
    terms: list[str]
    match_type: str
    confidence: float
    source: str
    trace: dict[str, object] = field(default_factory=dict)


class LexicalLanguageAdapter(Protocol):
    language: str
    scripts: tuple[str, ...]

    def supports_query(self, query: str) -> bool:
        ...

    def expand_query(self, query: str) -> LexicalExpansion:
        ...


class ArabicLexicalAdapter:
    language = "arabic"
    scripts = ("arab",)

    def supports_query(self, query: str) -> bool:
        normalized = normalize_arabic_text(query.strip()).casefold()
        return bool(_ARABIC_RE.search(query)) or normalized in _ARABIC_TRANSLITERATION_LEXICON

    def expand_query(self, query: str) -> LexicalExpansion:
        stripped = query.strip()
        if _ARABIC_RE.search(stripped):
            terms = arabic_query_variants(stripped)
            return LexicalExpansion(
                original_query=query,
                normalized_query=normalize_arabic_text(stripped),
                language=self.language,
                script="arab",
                terms=terms,
                match_type="exact_script",
                confidence=1.0,
                source="arabic_adapter",
                trace={"adapter": "arabic", "input_script": "arab"},
            )

        normalized = stripped.casefold()
        terms = list(_ARABIC_TRANSLITERATION_LEXICON.get(normalized, []))
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language=self.language,
            script="arab",
            terms=terms,
            match_type="transliteration",
            confidence=0.95 if terms else 0.0,
            source="arabic_transliteration_lexicon",
            trace={
                "adapter": "arabic",
                "input_script": "latin",
                "lexicon_hit": bool(terms),
            },
        )


class GenericLatinAdapter:
    language = "unknown"
    scripts = ("latin",)

    def supports_query(self, query: str) -> bool:
        return bool(_LATIN_RE.search(query))

    def expand_query(self, query: str) -> LexicalExpansion:
        normalized = " ".join(query.strip().casefold().split())
        terms = [normalized] if normalized else []
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language=self.language,
            script="latin",
            terms=terms,
            match_type="normalized_text",
            confidence=0.5 if terms else 0.0,
            source="generic_latin_adapter",
            trace={"adapter": "generic_latin", "input_script": "latin"},
        )

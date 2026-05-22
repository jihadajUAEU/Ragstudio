from __future__ import annotations

from dataclasses import dataclass

from ragstudio.services.lexical_language_adapters import LexicalExpansion


@dataclass(frozen=True, slots=True)
class KeywordLexicalAdapter:
    source: str
    keyword_map: dict[str, tuple[str, ...]]

    def supports_query(self, query: str) -> bool:
        normalized = query.casefold()
        return any(keyword in normalized for keyword in self.keyword_map)

    def expand_query(self, query: str) -> LexicalExpansion:
        normalized = " ".join(query.strip().casefold().split())
        terms: list[str] = []
        for keyword, expansions in self.keyword_map.items():
            if keyword in normalized:
                terms.extend(expansions)
        return LexicalExpansion(
            original_query=query,
            normalized_query=normalized,
            language="english",
            script="latin",
            terms=_dedupe(terms),
            match_type="domain_keyword",
            confidence=0.8 if terms else 0.0,
            source=self.source,
            trace={"adapter": self.source, "keywords": list(self.keyword_map)},
        )


LEGAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="legal_keyword_adapter",
    keyword_map={
        "contract": ("contract", "agreement", "clause"),
        "section": ("section", "article", "provision"),
        "statute": ("statute", "regulation", "law"),
        "breach": ("breach", "violation", "default"),
    },
)

MEDICAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="medical_keyword_adapter",
    keyword_map={
        "diagnosis": ("diagnosis", "condition", "finding"),
        "treatment": ("treatment", "therapy", "intervention"),
        "patient": ("patient", "clinical", "case"),
        "dose": ("dose", "dosage", "medication"),
    },
)

FINANCIAL_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="financial_keyword_adapter",
    keyword_map={
        "invoice": ("invoice", "bill", "amount"),
        "tax": ("tax", "vat", "withholding"),
        "revenue": ("revenue", "income", "sales"),
        "expense": ("expense", "cost", "liability"),
    },
)

CODE_LEXICAL_ADAPTER = KeywordLexicalAdapter(
    source="code_keyword_adapter",
    keyword_map={
        "api": ("api", "endpoint", "request"),
        "error": ("error", "exception", "stacktrace"),
        "function": ("function", "method", "call"),
        "class": ("class", "object", "type"),
    },
)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped

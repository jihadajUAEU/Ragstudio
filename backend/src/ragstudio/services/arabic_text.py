from __future__ import annotations

import re
import unicodedata

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
ARABIC_TOKEN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")
ALEF_TRANSLATION = str.maketrans(
    {
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0622": "\u0627",
        "\u0671": "\u0627",
        "\u0649": "\u064a",
    }
)


def normalize_arabic_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(ALEF_TRANSLATION)
    normalized = normalized.replace("ـ", "")
    normalized = ARABIC_DIACRITICS.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def arabic_tokens(value: str) -> list[str]:
    normalized = normalize_arabic_text(value)
    tokens: list[str] = []
    for match in ARABIC_TOKEN.finditer(normalized):
        token = match.group(0)
        if token not in tokens:
            tokens.append(token)
        if token.startswith("و") and len(token) > 2 and token[1:] not in tokens:
            tokens.append(token[1:])
    return tokens


def arabic_query_variants(query: str) -> list[str]:
    normalized = normalize_arabic_text(query)
    variants = [normalized] if normalized else []
    if normalized.startswith("و") and len(normalized) > 2:
        variants.append(normalized[1:])
    return list(dict.fromkeys(variants))

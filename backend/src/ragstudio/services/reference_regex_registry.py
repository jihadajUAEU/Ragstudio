from __future__ import annotations

import re

ARABIC_DIACRITICS_PATTERN = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)
ARABIC_TOKEN_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")

SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "arabic": re.compile(
        r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
    ),
    "latin": re.compile(r"[A-Za-z]"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "greek": re.compile(r"[\u0370-\u03ff]"),
    "hebrew": re.compile(r"[\u0590-\u05ff]"),
    "devanagari": re.compile(r"[\u0900-\u097f]"),
    "han": re.compile(r"[\u4e00-\u9fff]"),
}

REFERENCE_PATTERN = re.compile(
    r"(?P<prefix>\bQuran\s+)?(?P<bracket>\[)?"
    r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
    r"(?(bracket)\])",
    flags=re.IGNORECASE,
)
CHAPTER_ONLY_PATTERN = re.compile(
    r"\b(?:surah|sura|chapter)\s+(?P<chapter>\d{1,4})\b",
    flags=re.IGNORECASE,
)
LEGAL_SECTION_PATTERN = re.compile(
    r"(?:\bsection\b|\bsec\.?|§)\s*(?P<section>\d+(?:\.\d+)*)",
    flags=re.IGNORECASE,
)
PAGE_LINE_PATTERN = re.compile(
    r"\b(?:page|p\.?)\s*(?P<page>\d+)(?:\s*(?:[:,-]\s*)?(?:line|l\.?)\s*(?P<line>\d+))?",
    flags=re.IGNORECASE,
)
BOOK_HADITH_PATTERN = re.compile(
    r"\bBook\s+(?P<book>\d+)\s*,?\s*Hadith\s+(?P<hadith>\d+)\b",
    flags=re.IGNORECASE,
)

QUERY_ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF]")
QUERY_REFERENCE_PATTERN = re.compile(r"\[(?P<reference>\d{1,3}:\d{1,3})\]")
QUERY_GRAPH_CONTEXT_PATTERN = re.compile(
    r"\b(?:surrounding|connected|related|nearby|neighboring|previous|next|before|after|context|around)\b",
    re.IGNORECASE,
)
QUERY_PHRASE_PATTERN = re.compile(
    r"\b(?:(?:says|say)(?!\s+about\b)|phrase|quote)\b(?:\s+(?:that|is|was|as))?\s+(?P<phrase>.+)",
    re.IGNORECASE,
)
QUERY_NORMALIZED_PHRASE_PATTERN = re.compile(r"[^0-9A-Za-z\u0600-\u06FF]+")

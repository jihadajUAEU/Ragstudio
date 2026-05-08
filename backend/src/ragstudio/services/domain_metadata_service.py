from __future__ import annotations

import json
import re
from pathlib import Path

from ragstudio.schemas.parsing import (
    DomainMetadata,
    DomainMetadataSuggestIn,
    DomainProfileIn,
    DomainProfileOut,
)

BUILTIN_PROFILES: list[DomainProfileOut] = [
    DomainProfileOut(
        id="generic",
        name="Generic document",
        description="General uploaded document.",
        metadata=DomainMetadata(domain="generic", document_type="document", tags=["document"]),
    ),
    DomainProfileOut(
        id="research_paper",
        name="Research paper",
        description="Academic or technical research paper.",
        metadata=DomainMetadata(
            domain="research",
            document_type="paper",
            tags=["research", "paper"],
            citation_style="academic",
        ),
    ),
    DomainProfileOut(
        id="policy_admin",
        name="Policy/admin document",
        description="Administrative, policy, procedure, or governance document.",
        metadata=DomainMetadata(
            domain="policy",
            document_type="admin_document",
            tags=["policy", "admin"],
            expected_structure="sections",
        ),
    ),
    DomainProfileOut(
        id="table_spreadsheet",
        name="Table/spreadsheet",
        description="Structured rows, sheets, registers, or tabular data.",
        metadata=DomainMetadata(
            domain="data",
            document_type="table",
            tags=["table", "spreadsheet"],
            expected_structure="rows",
        ),
    ),
    DomainProfileOut(
        id="hadith",
        name="Hadith",
        description="Hadith collection or commentary.",
        metadata=DomainMetadata(
            domain="hadith",
            document_type="collection",
            language="mixed",
            tags=["hadith", "arabic", "english"],
            citation_style="book_hadith",
            expected_structure="book_hadith_records",
            reference_pattern="Book N, Hadith N",
            script="mixed",
            content_role="hadith",
        ),
    ),
    DomainProfileOut(
        id="quran_tafseer",
        name="Quran/Tafseer",
        description="Quran translation, tafseer, or verse explanation.",
        metadata=DomainMetadata(
            domain="quran_tafseer",
            document_type="commentary",
            language="mixed",
            tags=["quran", "tafseer", "arabic", "english"],
            citation_style="surah_ayah",
            expected_structure="surah_ayah_sections",
            script="mixed",
            content_role="tafseer",
        ),
    ),
    DomainProfileOut(
        id="fatwa_fiqh",
        name="Fatwa/Fiqh",
        description="Fatwa, legal ruling, or jurisprudence material.",
        metadata=DomainMetadata(
            domain="fiqh",
            document_type="fatwa",
            language="mixed",
            tags=["fatwa", "fiqh", "ruling"],
            expected_structure="question_answer",
            script="mixed",
            content_role="fiqh ruling",
        ),
    ),
]


class DomainMetadataService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.profile_path = data_dir / "domain-profiles.json"

    def list_profiles(self) -> list[DomainProfileOut]:
        return [*BUILTIN_PROFILES, *self._saved_profiles()]

    def upsert_profile(self, profile: DomainProfileIn) -> DomainProfileOut:
        saved = DomainProfileOut.model_validate(profile.model_dump())
        profiles = {item.id: item for item in self._saved_profiles()}
        profiles[saved.id] = saved
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps([item.model_dump() for item in profiles.values()], indent=2),
            encoding="utf-8",
        )
        return saved

    def suggest(self, payload: DomainMetadataSuggestIn) -> DomainMetadata:
        profile = next(
            (item for item in self.list_profiles() if item.id == payload.profile_id),
            BUILTIN_PROFILES[0],
        )
        metadata = profile.metadata.model_copy(deep=True)
        sources = set(metadata.metadata_sources)
        sources.add("profile")
        filename_text = f"{payload.filename} {payload.sample_text}".casefold()
        if "bukhari" in filename_text:
            metadata.collection = "Sahih al-Bukhari"
            sources.add("heuristic")
        elif "tirmidhi" in filename_text:
            metadata.collection = "Jami at-Tirmidhi"
            sources.add("heuristic")
        elif "muslim" in filename_text:
            metadata.collection = "Sahih Muslim"
            sources.add("heuristic")
        if re.search(r"book\s+\d+\s*,?\s*hadith\s+\d+", filename_text):
            metadata.reference_pattern = "Book N, Hadith N"
            sources.add("heuristic")
        if payload.filename.lower().endswith((".csv", ".xlsx", ".xls")):
            metadata.domain = "data"
            metadata.document_type = "table"
            metadata.tags = sorted({*metadata.tags, "table"})
            sources.add("heuristic")
        metadata.metadata_sources = sorted(sources)
        return metadata

    def _saved_profiles(self) -> list[DomainProfileOut]:
        if not self.profile_path.exists():
            return []
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [DomainProfileOut.model_validate(item) for item in data]

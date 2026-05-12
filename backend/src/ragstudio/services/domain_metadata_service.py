from __future__ import annotations

import json
from pathlib import Path

from ragstudio.schemas.parsing import (
    DomainMetadata,
    DomainProfileIn,
    DomainProfileOut,
)


def reference_custom_json(
    *,
    reference_type: str | None = None,
    display: str | None = None,
    canonical_ref_template: str | None = None,
    fields: dict[str, str] | None = None,
    relationships: dict[str, list[str]] | None = None,
    chunking: dict[str, object] | None = None,
    reference_resolution: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
    parser_normalization: dict[str, object] | None = None,
    retrieval: dict[str, bool] | None = None,
    graph: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {}
    if reference_type or display or canonical_ref_template or fields:
        schema: dict[str, object] = {}
        if reference_type:
            schema["type"] = reference_type
        if display:
            schema["display"] = display
        if canonical_ref_template:
            schema["canonical_ref_template"] = canonical_ref_template
        if fields:
            schema["fields"] = fields
        value["reference_schema"] = schema
    if relationships:
        value["relationships"] = relationships
    if chunking:
        value["chunking"] = chunking
    if reference_resolution:
        value["reference_resolution"] = reference_resolution
    if provenance:
        value["provenance"] = provenance
    if parser_normalization:
        value["parser_normalization"] = parser_normalization
    if retrieval:
        value["retrieval"] = retrieval
    if graph:
        value["graph"] = graph
    return value


GENERIC_PARSER_NORMALIZATION: dict[str, object] = {
    "allow_equations_as_content": False,
    "recover_text_bearing_blocks_as_prose": False,
    "preserve_original_block_type": True,
}

PROSE_PARSER_NORMALIZATION: dict[str, object] = {
    "allow_equations_as_content": False,
    "recover_text_bearing_blocks_as_prose": True,
    "preserve_original_block_type": True,
}

TECHNICAL_PARSER_NORMALIZATION: dict[str, object] = {
    "allow_equations_as_content": True,
    "recover_text_bearing_blocks_as_prose": False,
    "preserve_original_block_type": True,
}

TABULAR_PARSER_NORMALIZATION: dict[str, object] = {
    "allow_equations_as_content": True,
    "recover_text_bearing_blocks_as_prose": True,
    "preserve_original_block_type": True,
}


BUILTIN_PROFILES: list[DomainProfileOut] = [
    DomainProfileOut(
        id="generic",
        name="Generic document",
        description="General uploaded document.",
        metadata=DomainMetadata(
            domain="generic",
            document_type="document",
            tags=["document"],
            expected_structure="sections",
            custom_json=reference_custom_json(
                chunking={"unit": "section"},
                parser_normalization=GENERIC_PARSER_NORMALIZATION,
            ),
        ),
    ),
    DomainProfileOut(
        id="research_paper",
        name="Research paper",
        description="Academic or technical research paper.",
        metadata=DomainMetadata(
            domain="research",
            document_type="paper",
            tags=["research", "paper", "academic", "figures", "tables"],
            citation_style="academic",
            expected_structure="abstract_sections_references",
            custom_json=reference_custom_json(
                chunking={"unit": "section", "preserve_parallel_text": False},
                parser_normalization=TECHNICAL_PARSER_NORMALIZATION,
                retrieval={"boost_same_chapter": True},
            ),
        ),
    ),
    DomainProfileOut(
        id="policy_admin",
        name="Policy/admin document",
        description="Administrative, policy, procedure, or governance document.",
        metadata=DomainMetadata(
            domain="policy",
            document_type="admin_document",
            tags=["policy", "admin", "procedure", "governance"],
            citation_style="section",
            expected_structure="sections",
            reference_pattern="section_number",
            custom_json=reference_custom_json(
                reference_type="section",
                display="Section {section}",
                fields={"section": "section_number"},
                relationships={"section": ["same_section"], "next": ["next_section"]},
                chunking={"unit": "section"},
                parser_normalization=PROSE_PARSER_NORMALIZATION,
                retrieval={"exact_reference_top1": True, "boost_same_chapter": True},
            ),
        ),
    ),
    DomainProfileOut(
        id="table_spreadsheet",
        name="Table/spreadsheet",
        description="Structured rows, sheets, registers, or tabular data.",
        metadata=DomainMetadata(
            domain="data",
            document_type="table",
            tags=["table", "spreadsheet", "rows", "columns"],
            expected_structure="rows",
            custom_json=reference_custom_json(
                chunking={"unit": "row"},
                parser_normalization=TABULAR_PARSER_NORMALIZATION,
                retrieval={"exact_reference_top1": False},
            ),
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
            tags=["hadith", "islamic_text", "arabic", "english", "religious_text"],
            citation_style="book_hadith",
            expected_structure="book_chapter_hadith",
            reference_pattern="Book N, Hadith N",
            script="mixed",
            content_role="primary_source",
            custom_json=reference_custom_json(
                reference_type="book_hadith",
                display="Book {book}, Hadith {hadith}",
                canonical_ref_template="book:{book}:hadith:{hadith}",
                fields={
                    "book": "book_number",
                    "hadith": "hadith_number",
                    "chapter": "chapter_title",
                },
                relationships={
                    "previous": ["same_book", "hadith - 1"],
                    "next": ["same_book", "hadith + 1"],
                    "book": ["same_book"],
                    "chapter": ["same_chapter"],
                },
                chunking={
                    "unit": "hadith",
                    "include_neighbors": 1,
                    "preserve_parallel_text": True,
                    "merge_reference_header_with_body": True,
                },
                reference_resolution={
                    "enabled": True,
                    "build_canonical_units": True,
                    "carry_forward_body_blocks": True,
                    "header_only_policy": "provenance_only",
                    "continuation_policy": "until_next_reference",
                    "max_page_gap": 2,
                    "require_single_reference_per_answerable_chunk": True,
                },
                provenance={
                    "preserve_original_blocks": True,
                    "block_preview_chars": 160,
                    "store_text_hash": True,
                },
                parser_normalization=PROSE_PARSER_NORMALIZATION,
                retrieval={
                    "exact_reference_top1": True,
                    "boost_same_chapter": True,
                    "boost_neighbor_verses": True,
                },
                graph={
                    "node_types": ["collection", "book", "chapter", "hadith", "chunk"],
                    "edge_types": [
                        "contains",
                        "references",
                        "next_hadith",
                        "same_book",
                        "same_chapter",
                    ],
                    "materialize_from": ["mineru_structure", "reference_metadata"],
                    "confidence_policy": "evidence_required",
                },
            ),
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
            tags=["quran", "tafseer", "arabic", "english", "religious_text"],
            citation_style="surah_ayah",
            expected_structure="surah_ayah_sections",
            reference_pattern="surah_number:verse_number",
            script="mixed",
            content_role="tafseer",
            custom_json=reference_custom_json(
                reference_type="chapter_verse",
                display="{chapter}:{verse}",
                canonical_ref_template="{chapter}:{verse}",
                fields={
                    "chapter": "surah_number",
                    "verse": "ayah_number",
                    "page": "page_number",
                },
                relationships={
                    "previous": ["same_chapter", "verse - 1"],
                    "next": ["same_chapter", "verse + 1"],
                    "chapter": ["same_chapter"],
                    "page": ["same_page"],
                },
                chunking={
                    "unit": "verse",
                    "include_neighbors": 1,
                    "preserve_parallel_text": True,
                    "merge_reference_header_with_body": True,
                },
                reference_resolution={
                    "enabled": True,
                    "build_canonical_units": True,
                    "carry_forward_body_blocks": True,
                    "header_only_policy": "provenance_only",
                    "continuation_policy": "until_next_reference",
                    "max_page_gap": 1,
                    "require_single_reference_per_answerable_chunk": True,
                },
                provenance={
                    "preserve_original_blocks": True,
                    "block_preview_chars": 160,
                    "store_text_hash": True,
                },
                parser_normalization=PROSE_PARSER_NORMALIZATION,
                retrieval={
                    "exact_reference_top1": True,
                    "boost_same_chapter": True,
                    "boost_neighbor_verses": True,
                },
                graph={
                    "node_types": ["surah", "ayah", "translation", "chunk"],
                    "edge_types": [
                        "contains",
                        "references",
                        "next_ayah",
                        "same_surah",
                        "translation_of",
                    ],
                    "materialize_from": ["mineru_structure", "reference_metadata"],
                    "confidence_policy": "evidence_required",
                },
            ),
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
            tags=["fatwa", "fiqh", "ruling", "islamic_law", "question_answer"],
            citation_style="question_answer",
            expected_structure="question_answer",
            script="mixed",
            content_role="fiqh ruling",
            custom_json=reference_custom_json(
                relationships={
                    "topic": ["same_topic"],
                    "question": ["answer"],
                },
                chunking={"unit": "question_answer"},
                parser_normalization=PROSE_PARSER_NORMALIZATION,
                retrieval={"boost_same_chapter": True},
            ),
        ),
    ),
]


class DomainMetadataService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.profile_path = data_dir / "domain-profiles.json"

    def list_profiles(self) -> list[DomainProfileOut]:
        return [*BUILTIN_PROFILES, *self._saved_profiles()]

    def get_profile(self, profile_id: str) -> DomainProfileOut | None:
        return next(
            (profile for profile in self.list_profiles() if profile.id == profile_id),
            None,
        )

    def upsert_profile(self, profile: DomainProfileIn) -> DomainProfileOut:
        saved = DomainProfileOut.model_validate(profile.model_dump())
        if saved.id in {item.id for item in BUILTIN_PROFILES}:
            raise ValueError(f"Domain profile id '{saved.id}' is reserved.")
        profiles = {item.id: item for item in self._saved_profiles()}
        profiles[saved.id] = saved
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps([item.model_dump() for item in profiles.values()], indent=2),
            encoding="utf-8",
        )
        return saved

    def _saved_profiles(self) -> list[DomainProfileOut]:
        if not self.profile_path.exists():
            return []
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [DomainProfileOut.model_validate(item) for item in data]

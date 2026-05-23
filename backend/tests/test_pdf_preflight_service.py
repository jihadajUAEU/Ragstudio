import sys
from pathlib import Path
from types import SimpleNamespace

from ragstudio.services.pdf_preflight_service import PdfPreflightService


def test_preflight_fails_reference_unit_missing_arabic(tmp_path, monkeypatch):
    pdf_path = tmp_path / "missing-arabic.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("[1:4] It is You we worship and You we ask for help.")],
            ]
        },
    )
    contract = _verified_reference_contract({
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "failed"
    assert result.inspected_pages == 1
    assert result.missing_arabic_unit_count == 1
    assert len(result.issues) == 1
    assert result.issues[0].code == "reference_unit_missing_expected_script"
    assert result.issues[0].page == 1
    assert result.issues[0].reference == "[1:4]"


def test_preflight_uses_vision_sample_pages_for_sample_mode(tmp_path, monkeypatch):
    pdf_path = tmp_path / "vision-sample-pages.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("[1:1] English only reference unit.")],
                [
                    _text_block(
                        "[1:2] \u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647 "
                        "All praise is due to Allah."
                    )
                ],
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "sample_pages": [2],
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    })

    sample_result = PdfPreflightService().inspect(pdf_path, contract, mode="sample")
    full_result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert sample_result.status == "passed"
    assert sample_result.inspected_pages == 1
    assert sample_result.missing_arabic_unit_count == 0
    assert full_result.status == "failed"
    assert full_result.inspected_pages == 2
    assert full_result.missing_arabic_unit_count == 1


def test_preflight_fails_when_reference_contract_has_no_reference_units(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "scrambled-reference-layer.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("Arabic and English text exists but anchors are scrambled.")],
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_parallel_arabic_and_english",
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "failed"
    assert result.issues[0].code == "reference_unit_missing"


def test_preflight_does_not_require_reference_units_for_unverified_contract(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "unverified-reference-layer.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("Arabic and English text exists but anchors are contextual.")],
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_parallel_arabic_and_english",
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    })
    contract["reference_contract"]["verified"] = False

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "passed"
    assert result.issues == []


def test_preflight_does_not_fail_for_one_sample_page_without_reference_units(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "cover-plus-reference-pages.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("Surah heading and publication text.")],
                [_text_block("[1:1] \u0627\u0644\u062d\u0645\u062f English.")],
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_parallel_arabic_and_english",
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "passed"
    assert result.reference_unit_count == 1
    assert [issue.code for issue in result.issues] == ["reference_unit_missing"]


def test_preflight_uses_min_reference_script_pass_ratio(tmp_path, monkeypatch):
    pdf_path = tmp_path / "partial-script-pass.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "[1:1] \u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647 "
                        "All praise.\n[1:2] English only."
                    )
                ],
            ]
        },
    )
    contract = _verified_reference_contract({
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
            "min_reference_script_pass_ratio": 0.5,
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "passed"
    assert result.reference_unit_count == 2
    assert result.passed_reference_script_ratio == 0.5
    assert result.missing_arabic_unit_count == 1


def test_preflight_uses_preprocessing_sample_pages_before_vision_pages(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "preprocessing-sample-pages.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("[1:1] English only reference unit.")],
                [
                    _text_block(
                        "[1:2] \u0627\u0644\u062d\u0645\u062f \u0644\u0644\u0647 "
                        "All praise is due to Allah."
                    )
                ],
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "sample_pages": [1],
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "sample_pages": [2],
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract, mode="sample")

    assert result.status == "passed"
    assert result.inspected_pages == 1
    assert result.missing_arabic_unit_count == 0


def test_preflight_adds_representative_pages_to_configured_large_pdf_sample(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "large-vision-sample-pages.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block(f"[{page}:1] \u0627\u0644\u062d\u0645\u062f English.")]
                for page in range(1, 101)
            ]
        },
    )
    contract = _verified_reference_contract({
        "vision_analysis": {
            "sample_pages": [2, 3],
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract, mode="sample")

    assert result.status == "passed"
    assert result.inspected_page_numbers == [2, 3, 1, 50, 100]


def test_preflight_falls_back_to_representative_sample_pages(tmp_path, monkeypatch):
    pdf_path = tmp_path / "large-document.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block(f"[{page}:1] English only reference unit.")]
                for page in range(1, 11)
            ]
        },
    )
    contract = _verified_reference_contract({
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
    })

    result = PdfPreflightService().inspect(pdf_path, contract, mode="sample")

    assert result.inspected_page_numbers == [1, 5, 10]
    assert result.inspected_pages == 3


def test_preflight_uses_generic_anchors_to_count_custom_folio_line_units(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "folio-line-contract.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "Folio 12 Line 7 The record begins.\n"
                        "Folio 12 Line 8 The record continues."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "schema_type": "folio_line",
            "canonical_units": True,
            "verified": True,
            "anchors": [
                {
                    "kind": "primary_anchor",
                    "regex": r"Folio\s+(?P<folio>\d+)\s+Line\s+(?P<line>\d+)",
                    "unit_role": "folio_line",
                    "verified": True,
                }
            ],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_folio_line_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 2
    assert result.issues == []


def test_preflight_uses_reference_regexes_from_contract(tmp_path, monkeypatch):
    pdf_path = tmp_path / "quran-reference-forms.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "[1:6] \u0627\u0644\u062d\u0645\u062f English.\n"
                        "Verse 1:7 \u0627\u0644\u062d\u0645\u062f English.\n"
                        "1:8 \u0627\u0644\u062d\u0645\u062f English."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "primary_anchor_regex": (
                r"(\bVerse\s+|\[)(?P<chapter>\d{1,4})\s*:\s*"
                r"(?P<verse>\d{1,4})\]?"
            ),
            "inline_reference_regex": (
                r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
            ),
            "canonical_units": True,
            "schema_type": "chapter_verse",
            "verified": True,
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_verse_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 3
    assert result.missing_arabic_unit_count == 0


def test_preflight_falls_back_to_inline_references_when_primary_anchor_absent(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "quran-inline-reference.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [_text_block("1:8 \u0627\u0644\u062d\u0645\u062f English.")],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "primary_anchor_regex": (
                r"(\bVerse\s+|\[)(?P<chapter>\d{1,4})\s*:\s*"
                r"(?P<verse>\d{1,4})\]?"
            ),
            "inline_reference_regex": (
                r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})"
            ),
            "canonical_units": True,
            "schema_type": "chapter_verse",
            "verified": True,
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_verse_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 1
    assert result.issues == []


def test_preflight_contextual_contract_requires_context_anchor(tmp_path, monkeypatch):
    pdf_path = tmp_path / "contextless-numbered-list.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "104 \u0627\u0644\u062d\u0645\u062f English.\n"
                        "105 \u0627\u0644\u062d\u0645\u062f English."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "context_anchor_regex": r"\bSurah\s+(?P<chapter>\d{1,4})\b",
            "unit_anchor_regex": r"\b(?P<verse>10[45])\b",
            "canonical_units": True,
            "schema_type": "chapter_verse",
            "strategy": "contextual_unit",
            "verified": True,
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_verse_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "failed"
    assert result.reference_unit_count == 0
    assert [issue.code for issue in result.issues] == ["reference_unit_missing"]


def test_preflight_contextual_contract_counts_units_after_context(tmp_path, monkeypatch):
    pdf_path = tmp_path / "contextual-numbered-list.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "Surah 7\n"
                        "104 \u0627\u0644\u062d\u0645\u062f English.\n"
                        "105 \u0627\u0644\u062d\u0645\u062f English."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "context_anchor_regex": r"\bSurah\s+(?P<chapter>\d{1,4})\b",
            "unit_anchor_regex": r"\b(?P<verse>10[45])\b",
            "canonical_units": True,
            "schema_type": "chapter_verse",
            "strategy": "contextual_unit",
            "verified": True,
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_verse_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 2
    assert result.issues == []


def test_preflight_contextual_contract_uses_generic_anchors_without_legacy_fields(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "generic-contextual-folio-lines.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "Folio 12\n"
                        "Line 7 The record begins.\n"
                        "Line 8 The record continues."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "schema_type": "folio_line",
            "canonical_units": True,
            "strategy": "contextual_unit",
            "verified": True,
            "anchors": [
                {
                    "kind": "context_anchor",
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit_role": "folio",
                    "verified": True,
                },
                {
                    "kind": "unit_anchor",
                    "regex": r"Line\s+(?P<line>[78])",
                    "unit_role": "folio_line",
                    "verified": True,
                },
            ],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_folio_line_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 2
    assert result.issues == []


def test_preflight_contextual_strategy_does_not_count_units_without_context(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "contextual-lines-without-context.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "Line 7 The record begins.\n"
                        "Line 8 The record continues."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "schema_type": "folio_line",
            "canonical_units": True,
            "strategy": "contextual_unit",
            "verified": True,
            "anchors": [
                {
                    "kind": "context_anchor",
                    "regex": r"Folio\s+(?P<folio>\d+)",
                    "unit_role": "folio",
                    "verified": True,
                },
                {
                    "kind": "unit_anchor",
                    "regex": r"Line\s+(?P<line>[78])",
                    "unit_role": "folio_line",
                    "verified": True,
                },
            ],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_folio_line_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "failed"
    assert result.reference_unit_count == 0
    assert [issue.code for issue in result.issues] == ["reference_unit_missing"]


def test_preflight_ignores_unverified_anchor_inside_verified_contract(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "unverified-inline-anchor.pdf"
    _install_fake_fitz(
        monkeypatch,
        {
            pdf_path: [
                [
                    _text_block(
                        "[1:1] \u0627\u0644\u062d\u0645\u062f English.\n"
                        "1:8 Cross reference should not start a unit."
                    )
                ],
            ]
        },
    )
    contract = {
        "reference_contract": {
            "schema_type": "chapter_verse",
            "canonical_units": True,
            "strategy": "single_anchor",
            "verified": True,
            "anchors": [
                {
                    "kind": "primary_anchor",
                    "regex": r"\[(?P<chapter>\d+):(?P<verse>\d+)\]",
                    "unit_role": "verse",
                    "verified": True,
                },
                {
                    "kind": "inline_references",
                    "regex": r"(?P<chapter>\d+):(?P<verse>\d+)",
                    "policy": "cross_reference_only",
                    "verified": False,
                },
            ],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        },
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_verse_content",
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="full_validation")

    assert result.status == "passed"
    assert result.reference_unit_count == 1
    assert result.issues == []


def _verified_reference_contract(values: dict[str, object]) -> dict[str, object]:
    contract = dict(values)
    contract["reference_contract"] = {
        "primary_anchor_regex": r"\[(?P<chapter>\d{1,4}):(?P<verse>\d{1,4})\]",
        "inline_reference_regex": r"(?P<chapter>\d{1,4})\s*:\s*(?P<verse>\d{1,4})",
        "canonical_units": True,
        "schema_type": "chapter_verse",
        "verified": True,
    }
    return contract


def _install_fake_fitz(monkeypatch, documents: dict[Path, list[list[tuple[object, ...]]]]) -> None:
    normalized = {path.resolve(): pages for path, pages in documents.items()}

    def fake_open(path):
        return _FakeDocument(normalized[Path(path).resolve()])

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=fake_open))


def _text_block(
    text: str,
    *,
    x: float = 72,
    y: float = 72,
) -> tuple[float, float, float, float, str]:
    return (x, y, x + 100, y + 12, text)


class _FakeDocument:
    def __init__(self, pages: list[list[tuple[object, ...]]]) -> None:
        self._pages = [_FakePage(blocks) for blocks in pages]
        self.page_count = len(self._pages)

    def __enter__(self) -> "_FakeDocument":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __getitem__(self, index: int) -> "_FakePage":
        return self._pages[index]


class _FakePage:
    def __init__(self, blocks: list[tuple[object, ...]]) -> None:
        self._blocks = blocks

    def get_text(self, mode: str):
        assert mode == "blocks"
        return self._blocks

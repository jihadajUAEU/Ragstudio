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
    contract = {
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
        }
    }

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
    contract = {
        "vision_analysis": {
            "sample_pages": [2],
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    }

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
    contract = {
        "vision_analysis": {
            "observed_unit_pattern": "reference_units_with_parallel_arabic_and_english",
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "failed"
    assert result.issues[0].code == "reference_unit_missing"


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
    contract = {
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "expected_scripts": ["arabic", "latin"],
            "min_reference_script_pass_ratio": 0.5,
        },
    }

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
    contract = {
        "vision_analysis": {
            "sample_pages": [1],
            "expected_scripts": ["arabic", "latin"],
        },
        "preprocessing": {
            "strict_pdf_text_preflight": True,
            "sample_pages": [2],
        },
    }

    result = PdfPreflightService().inspect(pdf_path, contract, mode="sample")

    assert result.status == "passed"
    assert result.inspected_pages == 1
    assert result.missing_arabic_unit_count == 0


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

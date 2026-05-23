# PDF OCR Preflight Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an upload/index preprocessing gate that detects broken PDF text layers, produces a clean OCR PDF when the vision-derived document contract requires it, and rejects the document when cleanup cannot produce contract-valid text for parsing.
**Architecture:** Preserve the original upload as immutable evidence. Reuse the existing pre-upload vision model analysis as the single source for the document contract and cleanup policy. After upload, run deterministic PDF text-layer preflight before MinerU, optionally run OCRmyPDF with Arabic and English language data, validate the cleaned output against the vision-derived contract, then pass only a contract-valid artifact into parsing. Failed cleanup must fail the indexing job and prevent chunk materialization.
**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async ORM, PyMuPDF/pdf text extraction, Docker-executed OCRmyPDF with Tesseract `ara+eng`, pytest, React/TanStack Query, Vitest.

---

## File Structure

```text
backend/src/ragstudio/services/pdf_preflight_service.py
backend/src/ragstudio/services/pdf_ocr_cleanup_service.py
backend/src/ragstudio/services/document_service.py
backend/src/ragstudio/services/document_contract.py
backend/src/ragstudio/config.py
backend/src/ragstudio/schemas/documents.py
backend/src/ragstudio/schemas/parsing.py
backend/tests/test_pdf_preflight_service.py
backend/tests/test_pdf_ocr_cleanup_service.py
backend/tests/test_documents.py
docker/ocrmypdf/Dockerfile
docs/pdf-preflight-cleanup.md
frontend/src/features/documents/documents-page.tsx
frontend/tests/documents-page.test.tsx
```

## Contract

For `quran_arabic_english.pdf`, the contract is not hard-coded from the filename or document type. It is produced by the existing pre-upload vision model analysis of sample pages. That vision analysis observes that reference-bearing Quran units visually contain Arabic script and Latin/English translation evidence. The current uploaded PDF has a bad selectable text layer/read order: Surah 1 selection reaches `[1:6]` and mixes Arabic text into the wrong logical unit. That means the visual page may look correct, but parser text evidence is not reliable enough to index.

The pipeline must behave like this:

- If the original PDF passes contract preflight, index the original artifact.
- If the original PDF fails and cleanup is enabled, run OCR cleanup and validate the cleaned artifact.
- If the cleaned artifact passes, index the cleaned artifact and keep lineage to the original.
- If cleanup is unavailable, times out, lacks language data, or still fails contract validation, reject the indexing job with no chunks materialized.
- Never silently fall back to the broken original for strict reference/script contracts.

The vision-derived contract is the authority for expected scripts, reference unit shape, and reject policy. Static domain defaults may provide fallback hints, but they must not override the vision contract.

## Combined Pre-Upload Vision And Cleanup Policy

Do not add a second vision analysis pass inside indexing. Reuse the existing pre-upload vision analysis and extend its output so it produces both:

1. The document contract.
2. The preprocessing policy.

The combined flow is:

```text
pre-upload vision sample
  -> document contract
  -> cleanup recommendation
  -> sampled cleanup trial when needed
  -> upload accepted as parse-ready / pending-cleanup / rejected
  -> post-upload text-layer preflight
  -> OCR cleanup only if needed
  -> contract validation
  -> MinerU parse
```

Vision output should include:

```json
{
  "document_contract": {
    "expected_scripts": ["arabic", "latin"],
    "unit_pattern": "reference_units_with_parallel_arabic_and_english",
    "reference_pattern": "[surah:ayah]"
  },
  "preprocessing_policy": {
    "cleanup_recommended": true,
    "cleanup_reason": "Visual units contain Arabic and English; PDF text layer should preserve both scripts per reference unit.",
    "reject_if_cleanup_fails": true,
    "min_reference_script_pass_ratio": 0.98
  }
}
```

Responsibility split:

- Vision decides the expected document shape.
- Deterministic preflight decides whether the uploaded PDF text layer is usable.
- Sampled cleanup trial decides whether full OCR is worth attempting.
- OCR cleanup attempts to repair the parser-facing artifact.
- Deterministic validation decides final accept/reject.

## Sampled Cleanup Trial

Use the same pages already selected for pre-upload vision analysis to run a small cleanup trial before committing to full-document OCR.

The sampled trial flow is:

```text
sample pages -> vision contract
sample pages -> text-layer preflight
if sampled text layer fails:
  sample pages -> OCR cleanup trial
  cleaned sample pages -> contract validation
if cleaned sample passes:
  accept upload as pending full cleanup
if cleaned sample fails:
  reject early or report cannot-clean
```

This trial is not final proof. It is a go/no-go signal for the expensive full-document cleanup stage.

Rules:

- If sampled text-layer preflight passes, skip OCR cleanup.
- If sampled text-layer preflight fails and sampled cleanup succeeds, run full PDF OCR cleanup after upload.
- If sampled cleanup fails because OCR tooling or required languages are missing, reject early with `pdf_cleanup_unavailable` or `pdf_cleanup_language_missing`.
- If sampled cleanup runs but cleaned sample still fails the vision-derived contract, reject early with `pdf_sample_cleanup_contract_failed`.
- If sampled cleanup passes, final acceptance still requires full PDF cleanup and full cleaned-PDF validation before MinerU parsing.

For `quran_arabic_english.pdf`, sampled pages should show Arabic visually, original extracted text should fail unit/script checks, and sampled OCR should prove whether Arabic OCR can recover usable text before the full file is processed.

## Large Document Strategy

For large PDFs, such as a 1000-page document, the pipeline must not wait until after full OCR and full parsing to discover that the file is unusable. Use staged validation:

1. Reuse the pre-upload vision analysis on representative pages:
   - first pages
   - middle pages
   - last pages
   - pages with dense references, tables, or mixed scripts when detected
   - random pages across the document

2. Build the document contract and preprocessing policy from that vision sample:
   - expected scripts
   - reference pattern
   - unit shape
   - reading order expectation
   - cleanup recommendation
   - rejection thresholds

3. Run cheap text-layer preflight on the same sampled pages and on globally cheap signals:
   - page count
   - extracted text character count
   - script presence per sampled page
   - reference order on sampled pages
   - empty-text page ratio

4. If sampled text-layer preflight fails, run sampled OCR cleanup on those same pages.

5. Decide whether full cleanup is needed before running full OCR:
   - If sampled text satisfies the vision contract, skip OCR.
   - If vision sees required content that extracted text is missing or scrambling, and sampled cleanup passes, mark `cleanup_required = true`.
   - If sampled cleanup fails, reject early before full OCR.
   - If the document is clearly unrecoverable before OCR, reject early.

6. If cleanup is required, accept the upload as `pending_cleanup` and OCR the full PDF as a background indexing stage.

7. Validate the cleaned PDF before MinerU parsing:
   - all pages for cheap checks
   - all detectable reference units for expected scripts when feasible
   - every page that failed pre-cleanup sampling
   - representative sampled pages for layout/order checks
   - low-confidence or empty-text pages

8. Reject before parsing if the cleaned PDF fails the vision-derived contract.

Example large-document thresholds:

```json
{
  "min_reference_script_pass_ratio": 0.98,
  "max_empty_text_pages_ratio": 0.01,
  "max_failed_sample_pages": 0,
  "reject_if_cleanup_fails": true
}
```

The intended flow is:

```text
pre-upload vision contract and cleanup policy -> sampled text preflight -> sampled cleanup trial if needed -> full OCR only if sample passes -> cleaned PDF validation -> MinerU parse/index
```

Do not run:

```text
full OCR -> full parse -> thousands of warnings -> late rejection
```

## Tasks

- [ ] Add PDF preflight result models.

Create `backend/src/ragstudio/services/pdf_preflight_service.py` with dataclasses:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PdfPreflightIssue:
    code: str
    message: str
    page: int | None = None
    reference: str | None = None


@dataclass(frozen=True)
class PdfPreflightResult:
    status: str
    inspected_pages: int
    extracted_text_chars: int
    arabic_unit_count: int
    missing_arabic_unit_count: int
    issues: list[PdfPreflightIssue] = field(default_factory=list)
```

Implement `PdfPreflightService.inspect(path, contract)` using PyMuPDF to extract text blocks with coordinates. Detect Arabic with `[\u0600-\u06ff]`, detect references with `\[(\d+):(\d+)\]`, and flag reference units missing expected scripts.

Add support for `mode="sample"` and `mode="full_validation"`:

- `sample` inspects only contract-selected pages plus global cheap metrics.
- `full_validation` runs after OCR cleanup and validates all cheap checks plus all feasible reference/script checks before parsing.

- [ ] Persist and validate strict script expectations from the pre-upload vision-derived document contract.

Update `backend/src/ragstudio/services/document_contract.py` so the existing pre-upload vision model analysis can populate:

```python
"vision_analysis": {
    "sample_pages": [1, 2, 3],
    "observed_unit_pattern": "reference_units_with_parallel_arabic_and_english",
    "expected_scripts": ["arabic", "latin"]
},
"preprocessing": {
    "strict_pdf_text_preflight": true,
    "expected_scripts_source": "vision_analysis",
    "expected_scripts": ["arabic", "latin"],
    "cleanup_recommended": true,
    "cleanup_required_reason": "Visual reference units contain Arabic and English, but extracted text misses or scrambles Arabic units.",
    "reject_if_cleanup_fails": true,
    "min_reference_script_pass_ratio": 0.98
}
```

Keep this inside the existing index contract JSON so the evidence page can show the exact vision-derived reason the upload was accepted or rejected.

- [ ] Add OCR cleanup service.

Create `backend/src/ragstudio/services/pdf_ocr_cleanup_service.py` with:

```python
class PdfOcrCleanupError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PdfOcrCleanupService:
    async def clean(self, source_path: Path, output_path: Path) -> Path:
        ...
```

Run OCRmyPDF through Docker with a configured image and these arguments:

```text
--force-ocr -l ara+eng --deskew --clean --rotate-pages --optimize 1
```

Map tool failures to stable codes: `pdf_cleanup_unavailable`, `pdf_cleanup_timeout`, `pdf_cleanup_language_missing`, and `pdf_cleanup_failed`.

Add `clean_sample_pages(source_path, page_numbers, output_path)` so the upload flow can trial OCR only on the pages already used by vision analysis. The implementation may create a temporary sampled PDF, run OCRmyPDF on that sampled PDF, then validate the cleaned sample against the same contract.

- [ ] Add the OCRmyPDF image with Arabic language data.

Create `docker/ocrmypdf/Dockerfile`:

```dockerfile
FROM jbarlow83/ocrmypdf:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr-ara tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
```

Verification command:

```powershell
docker build -t ragstudio-ocrmypdf:ara-eng docker/ocrmypdf
docker run --rm ragstudio-ocrmypdf:ara-eng tesseract --list-langs
```

Expected output must include `ara` and `eng`.

- [ ] Add backend settings.

Modify `backend/src/ragstudio/config.py`:

```python
pdf_preflight_enabled: bool = True
pdf_ocr_cleanup_enabled: bool = True
pdf_ocr_docker_image: str = "ragstudio-ocrmypdf:ara-eng"
pdf_ocr_languages: str = "ara+eng"
pdf_ocr_timeout_seconds: int = 900
pdf_ocr_reject_on_failure: bool = True
pdf_ocr_min_reference_script_pass_ratio: float = 0.98
```

- [ ] Integrate preflight before MinerU indexing.

Modify `backend/src/ragstudio/services/document_service.py` in the upload/index path before MinerU parsing:

1. Load the pre-upload vision analysis and build the document index contract from that analysis.
2. Run `PdfPreflightService.inspect(original_artifact_path, contract, mode="sample")`.
3. If sampled preflight passes, continue with original artifact.
4. If sampled preflight fails and cleanup is allowed, run `PdfOcrCleanupService.clean_sample_pages(...)`.
5. Validate the cleaned sample against the vision-derived contract.
6. If sampled cleanup fails, reject early and do not run full OCR.
7. If sampled cleanup passes, write the full cleaned artifact under the document artifact directory.
8. Re-run preflight on the cleaned full artifact in `full_validation` mode.
9. If validation passes, send the cleaned path to parsing and store preprocessing lineage in the job result.
10. If validation fails, mark the job failed and do not call the parser.

The job result should include:

```json
{
  "preprocessing": {
    "status": "cleaned" ,
    "original_artifact_path": "...",
    "active_artifact_path": "...",
    "preflight_before": {"status": "failed"},
    "preflight_after": {"status": "passed"}
  }
}
```

For rejection:

```json
{
  "preprocessing": {
    "status": "rejected",
    "error_type": "pdf_cleanup_contract_failed",
    "message": "Cleaned PDF still fails expected Arabic script checks."
  }
}
```

- [ ] Add API/UI status surface.

Modify `backend/src/ragstudio/schemas/documents.py` and the document/job response path to expose preprocessing status from the latest indexing job.

Modify `frontend/src/features/documents/documents-page.tsx` to show a compact upload status:

- `PDF preflight passed`
- `OCR cleanup running`
- `Cleaned PDF indexed`
- `Rejected: PDF cleanup failed contract`

Do not show raw local filesystem paths in the UI.

- [ ] Add backend tests.

Create `backend/tests/test_pdf_preflight_service.py`:

```python
def test_preflight_fails_reference_unit_missing_arabic(tmp_path):
    pdf_path = make_pdf_with_text(tmp_path, "[1:4] It is You we worship and You we ask for help.")
    contract = {"preprocessing": {"strict_pdf_text_preflight": True, "expected_scripts": ["arabic", "latin"]}}

    result = PdfPreflightService().inspect(pdf_path, contract)

    assert result.status == "failed"
    assert result.missing_arabic_unit_count == 1
    assert result.issues[0].code == "reference_unit_missing_expected_script"
```

Create `backend/tests/test_pdf_ocr_cleanup_service.py`:

```python
async def test_cleanup_language_missing_maps_stable_error(fake_runner, tmp_path):
    fake_runner.stderr = "OCR engine does not have language data for: ara"
    service = PdfOcrCleanupService(runner=fake_runner)

    with pytest.raises(PdfOcrCleanupError) as exc:
        await service.clean(tmp_path / "in.pdf", tmp_path / "out.pdf")

    assert exc.value.code == "pdf_cleanup_language_missing"
```

Modify `backend/tests/test_documents.py` to assert a strict-contract PDF is rejected when both original and cleaned preflight fail, and that no chunks are written.

- [ ] Add frontend tests.

Modify `frontend/tests/documents-page.test.tsx`:

```tsx
it("shows rejected PDF cleanup status without local paths", async () => {
  render(<DocumentsPage />)

  expect(await screen.findByText(/Rejected: PDF cleanup failed contract/i)).toBeInTheDocument()
  expect(screen.queryByText(/C:\\Users\\/i)).not.toBeInTheDocument()
})
```

- [ ] Add operator documentation.

Create `docs/pdf-preflight-cleanup.md` covering:

- Why visual correctness is not enough for RAG indexing.
- How text-layer/read-order preflight works.
- How to build `ragstudio-ocrmypdf:ara-eng`.
- What rejection means.
- How to inspect preprocessing lineage in document/job evidence.

- [ ] Run verification.

Backend:

```powershell
pytest backend/tests/test_pdf_preflight_service.py backend/tests/test_pdf_ocr_cleanup_service.py backend/tests/test_documents.py
```

Frontend:

```powershell
cd frontend
npm test -- documents-page
npm run typecheck
```

Manual container check:

```powershell
docker build -t ragstudio-ocrmypdf:ara-eng ..\docker\ocrmypdf
docker run --rm ragstudio-ocrmypdf:ara-eng tesseract --list-langs
```

Manual document check:

```powershell
docker run --rm -v "C:\Users\jihad\Downloads:/data" ragstudio-ocrmypdf:ara-eng --force-ocr -l ara+eng --deskew --clean --rotate-pages --optimize 1 /data/quran_arabic_english.pdf /data/quran_arabic_english.cleaned_ocr.pdf
```

## Acceptance Criteria

- Uploading a PDF with a valid contract-compatible text layer indexes normally.
- Uploading `quran_arabic_english.pdf` triggers preflight failure before MinerU.
- Large PDFs use sampled vision/text preflight before deciding whether full OCR is necessary.
- Large PDFs run sampled cleanup on vision-selected pages before full OCR.
- The existing pre-upload vision analysis is reused; indexing does not perform a duplicate vision pass.
- OCR cleanup uses an image that includes Arabic and English Tesseract data.
- A cleaned PDF is parsed only after it passes the same contract preflight.
- If cleanup cannot run or cannot satisfy the contract, the job is rejected with a clear error type.
- Rejected PDFs do not create chunks, vector entries, graph projections, or misleading parse evidence.
- The UI shows the cleanup/rejection state without exposing local paths.
- Tests cover pass, cleanup success, cleanup unavailable, cleanup still invalid, and UI status display.

## Self-Review

This plan keeps the original PDF immutable, treats cleaned OCR as a derived artifact, and makes the contract the gate. The key implementation risk is the exact parser integration point for selecting the active artifact path; resolve that by reading the current document indexing flow before editing `document_service.py`.

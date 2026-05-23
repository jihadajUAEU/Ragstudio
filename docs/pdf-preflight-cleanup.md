# PDF Preflight Cleanup

Ragstudio must treat a PDF's parser-facing text as evidence, not as a visual
assumption. A page can look correct in a viewer while its selectable text layer
is empty, scrambled, out of reading order, or missing scripts that are visible on
the page. If that broken text reaches MinerU and indexing, retrieval can look
plausible while citing the wrong unit or omitting the evidence the user saw.

PDF preflight cleanup is the fail-closed path for that case. The original upload
stays immutable evidence. A cleaned OCR PDF is only a derived parser artifact,
and it is used only when it satisfies the same document contract that required
cleanup.

## Contract Source

The existing pre-upload vision analysis creates the contract. Indexing must not
run a second vision pass to invent a new policy. The vision sample observes what
the page visibly contains, such as Arabic script, Latin text, reference-bearing
units, tables, dense citations, or mixed-script layout. That output becomes both:

- `document_contract`: expected scripts, reference shape, unit pattern, and
  sampled pages.
- `preprocessing_policy`: whether cleanup is recommended, why it is required,
  the minimum validation threshold, and whether to reject if cleanup fails.

Static domain defaults may provide fallback hints, but they must not override the
vision-derived contract. If vision says reference units contain Arabic and
English, a PDF text layer that drops Arabic or mixes it into the wrong logical
unit is not parse-ready, even if the rendered page looks correct.

## Processing Flow

The intended flow is:

```text
pre-upload vision sample
  -> document contract and cleanup policy
  -> sampled text-layer preflight
  -> sampled OCR cleanup trial when needed
  -> upload accepted as parse-ready, pending-cleanup, or rejected
  -> post-upload full cleanup when required
  -> cleaned-PDF contract validation
  -> MinerU parse and indexing
```

Deterministic preflight checks the PDF text layer against the contract. Typical
checks include extracted character count, empty-text page ratio, expected script
presence, reference order, and whether each detected reference unit contains the
scripts that vision observed.

## Sampled Cleanup Trial

Large or mixed-script PDFs should not wait until full OCR and full parsing to
discover that the artifact is unusable. Use the same pages selected by the
pre-upload vision analysis for a small trial:

1. Run text-layer preflight on the sampled pages.
2. If sampled preflight passes, skip OCR cleanup.
3. If sampled preflight fails and cleanup is allowed, run OCRmyPDF on only the
   sampled pages.
4. Validate the cleaned sample against the same vision-derived contract.
5. Reject early if OCR tooling is unavailable, required language data is missing,
   or the cleaned sample still fails the contract.

The sampled trial is not final proof. It is a go/no-go signal before spending
time on full-document OCR.

## Full Cleanup Validation

When the sampled trial passes and the policy requires cleanup, run OCRmyPDF on
the full uploaded PDF. The cleaned artifact must pass full validation before it
is handed to MinerU. Validation should include cheap all-page checks, every page
that failed sampling, all feasible reference/script checks, and representative
layout/order checks.

Do not parse the original PDF as a fallback after cleanup was required. If the
cleaned artifact is invalid, the correct outcome is rejection with no chunks,
vector entries, graph projections, or misleading parse evidence.

## Rejection Behavior

Rejection means the document was not safe to index under its contract. Operators
should expect stable error types such as:

- `pdf_cleanup_unavailable`: OCR cleanup tooling could not run.
- `pdf_cleanup_timeout`: OCR cleanup exceeded the configured timeout.
- `pdf_cleanup_language_missing`: required Tesseract language data is missing.
- `pdf_sample_cleanup_contract_failed`: sampled OCR output still failed the
  vision-derived contract.
- `pdf_cleanup_contract_failed`: full cleaned PDF still failed validation.

Rejected jobs should surface the contract reason and cleanup status without raw
local filesystem paths. Public proof packets and UI evidence should show lineage
from original artifact to active parser artifact or rejection reason, with any
private paths redacted or replaced by artifact IDs.

## OCRmyPDF Image

Build the image from the repository root:

```powershell
docker build -t ragstudio-ocrmypdf:ara-eng docker/ocrmypdf
```

Verify that both Arabic and English language data are installed:

```powershell
docker run --rm ragstudio-ocrmypdf:ara-eng tesseract --list-langs
```

Expected output must include:

```text
ara
eng
```

Run a manual cleanup against a mounted work directory when needed:

```powershell
docker run --rm `
  -v "<host-pdf-directory>:/data" `
  ragstudio-ocrmypdf:ara-eng `
  --force-ocr -l ara+eng --deskew --clean --rotate-pages --optimize 1 `
  /data/<input>.pdf `
  /data/<output>.cleaned_ocr.pdf
```

Use placeholders or artifact IDs in notes and proof evidence. Do not publish
private local paths, private hostnames, provider endpoints, or unpublished model
hosts.

## Verification Commands

Backend verification for the planned services and integration:

```powershell
pytest backend/tests/test_pdf_preflight_service.py backend/tests/test_pdf_ocr_cleanup_service.py backend/tests/test_documents.py
```

Frontend verification for the planned upload status surface:

```powershell
cd frontend
npm test -- documents-page
npm run typecheck
```

Container verification:

```powershell
docker build -t ragstudio-ocrmypdf:ara-eng docker/ocrmypdf
docker run --rm ragstudio-ocrmypdf:ara-eng tesseract --list-langs
```

Operational evidence to inspect after an indexing attempt:

- The pre-upload vision contract and cleanup policy.
- Sampled text preflight status and issues.
- Sampled cleanup trial status, if cleanup was required.
- Full cleanup status and cleaned-PDF validation result.
- Final job result: `parse-ready`, `cleaned`, or `rejected`.
- Artifact lineage from original upload to active parser artifact, using public
  artifact identifiers rather than local paths.

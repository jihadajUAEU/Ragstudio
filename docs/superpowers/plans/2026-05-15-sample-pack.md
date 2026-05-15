# Sample Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public-safe synthetic sample pack under `examples/sample-pack/` with docs, metadata, evaluation prompts, expected artifacts, screenshot signoff, and repository contract tests.

**Architecture:** The pack is static and self-contained. Markdown documents are the canonical synthetic corpus, JSON files describe metadata/evaluations/expected artifacts, and one backend contract test validates structure, JSON parseability, use-case coverage, and redaction boundaries. Live app screenshots are captured into the pack only when the configured app URL is reachable and the screenshots pass signoff.

**Tech Stack:** Markdown, JSON, Python 3.12, pytest, existing proof validation via `scripts/proof.sh`.

---

## File Structure

- Create `examples/sample-pack/README.md`: reviewer-facing overview and workflow.
- Create `examples/sample-pack/RUNBOOK.md`: configurable live-app test path using `RAGSTUDIO_FRONTEND_URL`.
- Create `examples/sample-pack/sources/catalogue.md`: official source inspiration links and license cautions.
- Create 8 synthetic Markdown documents in `examples/sample-pack/documents/`.
- Create 8 metadata JSON files in `examples/sample-pack/metadata/`.
- Create `examples/sample-pack/evaluations/sample-pack-evaluation-set.json`: evaluation import payload.
- Create `examples/sample-pack/evaluations/expected-answers.md`: expected answer behavior.
- Create `examples/sample-pack/evaluations/should-not-answer.md`: refusal/insufficient-evidence cases.
- Create 4 expected artifact JSON files in `examples/sample-pack/expected-artifacts/`.
- Create `examples/sample-pack/screenshots/signoff.json`: fail-closed screenshot manifest.
- Create `backend/tests/test_sample_pack_contract.py`: static contract and redaction tests for the sample pack.

## Task 1: Add Sample-Pack Contract Tests

**Files:**
- Create: `backend/tests/test_sample_pack_contract.py`

- [ ] **Step 1: Write the failing contract test**

Create `backend/tests/test_sample_pack_contract.py` with:

```python
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = REPO_ROOT / "examples" / "sample-pack"

EXPECTED_DOCUMENTS = [
    "protocol-spec",
    "financial-filing",
    "regulatory-notice",
    "scientific-article",
    "technical-report",
    "public-domain-book",
    "legal-opinion",
    "ocr-stress",
]


def _read_json(relative_path: str) -> dict:
    return json.loads((SAMPLE_ROOT / relative_path).read_text(encoding="utf-8"))


def _sample_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in SAMPLE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".json"}
    )


def test_sample_pack_has_required_public_structure():
    assert (SAMPLE_ROOT / "README.md").exists()
    assert (SAMPLE_ROOT / "RUNBOOK.md").exists()
    assert (SAMPLE_ROOT / "sources" / "catalogue.md").exists()
    assert (SAMPLE_ROOT / "evaluations" / "sample-pack-evaluation-set.json").exists()
    assert (SAMPLE_ROOT / "screenshots" / "signoff.json").exists()

    for name in EXPECTED_DOCUMENTS:
        assert (SAMPLE_ROOT / "documents" / f"{name}.synthetic.md").exists()
        assert (SAMPLE_ROOT / "metadata" / f"{name}.metadata.json").exists()


def test_sample_pack_metadata_and_evaluations_cover_all_documents():
    evaluation_set = _read_json("evaluations/sample-pack-evaluation-set.json")
    assert evaluation_set["name"] == "Ragstudio Synthetic Sample Pack"
    assert evaluation_set["version"] == "2026-05-15"
    assert len(evaluation_set["items"]) >= 28

    covered_documents = {item["document_id"] for item in evaluation_set["items"]}
    assert covered_documents == set(EXPECTED_DOCUMENTS)
    assert any(item["expected_behavior"] == "should_not_answer" for item in evaluation_set["items"])
    assert any(item["query_type"] == "exact_reference" for item in evaluation_set["items"])
    assert any(item["query_type"] == "table_numeric" for item in evaluation_set["items"])
    assert any(item["query_type"] == "graph_citation" for item in evaluation_set["items"])
    assert any(item["query_type"] == "multilingual" for item in evaluation_set["items"])

    for name in EXPECTED_DOCUMENTS:
        metadata = _read_json(f"metadata/{name}.metadata.json")
        assert metadata["document_id"] == name
        assert metadata["synthetic"] is True
        assert metadata["public_safe"] is True
        assert metadata["domain"]
        assert metadata["source_inspiration"]
        assert metadata["quality_policy"]["allow_public_release"] is True


def test_expected_artifacts_cover_parser_chunks_retrieval_graph_and_reranker():
    parser_warnings = _read_json("expected-artifacts/parser-warnings.synthetic.json")
    chunks = _read_json("expected-artifacts/chunks.synthetic.json")
    retrieval = _read_json("expected-artifacts/retrieval-traces.synthetic.json")
    graph_reranker = _read_json("expected-artifacts/graph-reranker.synthetic.json")

    assert parser_warnings["pack_id"] == "ragstudio-sample-pack-v1"
    assert any(
        warning["warning_code"] == "reference_label_malformed"
        for warning in parser_warnings["warnings"]
    )
    assert any(
        warning["quality_action_policy"]["materialization"] == "blocked"
        for warning in parser_warnings["warnings"]
    )

    chunk_document_ids = {chunk["document_id"] for chunk in chunks["chunks"]}
    assert chunk_document_ids == set(EXPECTED_DOCUMENTS)
    assert any(chunk["quality_action_policy"]["vector_index"] == "blocked" for chunk in chunks["chunks"])

    assert any(trace["expected_behavior"] == "answer_with_evidence" for trace in retrieval["traces"])
    assert any(trace["expected_behavior"] == "should_not_answer" for trace in retrieval["traces"])
    assert any(stage["stage"] == "rerank" for trace in retrieval["traces"] for stage in trace["stages"])

    assert graph_reranker["graph_projection_state"]["status"] in {"ready", "synthetic_ready"}
    assert graph_reranker["reranker_traces"]
    assert graph_reranker["relationships"]


def test_sample_pack_runbook_uses_configurable_public_safe_url():
    runbook = (SAMPLE_ROOT / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "RAGSTUDIO_FRONTEND_URL" in runbook
    assert "http://127.0.0.1:5173" in runbook
    assert "10.127.33.19" not in runbook


def test_sample_pack_is_redaction_safe():
    text = _sample_text()
    forbidden_patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"github_pat_[A-Za-z0-9_]+",
        r"ghp_[A-Za-z0-9_]{20,}",
        r"xox[baprs]-[A-Za-z0-9-]+",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"(?i)bearer\s+[a-z0-9._=-]{12,}",
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}",
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}",
        r"192\.168\.\d{1,3}\.\d{1,3}",
        r"/Users/[^\s\"']+|/home/[^\s\"']+|C:\\Users\\",
        r"file://",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, text) is None, pattern

    assert "synthetic" in text.lower()
    assert "not copied" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_sample_pack_contract.py -q
```

Expected: FAIL because `examples/sample-pack/` does not exist yet.

- [ ] **Step 3: Commit the failing contract test**

Run:

```bash
git add backend/tests/test_sample_pack_contract.py
git commit -m "test: add sample pack contract"
```

Expected: commit succeeds.

## Task 2: Add Public-Facing Sample-Pack Docs

**Files:**
- Create: `examples/sample-pack/README.md`
- Create: `examples/sample-pack/RUNBOOK.md`
- Create: `examples/sample-pack/sources/catalogue.md`

- [ ] **Step 1: Create README**

Create `examples/sample-pack/README.md` with:

```markdown
# Ragstudio Synthetic Sample Pack

This sample pack gives reviewers a safe, repeatable way to see how Ragstudio exposes document-quality failures before they become answer evidence.

The documents are synthetic. They are inspired by public document types, but the text is not copied from the internet, customer files, private corpora, or provider outputs.

## What It Covers

- parser warnings and quality gates,
- chunk metadata and reference labels,
- exact-reference retrieval,
- table and numeric grounding,
- graph/citation relationships,
- reranker traces,
- multilingual text,
- should-not-answer prompts.

## Quick Path

1. Read `sources/catalogue.md` to understand the public document types that inspired the pack.
2. Upload files from `documents/` into Ragstudio.
3. Attach the matching file from `metadata/`.
4. Import `evaluations/sample-pack-evaluation-set.json` where evaluation import is available.
5. Follow `RUNBOOK.md` to inspect the app and capture screenshots.

## Safety Rule

Only screenshots marked safe in `screenshots/signoff.json` should be published. Pending screenshots are local verification evidence only.
```

- [ ] **Step 2: Create RUNBOOK**

Create `examples/sample-pack/RUNBOOK.md` with:

```markdown
# Sample Pack Runbook

Use this runbook to verify the sample pack in a live Ragstudio app.

```bash
export RAGSTUDIO_FRONTEND_URL="${RAGSTUDIO_FRONTEND_URL:-http://127.0.0.1:5173}"
```

Open `$RAGSTUDIO_FRONTEND_URL` in a browser.

## App Flow

1. Open Documents.
2. Upload the files in `documents/`.
3. Attach the matching JSON files in `metadata/` when upload or reindex metadata is available.
4. Wait for indexing. If a job fails or stays pending, capture that state as a limitation.
5. Open Pipeline and inspect parser warnings for `ocr-stress`.
6. Open Chunks and inspect metadata for at least one exact-reference chunk.
7. Open Query and run an exact-reference question from `evaluations/sample-pack-evaluation-set.json`.
8. Open Query and run a `should_not_answer` question from the same evaluation set.
9. Open Graph when graph projection is available and inspect citation relationships for `legal-opinion` or `scientific-article`.
10. Open Evaluation, Variants, Experiments, Comparison, and Optimizer when those flows are configured.
11. Capture screenshots only after checking they contain no private endpoint, private hostname, token, local path, or unpublished model/provider detail.
12. Update `screenshots/signoff.json` with the approval state for every screenshot.

## Screenshot Targets

- Documents page with uploaded sample documents.
- Pipeline or job warning view for the OCR stress document.
- Chunk inspector showing reference metadata and quality action policy.
- Query trace for an exact-reference answer.
- Query trace for a should-not-answer case.
- Graph page showing legal or scientific citation relationships when available.
- Evaluation or Comparison page showing sample-pack runs when available.

## Limitation Rule

If a surface is unavailable, broken, or not configured, record the limitation. Do not mark it as proof.
```

- [ ] **Step 3: Create source catalogue**

Create `examples/sample-pack/sources/catalogue.md` with:

```markdown
# Public Source Inspiration Catalogue

The sample pack is synthetic. These links explain the public document types that inspired the examples, but the shipped document text is not copied from these sources.

| Source class | Official reference | Why it matters for RAG quality |
| --- | --- | --- |
| IETF/RFC-style protocol documents | https://www.rfc-editor.org/rfc/rfc5378.html | Normative language, exact clauses, section references, and cross-references. |
| SEC/EDGAR-style filings | https://www.sec.gov/search-filings/edgar-search-assistance/how-do-i-use-edgar | Financial tables, periods, risk factors, and numeric grounding. |
| Federal Register-style notices | https://www.federalregister.gov/reader-aids/developer-resources/rest-api | Agency metadata, action labels, dates, and docket-like references. |
| PMC-style scientific articles | https://pmc.ncbi.nlm.nih.gov/tools/openftlist/ | Abstracts, methods, figure captions, citations, and evidence-bound answers. |
| NASA technical reports | https://ntrs.nasa.gov/ | Engineering units, acronyms, report metadata, and tabular evidence. |
| Project Gutenberg-style books | https://www.gutenberg.org/policy/terms_of_use.html | Long-form prose, chapters, notes, and public-domain reuse caution. |
| Wikisource-style books | https://wikisource.org/wiki/Wikisource%3ACopyright_policy | Public-domain texts, editions, translations, and source provenance. |
| CourtListener-style legal opinions | https://www.courtlistener.com/help/api/bulk-data/ | Dockets, holdings, citations, concurrences, and citation graph structure. |

## Publishability Note

Public availability does not automatically mean every excerpt is safe to redistribute in every context. V1 avoids this problem by using synthetic text only.
```

- [ ] **Step 4: Commit docs**

Run:

```bash
git add examples/sample-pack/README.md examples/sample-pack/RUNBOOK.md examples/sample-pack/sources/catalogue.md
git commit -m "docs: add sample pack guide"
```

Expected: commit succeeds.

## Task 3: Add Synthetic Documents And Metadata

**Files:**
- Create: `examples/sample-pack/documents/*.synthetic.md`
- Create: `examples/sample-pack/metadata/*.metadata.json`

- [ ] **Step 1: Create 8 synthetic documents**

Create the 8 Markdown files named in the spec. Each file must include:

```markdown
> Synthetic sample. Inspired by public document structure, not copied from any source.
```

Each file must also include at least three stable references such as `SP-1.1`, `FIN-2026-R1`, `REG-7`, `SCI-FIG-2`, `TR-4.2`, `BOOK-II-4`, `CASE-3`, or `OCR-A7`.

- [ ] **Step 2: Create 8 metadata JSON files**

Each metadata file must follow this shape:

```json
{
  "document_id": "protocol-spec",
  "title": "Synthetic Protocol Specification",
  "domain": "protocol_specification",
  "synthetic": true,
  "public_safe": true,
  "source_inspiration": ["ietf_rfc"],
  "language": "english",
  "citation_style": "section",
  "reference_pattern": "section_id",
  "expected_structure": "numbered_sections",
  "quality_policy": {
    "allow_public_release": true,
    "require_reference_labels": true,
    "require_evidence_for_answers": true,
    "unsupported_answer_action": "should_not_answer"
  }
}
```

Adjust `document_id`, `title`, `domain`, `source_inspiration`, `language`, `citation_style`, `reference_pattern`, and `expected_structure` for each document.

- [ ] **Step 3: Run contract test**

Run:

```bash
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_sample_pack_contract.py -q
```

Expected: still FAIL because evaluations and expected artifacts do not exist yet.

- [ ] **Step 4: Commit documents and metadata**

Run:

```bash
git add examples/sample-pack/documents examples/sample-pack/metadata
git commit -m "docs: add synthetic sample documents"
```

Expected: commit succeeds.

## Task 4: Add Evaluation Set And Expected Artifacts

**Files:**
- Create: `examples/sample-pack/evaluations/sample-pack-evaluation-set.json`
- Create: `examples/sample-pack/evaluations/expected-answers.md`
- Create: `examples/sample-pack/evaluations/should-not-answer.md`
- Create: `examples/sample-pack/expected-artifacts/parser-warnings.synthetic.json`
- Create: `examples/sample-pack/expected-artifacts/chunks.synthetic.json`
- Create: `examples/sample-pack/expected-artifacts/retrieval-traces.synthetic.json`
- Create: `examples/sample-pack/expected-artifacts/graph-reranker.synthetic.json`
- Create: `examples/sample-pack/screenshots/signoff.json`

- [ ] **Step 1: Create evaluation set**

Create a JSON object with this top-level shape:

```json
{
  "name": "Ragstudio Synthetic Sample Pack",
  "version": "2026-05-15",
  "description": "Synthetic evaluation prompts for the Ragstudio public sample pack.",
  "items": []
}
```

Add at least 4 items for each of the 8 document IDs. Include `query_type` values covering `exact_reference`, `table_numeric`, `graph_citation`, `multilingual`, and `unsupported`. Use `expected_behavior` values `answer_with_evidence` and `should_not_answer`.

- [ ] **Step 2: Create expected-answer docs**

Create `expected-answers.md` describing answerable queries and `should-not-answer.md` describing unsupported queries. Each unsupported case must say what evidence is missing.

- [ ] **Step 3: Create expected artifacts**

Create parser warnings, chunks, retrieval traces, graph/reranker files that match the test assertions from Task 1.

- [ ] **Step 4: Create screenshot signoff**

Create `screenshots/signoff.json` with:

```json
{
  "pack_id": "ragstudio-sample-pack-v1",
  "policy": "fail_closed",
  "screenshots": []
}
```

- [ ] **Step 5: Run contract test**

Run:

```bash
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_sample_pack_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit evaluation and expected artifacts**

Run:

```bash
git add examples/sample-pack/evaluations examples/sample-pack/expected-artifacts examples/sample-pack/screenshots/signoff.json
git commit -m "docs: add sample pack evaluation artifacts"
```

Expected: commit succeeds.

## Task 5: Validate Proof Packet And Capture Live Screenshot

**Files:**
- May create: `examples/sample-pack/screenshots/app-home.png`
- Modify: `examples/sample-pack/screenshots/signoff.json`

- [ ] **Step 1: Run proof validation**

Run:

```bash
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m ragstudio.proof_packet.cli --strict --json
```

Expected: JSON output with `"status": "passed"`.

- [ ] **Step 2: Check live app URL**

Run:

```bash
curl -I --max-time 10 http://10.127.33.19:5173
```

Expected: `HTTP/1.1 200 OK`. If unreachable, record screenshot capture as blocked in the final report and do not create fake screenshots.

- [ ] **Step 3: Capture screenshot if reachable**

Use Playwright against `http://10.127.33.19:5173` and write `examples/sample-pack/screenshots/app-home.png`. The committed docs must not mention this LAN URL.

- [ ] **Step 4: Update screenshot signoff if screenshot exists**

If `app-home.png` exists and contains no private details, update `screenshots/signoff.json`:

```json
{
  "pack_id": "ragstudio-sample-pack-v1",
  "policy": "fail_closed",
  "screenshots": [
    {
      "screenshot_path": "screenshots/app-home.png",
      "screen": "app-home",
      "safe_to_publish": true,
      "redaction_status": "passed",
      "reviewer": "Codex",
      "reviewed_at": "2026-05-15T00:00:00Z",
      "notes": "Captured from local verification run; no private endpoint visible in the screenshot."
    }
  ]
}
```

Use the actual UTC timestamp.

- [ ] **Step 5: Run full verification**

Run:

```bash
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m pytest backend/tests/test_sample_pack_contract.py backend/tests/test_proof_packet_validator.py::test_default_packet_validates_successfully -q
PYTHONPATH=backend/src /Users/meet/Documents/Ragstudio/.venv/bin/python -m ragstudio.proof_packet.cli --strict --json
```

Expected: tests PASS and proof output has `"status": "passed"`.

- [ ] **Step 6: Commit screenshot and final validation updates**

Run:

```bash
git add examples/sample-pack/screenshots
git commit -m "docs: add sample pack screenshot signoff"
```

Expected: commit succeeds only if there are screenshot/signoff changes. Skip commit if no screenshot was captured.

## Self-Review

- Spec coverage: The plan creates the sample pack structure, source catalogue, 8 synthetic documents, metadata, evaluations, expected artifacts, screenshot signoff, redaction checks, proof validation, and live app screenshot attempt.
- Placeholder scan: The plan has no unresolved markers or undefined later work.
- Type consistency: The test and JSON fields use consistent `document_id`, `query_type`, `expected_behavior`, `quality_action_policy`, and `pack_id` names.

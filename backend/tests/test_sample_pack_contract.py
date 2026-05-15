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

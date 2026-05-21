import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKET_ROOT = REPO_ROOT / "docs" / "benchmarks" / "ragstudio-oss-proof-v1"


def _read_json(relative_path: str) -> dict:
    return json.loads((PACKET_ROOT / relative_path).read_text(encoding="utf-8"))


def _walk_packet_files() -> list[Path]:
    return [path for path in PACKET_ROOT.rglob("*") if path.is_file()]


def test_manifest_resolves_all_public_packet_paths_and_hashes():
    manifest = _read_json("manifest.json")

    assert manifest["packet_id"] == "ragstudio-oss-proof-v1"
    assert manifest["schema_version"] == "2020-12"
    assert manifest["hash_status"] == "complete_for_current_artifacts"

    expected_paths = [
        *manifest["fixtures"],
        *manifest["artifacts"],
        *manifest["schemas"].values(),
        manifest["claims"]["registry"],
        manifest["claims"]["matrix"],
        manifest["screenshots"]["signoff"],
    ]

    missing = [path for path in expected_paths if not (PACKET_ROOT / path).exists()]
    assert missing == []

    for artifact_path, recorded in manifest["artifact_hashes"].items():
        artifact = PACKET_ROOT / artifact_path
        content = artifact.read_bytes()
        if artifact.suffix.lower() in {".json", ".md"}:
            content = content.replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        assert recorded["algorithm"] == "sha256"
        assert recorded["redaction_status"] == "passed"
        assert actual == recorded["value"]


def test_synthetic_fixtures_and_artifacts_cover_required_evidence_shapes():
    fixture_text = "\n".join(
        (PACKET_ROOT / path).read_text(encoding="utf-8")
        for path in [
            "fixtures/corpus.synthetic.json",
            "fixtures/parser-warnings.synthetic.json",
            "fixtures/retrieval-traces.synthetic.json",
            "fixtures/graph-reranker.synthetic.json",
        ]
    )
    artifact_text = "\n".join(
        (PACKET_ROOT / path).read_text(encoding="utf-8")
        for path in _read_json("manifest.json")["artifacts"]
    )

    assert "reference_unit_missing_expected_script" in fixture_text
    assert "quality_action_policy" in fixture_text
    assert "chunk_traces" in fixture_text
    assert "reranker_traces" in fixture_text
    assert "graph_projection_state" in fixture_text
    assert '"redaction_status": "passed"' in artifact_text


def test_schemas_are_json_schema_2020_12_and_strict():
    manifest = _read_json("manifest.json")

    for schema_path in manifest["schemas"].values():
        schema = _read_json(schema_path)
        schema_text = (PACKET_ROOT / schema_path).read_text(encoding="utf-8")

        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema.get("type") == "object"
        assert schema.get("required"), f"{schema_path} must declare required fields"
        assert '"additionalProperties": false' in schema_text


def test_claim_registry_keeps_proven_roadmap_and_disabled_claims_honest():
    manifest = _read_json("manifest.json")
    registry = _read_json(manifest["claims"]["registry"])

    counts = {"proven": 0, "roadmap": 0, "disabled": 0, "total": len(registry["claims"])}
    for claim in registry["claims"]:
        counts[claim["status"]] += 1

    assert counts == manifest["claim_counts"]

    for claim in registry["claims"]:
        if claim["status"] == "proven":
            assert claim["evidence"]
            assert claim["explanation"]
            for evidence in claim["evidence"]:
                assert evidence["public"] is True
                assert evidence["redaction_status"] == "passed"
                assert evidence["artifact_path"] in manifest["artifacts"]
        elif claim["status"] == "roadmap":
            assert claim["missing_evidence"]
            assert claim["planned_proof_path"]
        elif claim["status"] == "disabled":
            assert claim["disabled_reason"]
            assert claim["requirements_to_prove"]


def test_redaction_policy_and_screenshot_signoff_are_fail_closed():
    manifest = _read_json("manifest.json")
    signoff = _read_json(manifest["screenshots"]["signoff"])

    assert manifest["redaction_status"]["overall"] == "passed_human_approved"
    assert manifest["redaction_status"]["policy"] == "fail_closed"
    assert manifest["screenshots"] == {
        "signoff": "screenshots/signoff.json",
        "approved_count": 1,
        "pending_count": 0,
    }

    screenshots = signoff["screenshots"]
    assert len(screenshots) == 1
    assert screenshots[0]["safe_to_publish"] is True
    assert screenshots[0]["reviewer"]
    assert screenshots[0]["reviewed_at"]
    assert (PACKET_ROOT / screenshots[0]["screenshot_path"]).exists()

    packet_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in _walk_packet_files()
        if path.suffix.lower() in {".json", ".md"}
    )
    forbidden_patterns = [
        r"sk-[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"github_pat_[A-Za-z0-9_]+",
        r"ghp_[A-Za-z0-9_]{20,}",
        r"xox[baprs]-[A-Za-z0-9-]+",
        r"AIza[0-9A-Za-z_-]{20,}",
        r"(?i)bearer\s+[a-z0-9._=-]{12,}",
        r"localhost|127\.0\.0\.1|0\.0\.0\.0",
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}",
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}",
        r"192\.168\.\d{1,3}\.\d{1,3}",
        r"/Users/[^\s\"']+|/home/[^\s\"']+|C:\\Users\\",
        r"file://",
    ]

    for pattern in forbidden_patterns:
        assert re.search(pattern, packet_text) is None, pattern


def test_claims_and_compatibility_docs_explain_public_boundaries():
    claims_doc = (PACKET_ROOT / "docs" / "CLAIMS.md").read_text(encoding="utf-8")
    compatibility_doc = (PACKET_ROOT / "docs" / "COMPATIBILITY.md").read_text(
        encoding="utf-8"
    )
    limitations_doc = (PACKET_ROOT / "docs" / "LIMITATIONS.md").read_text(
        encoding="utf-8"
    )

    for status in ["proven", "roadmap", "disabled"]:
        assert status in claims_doc

    assert "JSON Schema 2020-12" in compatibility_doc
    assert "packet version" in compatibility_doc.lower()
    assert "Docker" in compatibility_doc
    assert "secrets" in compatibility_doc
    assert "2000+ page" in limitations_doc

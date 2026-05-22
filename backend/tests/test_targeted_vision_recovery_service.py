import json
from pathlib import Path

import pytest
from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.parser_normalization import VisionRecoveryConfig
from ragstudio.services.targeted_vision_recovery_service import TargetedVisionRecoveryService

pytestmark = pytest.mark.asyncio


class FakeVisionRecoveryClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    async def recover_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.text


async def test_targeted_vision_recovery_appends_text_and_suppresses_counted_warning(
    tmp_path: Path,
):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "ayah.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-image")
    content_list = tmp_path / "source_content_list.json"
    content_list.write_text(
        json.dumps(
            [
                {
                    "type": "image",
                    "img_path": "images/ayah.png",
                    "page_idx": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    warning = {
        "code": "reference_unit_missing_expected_script",
        "reference": "19:13",
        "expected_script": "arabic",
        "action": "quarantine_exact_arabic",
    }
    request = {
        "trigger": "missing_required_script",
        "scope": "reference_unit",
        "reference": "19:13",
        "missing_scripts": ["arabic"],
        "page_start": 1,
        "page_end": 1,
        "failure_action": "warn",
    }
    chunk = AdapterChunk(
        text="[19:13] And affection from Us and purity.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={
            "parser_metadata": {
                "artifact_extract_dir": str(tmp_path),
                "content_list_ref": "source_content_list.json",
            },
            "provenance": {
                "blocks": [{"source_block_ref": "source_content_list.json:block:0"}]
            },
            "extraction_quality": {"parser_warnings": [warning]},
            "quality_repair": {"targeted_vision_recovery_requests": [request]},
        },
    )
    client = FakeVisionRecoveryClient("وحنانا من لدنا وزكاة وكان تقيا")
    config = VisionRecoveryConfig(
        base_url="http://vision.test/v1",
        model="vision-ocr",
        enabled=True,
        target_block_types=frozenset({"image"}),
        triggers=frozenset({"missing_required_script"}),
        languages=frozenset({"arabic"}),
    )

    summary = await TargetedVisionRecoveryService(client).recover([chunk], config=config)

    assert summary["targeted_vision_recovery_attempted"] == 1
    assert summary["targeted_vision_recovery_succeeded"] == 1
    assert client.calls[0]["triggers"] == ["missing_required_script"]
    assert "وحنانا من لدنا" in chunk.text
    assert request["vision_recovery_status"] == "succeeded"
    assert request["recovery_source"] == "vision_model:vision-ocr"
    assert warning["vision_recovery_status"] == "succeeded"
    assert warning["suppressed_from_counts"] is True
    assert warning["quality_gate_action"] == "accepted_recovery"
    assert warning["vision_recovery_required"] is False
    assert chunk.metadata["provenance"]["blocks"][-1]["role"] == "targeted_vision_recovery"


async def test_targeted_vision_recovery_keeps_warning_counted_when_not_configured():
    warning = {
        "code": "reference_unit_missing_expected_script",
        "reference": "19:13",
        "expected_script": "arabic",
    }
    request = {
        "reference": "19:13",
        "missing_scripts": ["arabic"],
        "page_start": 1,
        "page_end": 1,
    }
    chunk = AdapterChunk(
        text="[19:13] English only.",
        source_location={"page_start": 1, "page_end": 1},
        metadata={
            "extraction_quality": {"parser_warnings": [warning]},
            "quality_repair": {"targeted_vision_recovery_requests": [request]},
        },
    )

    summary = await TargetedVisionRecoveryService().recover([chunk], config=None)

    assert summary["targeted_vision_recovery_not_configured"] == 1
    assert request["vision_recovery_status"] == "not_configured"
    assert warning["vision_recovery_status"] == "not_configured"
    assert warning.get("suppressed_from_counts") is None

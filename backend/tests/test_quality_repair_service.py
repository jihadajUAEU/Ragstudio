from ragstudio.services.adapter import AdapterChunk
from ragstudio.services.quality_repair_service import QualityRepairPass


def test_quality_repair_annotates_generic_required_script_warning_code():
    warning = {
        "code": "reference_unit_missing_required_script",
        "reference": "folio:12:line:7",
        "required_script": "latin",
    }
    record = {
        "reference": "folio:12:line:7",
        "missing_scripts": ["latin"],
        "source_location": {"page": 3},
    }
    chunk = AdapterChunk(
        text="Folio 12 Line 7",
        source_location={"page": 3},
        metadata={
            "quality": {"by_reference": [record]},
            "extraction_quality": {"parser_warnings": [warning]},
        },
    )

    summary = QualityRepairPass().apply_post_quality_repairs([chunk])

    assert summary == {"targeted_vision_recovery_requests": 1}
    assert warning["vision_recovery_required"] is True
    assert warning["repair"]["vision_recovery"]["reference"] == "folio:12:line:7"
    assert warning["repair"]["vision_recovery"]["missing_scripts"] == ["latin"]

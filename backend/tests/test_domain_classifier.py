from ragstudio.services.domain_classifier import DomainClassifier


def test_domain_classifier_maps_quran_tafseer_reference_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "quran_tafseer",
                "document_type": "tafseer",
                "content_role": "quran",
                "language": "mixed",
                "tags": ["quran", "tafseer", "arabic"],
            }
        ]
    )

    assert result.domain_profile_id == "reference_heavy"
    assert result.domain_family == "tafseer_reference"
    assert result.reference_heavy is True
    assert result.layout_hint == "reference"


def test_domain_classifier_maps_hadith_legal_and_policy_to_reference_heavy():
    classifier = DomainClassifier()

    for metadata in (
        {"domain": "hadith", "tags": ["hadith"]},
        {"domain": "legal", "document_type": "statute"},
        {"domain": "policy", "tags": ["policy"]},
    ):
        result = classifier.classify([metadata])

        assert result.domain_profile_id == "reference_heavy"
        assert result.layout_hint == "reference"
        assert result.reference_heavy is True


def test_domain_classifier_maps_layout_heavy_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "finance",
                "document_type": "report",
                "layout_types": ["table", "figure"],
                "tags": ["table", "annual_report"],
            }
        ]
    )

    assert result.domain_profile_id == "multimodal_layout"
    assert result.domain_family == "generic"
    assert result.layout_hint == "table"
    assert result.reference_heavy is False


def test_domain_classifier_maps_equation_layout_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "science",
                "document_type": "paper",
                "layout_types": ["equation"],
            }
        ]
    )

    assert result.domain_profile_id == "multimodal_layout"
    assert result.layout_hint == "equation"


def test_domain_classifier_defaults_to_general_for_plain_documents():
    result = DomainClassifier().classify([{"domain": "general", "tags": ["notes"]}])

    assert result.domain_profile_id == "general"
    assert result.domain_family == "generic"
    assert result.layout_hint is None
    assert result.reference_heavy is False


def test_domain_classifier_request_cache_reuses_document_classification():
    classifier = DomainClassifier()
    metadata = [
        {
            "document_id": "doc-1",
            "metadata_version": "v1",
            "domain": "hadith",
            "tags": ["hadith"],
        }
    ]

    first = classifier.classify(metadata)
    second = classifier.classify(metadata)

    assert first is second
    assert classifier.cache_stats()["hits"] == 1
    assert classifier.cache_stats()["size"] == 1


def test_domain_classifier_cache_key_includes_metadata_fingerprint():
    classifier = DomainClassifier()

    first = classifier.classify(
        [{"document_id": "doc-1", "metadata_fingerprint": "a", "domain": "hadith"}]
    )
    second = classifier.classify(
        [{"document_id": "doc-1", "metadata_fingerprint": "b", "domain": "hadith"}]
    )

    assert first is not second
    assert classifier.cache_stats()["hits"] == 0
    assert classifier.cache_stats()["size"] == 2

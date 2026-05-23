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
                "custom_json": {
                    "reference_schema": {
                        "type": "chapter_verse",
                        "fields": {"chapter": "chapter_number", "verse": "verse_number"},
                    }
                },
            }
        ]
    )

    assert result.domain_profile_id == "reference_heavy"
    assert result.domain_family == "reference_heavy"
    assert result.materialization_hint == "graph"
    assert result.reference_heavy is True
    assert result.layout_hint == "reference"


def test_domain_classifier_maps_hadith_contract_to_reference_family():
    result = DomainClassifier().classify(
        [
            {
                "domain": "hadith",
                "tags": ["hadith"],
                "custom_json": {
                    "reference_schema": {
                        "type": "book_hadith",
                        "fields": {"book": "book_number", "hadith": "hadith_number"},
                    }
                },
            }
        ]
    )

    assert result.domain_profile_id == "reference_heavy"
    assert result.domain_family == "reference_heavy"
    assert result.layout_hint == "reference"
    assert result.materialization_hint == "graph"
    assert result.reference_heavy is True


def test_domain_classifier_routes_custom_reference_contracts_as_reference_heavy():
    result = DomainClassifier().classify(
        [
            {
                "domain": "archive",
                "custom_json": {
                    "reference_schema": {
                        "type": "article_clause",
                        "fields": {
                            "article": "article_number",
                            "clause": "clause_number",
                        },
                    }
                },
            }
        ]
    )

    assert result.domain_profile_id == "reference_heavy"
    assert result.domain_family == "reference_heavy"
    assert result.layout_hint == "reference"
    assert result.materialization_hint == "graph"
    assert result.reference_heavy is True


def test_domain_classifier_maps_legal_and_policy_to_legal_reference():
    classifier = DomainClassifier()

    for metadata in (
        {"domain": "legal", "document_type": "statute"},
        {"domain": "policy", "tags": ["policy"]},
    ):
        result = classifier.classify([metadata])

        assert result.domain_profile_id == "legal_reference"
        assert result.domain_family == "legal_reference"
        assert result.layout_hint == "reference"
        assert result.materialization_hint == "graph"
        assert result.reference_heavy is True


def test_domain_classifier_maps_layout_heavy_documents():
    result = DomainClassifier().classify(
        [
            {
                "domain": "operations",
                "document_type": "report",
                "layout_types": ["table", "figure"],
                "tags": ["table", "annual_report"],
            }
        ]
    )

    assert result.domain_profile_id == "multimodal_layout"
    assert result.domain_family == "generic"
    assert result.layout_hint == "table"
    assert result.materialization_hint == "full"
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
    assert result.materialization_hint == "full"


def test_domain_classifier_defaults_to_general_for_plain_documents():
    result = DomainClassifier().classify([{"domain": "general", "tags": ["notes"]}])

    assert result.domain_profile_id == "general"
    assert result.domain_family == "generic"
    assert result.layout_hint is None
    assert result.materialization_hint == "vector"
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


def test_domain_classifier_maps_specialized_non_arabic_profiles():
    classifier = DomainClassifier()

    legal = classifier.classify([{"domain": "legal", "document_type": "contract"}])
    medical = classifier.classify([{"domain": "medical", "layout_types": ["figure"]}])
    financial = classifier.classify([{"domain": "finance", "layout_types": ["table"]}])
    code = classifier.classify([{"domain": "code", "tags": ["api"]}])

    assert legal.domain_family == "legal_reference"
    assert legal.domain_profile_id == "legal_reference"
    assert legal.materialization_hint == "graph"
    assert medical.domain_family == "medical_reference"
    assert medical.domain_profile_id == "medical_reference"
    assert medical.materialization_hint == "full"
    assert financial.domain_family == "financial_reference"
    assert financial.domain_profile_id == "financial_reference"
    assert financial.materialization_hint == "full"
    assert code.domain_family == "code_reference"
    assert code.domain_profile_id == "code_reference"
    assert code.materialization_hint == "vector"


def test_domain_classifier_does_not_infer_reference_family_without_contract():
    result = DomainClassifier().classify(
        [{"domain": "quran_tafseer", "tags": ["quran", "tafseer"]}]
    )

    assert result.domain_family == "generic"
    assert result.domain_profile_id == "general"
    assert result.materialization_hint == "vector"

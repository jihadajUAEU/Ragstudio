from ragstudio.services.static_policy_catalog import (
    POLICY_CATALOG_VERSION,
    policy_item,
    policy_items_by_kind,
)


def test_policy_catalog_classifies_remaining_hardcoded_items() -> None:
    assert POLICY_CATALOG_VERSION == "2026-05-24"

    expected_ids = {
        "domain_profile_defaults",
        "chunk_profile_word_targets",
        "block_type_vocabulary",
        "query_hypothesis_protocol_vocabulary",
        "api_pagination_bounds",
        "provider_manifest_vocabulary",
        "pdf_preflight_ratio_policy",
        "proof_packet_protocol_constants",
        "proof_packet_error_codes",
        "retrieval_candidate_expansion",
    }

    assert expected_ids.issubset({item.policy_id for item in policy_items_by_kind()})


def test_policy_catalog_distinguishes_protocol_from_tunable_policy() -> None:
    assert policy_item("proof_packet_protocol_constants").kind == "protocol_constant"
    assert policy_item("proof_packet_error_codes").kind == "protocol_constant"
    assert policy_item("chunk_profile_word_targets").kind == "tunable_policy"
    assert policy_item("api_pagination_bounds").kind == "runtime_default"
    assert policy_item("query_hypothesis_protocol_vocabulary").kind == "protocol_constant"

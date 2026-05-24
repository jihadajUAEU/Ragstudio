from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PolicyKind = Literal[
    "runtime_default",
    "tunable_policy",
    "protocol_constant",
    "security_policy",
    "ui_fallback",
]

POLICY_CATALOG_VERSION = "2026-05-24"


@dataclass(frozen=True, slots=True)
class StaticPolicyItem:
    policy_id: str
    kind: PolicyKind
    owner: str
    source_paths: tuple[str, ...]
    note: str


STATIC_POLICY_ITEMS: tuple[StaticPolicyItem, ...] = (
    StaticPolicyItem(
        policy_id="domain_profile_defaults",
        kind="tunable_policy",
        owner="domain_profile_registry",
        source_paths=("backend/src/ragstudio/services/domain_profile_registry.py",),
        note=(
            "Built-in domain profiles are product defaults; changing them requires "
            "route-planner tests."
        ),
    ),
    StaticPolicyItem(
        policy_id="chunk_profile_word_targets",
        kind="tunable_policy",
        owner="chunk_splitter",
        source_paths=("backend/src/ragstudio/services/chunk_splitter.py",),
        note="Word targets and hard caps affect canonical evidence boundaries.",
    ),
    StaticPolicyItem(
        policy_id="block_type_vocabulary",
        kind="protocol_constant",
        owner="block_types",
        source_paths=("backend/src/ragstudio/services/block_types.py",),
        note="Parser block categories define cross-service vocabulary.",
    ),
    StaticPolicyItem(
        policy_id="query_hypothesis_protocol_vocabulary",
        kind="protocol_constant",
        owner="query_hypothesis_service",
        source_paths=("backend/src/ragstudio/services/query_hypothesis_service.py",),
        note=(
            "Allowed intents, scripts, term types, domain hints, and answer shapes "
            "are parser protocol."
        ),
    ),
    StaticPolicyItem(
        policy_id="api_pagination_bounds",
        kind="runtime_default",
        owner="api_routes",
        source_paths=("backend/src/ragstudio/api/routes/", "backend/src/ragstudio/schemas/"),
        note="List defaults and max page sizes are API behavior, not retrieval scoring.",
    ),
    StaticPolicyItem(
        policy_id="provider_manifest_vocabulary",
        kind="protocol_constant",
        owner="provider_manifest_service",
        source_paths=("backend/src/ragstudio/services/provider_manifest_service.py",),
        note="Manifest sections and capabilities are external provider contract vocabulary.",
    ),
    StaticPolicyItem(
        policy_id="pdf_preflight_ratio_policy",
        kind="tunable_policy",
        owner="pdf_preflight_service",
        source_paths=("backend/src/ragstudio/services/pdf_preflight_service.py",),
        note="Reference-script pass ratios gate parser preflight behavior.",
    ),
    StaticPolicyItem(
        policy_id="proof_packet_protocol_constants",
        kind="protocol_constant",
        owner="proof_packet_validator",
        source_paths=("backend/src/ragstudio/proof_packet/validator.py",),
        note="Packet id, packet root, validator version, and commit length define proof protocol.",
    ),
    StaticPolicyItem(
        policy_id="proof_packet_error_codes",
        kind="protocol_constant",
        owner="proof_packet_errors",
        source_paths=("backend/src/ragstudio/proof_packet/errors.py",),
        note="Error codes and recovery guidance are stable validator output contract.",
    ),
    StaticPolicyItem(
        policy_id="retrieval_candidate_expansion",
        kind="tunable_policy",
        owner="retrieval_evidence",
        source_paths=(
            "backend/src/ragstudio/services/retrieval_evidence.py",
            "backend/src/ragstudio/services/retrieval_orchestrator.py",
        ),
        note=(
            "Expansion factors, minimum candidate windows, and seed caps affect "
            "recall and latency."
        ),
    ),
)


def policy_items_by_kind(kind: PolicyKind | None = None) -> tuple[StaticPolicyItem, ...]:
    if kind is None:
        return STATIC_POLICY_ITEMS
    return tuple(item for item in STATIC_POLICY_ITEMS if item.kind == kind)


def policy_item(policy_id: str) -> StaticPolicyItem:
    for item in STATIC_POLICY_ITEMS:
        if item.policy_id == policy_id:
            return item
    raise KeyError(f"Unknown static policy item: {policy_id}")

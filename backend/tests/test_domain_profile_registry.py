import pytest
from ragstudio.services.domain_profile_registry import (
    DomainProfile,
    DomainProfileRegistry,
)


def test_registry_returns_deterministic_default_profile():
    registry = DomainProfileRegistry()

    assert registry.get(None).id == "general"
    assert [profile.id for profile in registry.list_profiles()] == [
        "general",
        "multimodal_layout",
        "reference_heavy",
    ]


def test_registry_resolves_explicit_domain_before_hints():
    registry = DomainProfileRegistry()

    profile = registry.resolve(domain_id="reference_heavy", layout_hint="table")

    assert profile.id == "reference_heavy"
    assert profile.chunking_strategy == "reference_anchored"


def test_registry_can_be_configured_without_external_dependencies():
    registry = DomainProfileRegistry(
        profiles=(
            DomainProfile(
                id="legal",
                label="Legal",
                chunking_strategy="citation_anchored",
                retrieval_priority=("postgres_canonical", "lexical_reference"),
                supported_layouts=("reference",),
                materialization_hints=("canonical_only",),
            ),
        )
    )

    assert registry.get("legal").reference_patterns == ()
    with pytest.raises(KeyError, match="Unknown domain profile"):
        registry.get("general")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LayoutHint = Literal["plain_text", "table", "figure", "equation", "reference", "mixed"]
MaterializationHint = Literal["canonical_only", "vector", "graph", "runtime", "full"]


@dataclass(frozen=True, slots=True)
class DomainProfile:
    id: str
    label: str
    chunking_strategy: str
    retrieval_priority: tuple[str, ...]
    supported_layouts: tuple[LayoutHint, ...] = ("plain_text", "mixed")
    materialization_hints: tuple[MaterializationHint, ...] = ("canonical_only", "vector")
    reference_patterns: tuple[str, ...] = ()
    default_top_k: int = 8
    preserve_parallel_text: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def supports_layout(self, layout: LayoutHint | str | None) -> bool:
        if layout is None:
            return True
        return layout in self.supported_layouts or "mixed" in self.supported_layouts

    def supports_materialization(self, hint: MaterializationHint | str | None) -> bool:
        if hint is None:
            return True
        return hint in self.materialization_hints or "full" in self.materialization_hints


class DomainProfileRegistry:
    def __init__(self, profiles: tuple[DomainProfile, ...] | None = None) -> None:
        configured_profiles = profiles or DEFAULT_DOMAIN_PROFILES
        self._profiles = {profile.id: profile for profile in configured_profiles}

    def get(self, profile_id: str | None) -> DomainProfile:
        if not profile_id:
            return self.default_profile()
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"Unknown domain profile: {profile_id}") from exc

    def default_profile(self) -> DomainProfile:
        return self._profiles["general"]

    def list_profiles(self) -> tuple[DomainProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def resolve(
        self,
        *,
        domain_id: str | None = None,
        layout_hint: LayoutHint | str | None = None,
        materialization_hint: MaterializationHint | str | None = None,
    ) -> DomainProfile:
        if domain_id:
            return self.get(domain_id)
        if layout_hint is None and materialization_hint is None:
            return self.default_profile()
        candidates = [
            profile
            for profile in self.list_profiles()
            if profile.supports_layout(layout_hint)
            and profile.supports_materialization(materialization_hint)
        ]
        if not candidates:
            return self.default_profile()
        return sorted(candidates, key=lambda profile: (profile.id == "general", profile.id))[0]


DEFAULT_DOMAIN_PROFILES: tuple[DomainProfile, ...] = (
    DomainProfile(
        id="general",
        label="General Evidence",
        chunking_strategy="semantic_window",
        retrieval_priority=("postgres_canonical", "vector", "raganything_runtime"),
        supported_layouts=("plain_text", "table", "figure", "equation", "reference", "mixed"),
        materialization_hints=("canonical_only", "vector", "graph", "runtime", "full"),
    ),
    DomainProfile(
        id="reference_heavy",
        label="Reference Heavy",
        chunking_strategy="reference_anchored",
        retrieval_priority=("postgres_canonical", "lexical_reference", "graph", "vector"),
        supported_layouts=("plain_text", "reference", "mixed"),
        materialization_hints=("canonical_only", "vector", "graph", "full"),
        reference_patterns=("section", "article", "ayah", "hadith", "footnote"),
    ),
    DomainProfile(
        id="multimodal_layout",
        label="Multimodal Layout",
        chunking_strategy="layout_block",
        retrieval_priority=("postgres_canonical", "raganything_runtime", "vector", "graph"),
        supported_layouts=("table", "figure", "equation", "mixed"),
        materialization_hints=("canonical_only", "runtime", "vector", "full"),
    ),
)

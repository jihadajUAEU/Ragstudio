from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HybridScorePolicy:
    reference_exact: float = 100.0
    same_parent_reference_query: float = 60.0
    same_parent_with_unit_query: float = 5.0
    neighbor_match: float = 30.0
    term_coverage_multiplier: float = 10.0
    semantic_density_multiplier: float = 2.0
    metadata_boost_cap: float = 12.0
    metadata_title_term_cap: float = 10.0
    metadata_title_term_multiplier: float = 2.0
    layout_context_cap: float = 16.0
    layout_context_term_multiplier: float = 4.0
    arabic_exact: float = 40.0
    arabic_token: float = 24.0
    answer_bearing_count: float = 30.0
    guidance_request: float = 40.0
    exact_query_phrase: float = 8.0
    answer_bearing_phrase: float = 24.0

    @property
    def same_chapter_reference_query(self) -> float:
        return self.same_parent_reference_query

    @property
    def same_chapter_with_verse_query(self) -> float:
        return self.same_parent_with_unit_query


@dataclass(frozen=True, slots=True)
class FusionScorePolicy:
    rrf_k: int = 60
    direct_priority: dict[str, int] = field(
        default_factory=lambda: {
            "reference_hypothesis": 5,
            "reference_exact": 100,
            "arabic_exact": 90,
            "target_phrase": 80,
            "reference_tool": 70,
            "lexical_tool": 60,
            "pgvector": 20,
            "default": 10,
        }
    )
    lane_priority: dict[str, int] = field(
        default_factory=lambda: {
            "metadata": 40,
            "reference_exact": 40,
            "arabic_lexical": 35,
            "lexical": 35,
            "graph": 30,
            "pgvector": 20,
            "native": 10,
            "default": 0,
        }
    )
    direct_boost: dict[str, float] = field(
        default_factory=lambda: {
            "reference_exact": 100.0,
            "arabic_exact": 90.0,
            "target_phrase": 80.0,
        }
    )


@dataclass(frozen=True, slots=True)
class LayoutNeighborPolicy:
    vertical_proximity: float = 150.0
    base_score: float = 9.0
    base_boost_score: float = 1.5
    base_final_score: float = 10.5
    spatial_proximity_boost: float = 1.0
    layout_group_boost: float = 2.0
    reading_order_neighbor_boost: float = 1.0


@dataclass(frozen=True, slots=True)
class ContextWindowPolicy:
    base_score: float = 8.0
    boost_score: float = 1.0
    final_score: float = 9.0


@dataclass(frozen=True, slots=True)
class RoutePlanningPolicy:
    default_lane_timeout_ms: int = 8_000
    min_lane_timeout_ms: int = 250
    response_budget_fraction: float = 0.35

    def lane_timeout_ms(self, response_budget_ms: int | None) -> int:
        if response_budget_ms is None:
            return self.default_lane_timeout_ms
        budget = int(response_budget_ms * self.response_budget_fraction)
        return max(self.min_lane_timeout_ms, min(budget, self.default_lane_timeout_ms))


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    policy_version: str = "2026-05-24"
    hybrid: HybridScorePolicy = field(default_factory=HybridScorePolicy)
    fusion: FusionScorePolicy = field(default_factory=FusionScorePolicy)
    layout_neighbor: LayoutNeighborPolicy = field(default_factory=LayoutNeighborPolicy)
    context_window: ContextWindowPolicy = field(default_factory=ContextWindowPolicy)
    route_planning: RoutePlanningPolicy = field(default_factory=RoutePlanningPolicy)


DEFAULT_RETRIEVAL_POLICY = RetrievalPolicy()

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PipelineLayerId(StrEnum):
    PARSE = "parse"
    LAYOUT_NORMALIZATION = "layout_normalization"
    DOMAIN_RESOLVER = "domain_resolver"
    CANONICAL_EVIDENCE = "canonical_evidence"
    REPAIR_AND_QUALITY = "repair_and_quality"
    MATERIALIZATION_POLICY = "materialization_policy"
    RETRIEVAL_PLANNER = "retrieval_planner"
    FUSION_AND_RERANK = "fusion_and_rerank"
    CONTEXT_ASSEMBLY = "context_assembly"
    PROOF_TRACE = "proof_trace"


@dataclass(frozen=True, slots=True)
class PipelineLayer:
    id: PipelineLayerId
    position: int
    label: str
    contract: str


PIPELINE_LAYERS: tuple[PipelineLayer, ...] = (
    PipelineLayer(
        id=PipelineLayerId.PARSE,
        position=1,
        label="Parse",
        contract="Extract source blocks, parser warnings, and runtime source identifiers.",
    ),
    PipelineLayer(
        id=PipelineLayerId.LAYOUT_NORMALIZATION,
        position=2,
        label="Layout Normalization",
        contract="Normalize pages, blocks, reading order, and layout-derived provenance.",
    ),
    PipelineLayer(
        id=PipelineLayerId.DOMAIN_RESOLVER,
        position=3,
        label="Domain Resolver",
        contract="Resolve domain profile hints for chunking, references, and retrieval.",
    ),
    PipelineLayer(
        id=PipelineLayerId.CANONICAL_EVIDENCE,
        position=4,
        label="Canonical Evidence",
        contract="Create canonical evidence units with stable references and provenance.",
    ),
    PipelineLayer(
        id=PipelineLayerId.REPAIR_AND_QUALITY,
        position=5,
        label="Repair And Quality",
        contract="Apply repairs, parser warnings, and quality action policy.",
    ),
    PipelineLayer(
        id=PipelineLayerId.MATERIALIZATION_POLICY,
        position=6,
        label="Materialization Policy",
        contract="Decide which evidence can persist, index, and project into graph stores.",
    ),
    PipelineLayer(
        id=PipelineLayerId.RETRIEVAL_PLANNER,
        position=7,
        label="Retrieval Planner",
        contract="Select deterministic retrieval routes from domain, layout, and policy hints.",
    ),
    PipelineLayer(
        id=PipelineLayerId.FUSION_AND_RERANK,
        position=8,
        label="Fusion And Rerank",
        contract="Fuse lexical, vector, graph, and runtime candidates before reranking.",
    ),
    PipelineLayer(
        id=PipelineLayerId.CONTEXT_ASSEMBLY,
        position=9,
        label="Context Assembly",
        contract="Assemble answer context from canonical evidence units.",
    ),
    PipelineLayer(
        id=PipelineLayerId.PROOF_TRACE,
        position=10,
        label="Proof Trace",
        contract="Link claims to route decisions, source commits, artifacts, and limitations.",
    ),
)


def pipeline_layer_ids() -> tuple[PipelineLayerId, ...]:
    return tuple(layer.id for layer in PIPELINE_LAYERS)


def get_pipeline_layer(layer_id: PipelineLayerId | str) -> PipelineLayer:
    normalized = PipelineLayerId(layer_id)
    for layer in PIPELINE_LAYERS:
        if layer.id == normalized:
            return layer
    raise ValueError(f"Unknown pipeline layer: {layer_id}")


def assert_pipeline_contract_complete() -> None:
    expected_positions = tuple(range(1, len(PIPELINE_LAYERS) + 1))
    observed_positions = tuple(layer.position for layer in PIPELINE_LAYERS)
    if observed_positions != expected_positions:
        raise ValueError("Pipeline layers must be contiguous and ordered.")
    if len(set(pipeline_layer_ids())) != len(PIPELINE_LAYERS):
        raise ValueError("Pipeline layer ids must be unique.")

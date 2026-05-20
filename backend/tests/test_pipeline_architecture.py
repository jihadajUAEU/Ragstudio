import pytest
from ragstudio.services.pipeline_architecture import (
    PIPELINE_LAYERS,
    PipelineLayerId,
    assert_pipeline_contract_complete,
    get_pipeline_layer,
    pipeline_layer_ids,
)


def test_pipeline_layers_are_stable_and_ordered():
    assert_pipeline_contract_complete()

    assert pipeline_layer_ids() == (
        PipelineLayerId.PARSE,
        PipelineLayerId.LAYOUT_NORMALIZATION,
        PipelineLayerId.DOMAIN_RESOLVER,
        PipelineLayerId.CANONICAL_EVIDENCE,
        PipelineLayerId.REPAIR_AND_QUALITY,
        PipelineLayerId.MATERIALIZATION_POLICY,
        PipelineLayerId.RETRIEVAL_PLANNER,
        PipelineLayerId.FUSION_AND_RERANK,
        PipelineLayerId.CONTEXT_ASSEMBLY,
        PipelineLayerId.PROOF_TRACE,
    )
    assert [layer.position for layer in PIPELINE_LAYERS] == list(range(1, 11))


def test_get_pipeline_layer_accepts_strings_and_rejects_unknown_ids():
    layer = get_pipeline_layer("retrieval_planner")

    assert layer.id == PipelineLayerId.RETRIEVAL_PLANNER
    assert layer.label == "Retrieval Planner"

    with pytest.raises(ValueError):
        get_pipeline_layer("missing")

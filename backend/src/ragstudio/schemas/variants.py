from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel

VARIANT_PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "balanced": {"top_k": 5, "temperature": 0.2, "enable_rerank": True},
    "precise": {"top_k": 3, "temperature": 0.1, "enable_rerank": True},
    "broad": {"top_k": 12, "temperature": 0.3, "enable_rerank": True},
    "fast": {"top_k": 4, "temperature": 0.0, "enable_rerank": False},
}

VariantPreset = Literal["balanced", "precise", "broad", "fast"]


class VariantIn(StudioModel):
    name: str = Field(min_length=1)
    preset: VariantPreset
    parameters: dict[str, Any] = Field(default_factory=dict)


class VariantUpdate(StudioModel):
    name: str = Field(min_length=1)
    preset: VariantPreset
    parameters: dict[str, Any] = Field(default_factory=dict)


class VariantOut(VariantIn):
    id: str


class VariantPage(StudioModel):
    items: list[VariantOut]
    total: int

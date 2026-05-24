from typing import Any, Literal

from pydantic import Field

from ragstudio.schemas.common import StudioModel
from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY

VARIANT_PRESET_DEFAULTS: dict[str, dict[str, Any]] = (
    DEFAULT_OPERATIONAL_POLICY.variant_presets
)

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
    limit: int = 100
    offset: int = 0
    has_more: bool = False

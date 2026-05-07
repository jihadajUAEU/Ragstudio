from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StudioModel


class VariantIn(StudioModel):
    name: str = Field(min_length=1)
    preset: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class VariantOut(VariantIn):
    id: str


class VariantPage(StudioModel):
    items: list[VariantOut]
    total: int

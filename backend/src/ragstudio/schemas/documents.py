from typing import Any

from pydantic import Field

from ragstudio.schemas.common import StageStatus, StudioModel
from ragstudio.schemas.parsing import IndexDocumentIn


class DocumentOut(StudioModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    status: StageStatus
    latest_index_options: IndexDocumentIn | None = None
    index_contract: dict[str, Any] = Field(default_factory=dict)

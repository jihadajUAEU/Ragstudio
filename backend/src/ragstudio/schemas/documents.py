from ragstudio.schemas.common import StageStatus, StudioModel
from ragstudio.schemas.parsing import IndexDocumentIn


class DocumentOut(StudioModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    status: StageStatus
    latest_index_options: IndexDocumentIn | None = None

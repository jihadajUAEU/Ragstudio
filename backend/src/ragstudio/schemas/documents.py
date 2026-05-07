from ragstudio.schemas.common import StageStatus, StudioModel


class DocumentOut(StudioModel):
    id: str
    filename: str
    content_type: str
    sha256: str
    status: StageStatus

from ragstudio.schemas.common import StudioModel


class SettingsProfileIn(StudioModel):
    provider: str
    llm_model: str
    embedding_model: str
    storage_backend: str


class SettingsProfileOut(SettingsProfileIn):
    id: str

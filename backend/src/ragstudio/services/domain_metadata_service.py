from __future__ import annotations

import json
from pathlib import Path

from ragstudio.schemas.parsing import (
    DomainProfileIn,
    DomainProfileOut,
)


def _builtin_profiles_path() -> Path:
    return Path(__file__).resolve().parents[1] / "domain_profiles" / "builtin_profiles.json"


def _load_builtin_profiles() -> list[DomainProfileOut]:
    payload = json.loads(_builtin_profiles_path().read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [DomainProfileOut.model_validate(item) for item in payload]


BUILTIN_PROFILES: list[DomainProfileOut] = _load_builtin_profiles()


class DomainMetadataService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.profile_path = data_dir / "domain-profiles.json"

    def list_profiles(self) -> list[DomainProfileOut]:
        return [*BUILTIN_PROFILES, *self._saved_profiles()]

    def get_profile(self, profile_id: str) -> DomainProfileOut | None:
        return next(
            (profile for profile in self.list_profiles() if profile.id == profile_id),
            None,
        )

    def upsert_profile(self, profile: DomainProfileIn) -> DomainProfileOut:
        saved = DomainProfileOut.model_validate(profile.model_dump())
        if saved.id in {item.id for item in BUILTIN_PROFILES}:
            raise ValueError(f"Domain profile id '{saved.id}' is reserved.")
        profiles = {item.id: item for item in self._saved_profiles()}
        profiles[saved.id] = saved
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(
            json.dumps([item.model_dump() for item in profiles.values()], indent=2),
            encoding="utf-8",
        )
        return saved

    def _saved_profiles(self) -> list[DomainProfileOut]:
        if not self.profile_path.exists():
            return []
        data = json.loads(self.profile_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [DomainProfileOut.model_validate(item) for item in data]

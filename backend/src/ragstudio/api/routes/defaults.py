from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from ragstudio.schemas.defaults import DefaultsOut, RuntimeDefaultsOut
from ragstudio.services.retrieval_policy import DEFAULT_RETRIEVAL_POLICY
from ragstudio.services.runtime_defaults import RUNTIME_DEFAULTS

router = APIRouter(prefix="/api/defaults", tags=["defaults"])


@router.get("", response_model=DefaultsOut)
async def get_defaults() -> DefaultsOut:
    return DefaultsOut(
        runtime=RuntimeDefaultsOut(**asdict(RUNTIME_DEFAULTS)),
        policy_versions={"retrieval": DEFAULT_RETRIEVAL_POLICY.policy_version},
    )

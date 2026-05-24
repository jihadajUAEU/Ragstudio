from __future__ import annotations

from typing import Protocol

from ragstudio.config import AppSettings
from ragstudio.db.models import Job
from ragstudio.services.http_client_provider import HttpClientProviderProtocol
from ragstudio.services.index_job_runner import IndexJobRunner
from ragstudio.services.operational_policy import DEFAULT_OPERATIONAL_POLICY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class BackgroundJobRunner(Protocol):
    async def run(self, job: Job) -> None: ...


class BackgroundRunnerFactory:
    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_OPERATIONAL_POLICY.worker.lease_seconds,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        http_client_provider: HttpClientProviderProtocol | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.session_factory = session_factory
        self.http_client_provider = http_client_provider

    @property
    def job_types(self) -> list[str]:
        return ["index_document"]

    def runner_for(self, job: Job) -> BackgroundJobRunner:
        if job.type == "index_document":
            return IndexJobRunner(
                self.session,
                self.settings,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                session_factory=self.session_factory,
                http_client_provider=self.http_client_provider,
            )
        raise RuntimeError(f"Unsupported job type: {job.type}")

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragstudio.config import AppSettings
from ragstudio.db.engine import init_db, make_engine, make_session_factory
from ragstudio.db.models import Job
from ragstudio.services.index_job_runner import IndexJobRunner
from ragstudio.services.job_queue_service import JobQueueService

logger = logging.getLogger(__name__)


async def run_once(
    session: AsyncSession,
    settings: AppSettings,
    *,
    worker_id: str,
    lease_seconds: int = 300,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    queue = JobQueueService(session)
    await queue.recover_expired_jobs()
    job = await queue.claim_next(
        worker_id=worker_id,
        job_types=["index_document"],
        lease_seconds=lease_seconds,
    )
    if job is None:
        await session.commit()
        return 0

    job_id = job.id
    await session.commit()

    try:
        await IndexJobRunner(
            session,
            settings,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            session_factory=session_factory,
        ).run(job)
        await session.commit()
        return 1
    except Exception as exc:
        logger.exception("Worker %s failed job %s.", worker_id, job_id)
        await _mark_failed_after_runner_error(
            session,
            job_id=job_id,
            worker_id=worker_id,
            reason=str(exc),
        )
        return 1


async def _mark_failed_after_runner_error(
    session: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    reason: str,
) -> None:
    try:
        await session.rollback()
        job = await session.get(Job, job_id)
        if job is None:
            logger.warning("Worker %s could not mark missing job %s failed.", worker_id, job_id)
            return
        await JobQueueService(session).mark_failed(job, worker_id=worker_id, reason=reason)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Worker %s could not mark job %s failed.", worker_id, job_id)


async def run_forever(
    *,
    poll_seconds: float = 2.0,
    worker_id: str | None = None,
    lease_seconds: int = 300,
) -> None:
    settings = AppSettings()
    engine = make_engine(settings.resolved_database_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    resolved_worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"

    try:
        while True:
            async with session_factory() as session:
                try:
                    processed = await run_once(
                        session,
                        settings,
                        worker_id=resolved_worker_id,
                        lease_seconds=lease_seconds,
                        session_factory=session_factory,
                    )
                except Exception:
                    await session.rollback()
                    logger.exception("Worker %s cycle failed.", resolved_worker_id)
                    processed = 0
            if processed == 0:
                await asyncio.sleep(poll_seconds)
    finally:
        await engine.dispose()


async def healthcheck(settings: AppSettings | None = None) -> bool:
    resolved_settings = settings or AppSettings()
    engine = make_engine(resolved_settings.resolved_database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Worker healthcheck failed.")
        return False
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run the Ragstudio indexing worker.")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Check worker dependencies and exit.",
    )
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(0 if asyncio.run(healthcheck()) else 1)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()

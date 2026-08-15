import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import DurableJob, JobType, LeaseOwnershipLost
from app.jobs.repository import JobRepository

JobHandler = Callable[[DurableJob], Awaitable[None]]


class JobRunner:
    def __init__(
        self,
        *,
        worker_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        repository: JobRepository,
        handlers: dict[JobType, JobHandler],
        poll_seconds: float,
        lease_seconds: float,
        job_types: tuple[JobType, ...] | None = None,
        concurrency: int = 1,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self._worker_id = worker_id
        self._session_factory = session_factory
        self._repository = repository
        self._handlers = handlers
        self._poll_seconds = poll_seconds
        self._lease_seconds = lease_seconds
        self._job_types = job_types
        self._concurrency = concurrency
        self._stop = asyncio.Event()

    async def run(self) -> None:
        await asyncio.gather(*(self._worker_loop(index) for index in range(self._concurrency)))

    async def stop(self) -> None:
        self._stop.set()

    async def _worker_loop(self, index: int) -> None:
        worker_id = self._worker_id if self._concurrency == 1 else f"{self._worker_id}:{index}"
        while not self._stop.is_set():
            job = await self._claim_one(worker_id)
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                except TimeoutError:
                    pass
                continue
            await self._execute(job, worker_id)

    async def _claim_one(self, worker_id: str) -> DurableJob | None:
        async with self._session_factory() as session, session.begin():
            jobs = await self._repository.claim(
                session,
                worker_id=worker_id,
                limit=1,
                job_types=self._job_types,
            )
            return jobs[0] if jobs else None

    async def _execute(self, job: DurableJob, worker_id: str | None = None) -> None:
        owner_id = worker_id or self._worker_id
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._mark_failed(
                job,
                f"no handler registered for {job.job_type.value}",
                owner_id,
            )
            return
        renewal_stop = asyncio.Event()
        handler_task = asyncio.create_task(handler(job))
        renewal_task = asyncio.create_task(self._renew_lease(job, renewal_stop, owner_id))
        lease_lost = False
        try:
            done, _pending = await asyncio.wait(
                (handler_task, renewal_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if renewal_task in done:
                # _renew_lease only ends by raising LeaseOwnershipLost: the
                # job was reclaimed by reconciliation and belongs to another
                # worker now. Stop the handler immediately instead of letting
                # two workers execute the same job side by side.
                lease_lost = True
                handler_task.cancel()
        except asyncio.CancelledError:
            handler_task.cancel()
            if not lease_lost:
                await self._mark_failed(job, "worker shutdown during job execution", owner_id)
            raise
        finally:
            renewal_stop.set()
            try:
                await renewal_task
            except LeaseOwnershipLost:
                lease_lost = True
        try:
            await handler_task
        except asyncio.CancelledError:
            if lease_lost:
                return
            raise
        except Exception as exc:
            if lease_lost:
                return
            await self._mark_failed(job, f"{type(exc).__name__}: {exc}", owner_id)
            return
        if lease_lost:
            # The job belongs to another worker now; this worker must not
            # mark it succeeded or failed.
            return
        async with self._session_factory() as session, session.begin():
            await self._repository.succeed(
                session,
                job_id=job.id,
                worker_id=owner_id,
            )

    async def _mark_failed(self, job: DurableJob, error: str, worker_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            await self._repository.fail(
                session,
                job_id=job.id,
                worker_id=worker_id,
                error=error,
            )

    async def _renew_lease(
        self,
        job: DurableJob,
        stop: asyncio.Event,
        worker_id: str,
    ) -> None:
        interval = max(self._lease_seconds / 3.0, 1.0)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                async with self._session_factory() as session, session.begin():
                    renewed = await self._repository.renew_lease(
                        session,
                        job_id=job.id,
                        worker_id=worker_id,
                    )
                if not renewed:
                    raise LeaseOwnershipLost("durable job lease ownership was lost") from None

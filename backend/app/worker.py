import asyncio
import logging
import os
import socket

from pathlib import Path
from time import monotonic
from uuid import uuid4

from dotenv import load_dotenv

from app.config import get_database_url

from app.harness.experiment_service import (
    ExperimentService,
)
from app.harness.postgres_experiment_store import (
    PostgresExperimentStore,
)
from app.harness.postgres_run_store import (
    PostgresRunStore,
)

from app.jobs.errors import JobOwnershipError
from app.jobs.executor import EvaluationJobExecutor
from app.jobs.models import EvaluationJob
from app.jobs.postgres_store import (
    PostgresEvaluationJobStore,
)
from app.jobs.store import EvaluationJobStore

from app.runtime_factory import build_harness_runner


logger = logging.getLogger(__name__)


# ============================================================
# 1. Worker configuration
# ============================================================

LEASE_SECONDS = 60
POLL_INTERVAL = 2.0
RECOVERY_INTERVAL = 10.0
MAX_ATTEMPTS = 3
RECOVERY_BATCH_SIZE = 100


def generate_worker_id() -> str:
    """
    Generate a unique identity for one Worker process.
    """

    hostname = socket.gethostname()
    process_id = os.getpid()
    suffix = uuid4().hex[:8]

    return f"{hostname}-{process_id}-{suffix}"


# ============================================================
# 2. Independent heartbeat loop
# ============================================================

async def heartbeat_loop(
    *,
    store: EvaluationJobStore,
    job: EvaluationJob,
    stop_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
    lease_seconds: int = LEASE_SECONDS,
) -> None:
    """
    Periodically renew the lease of one claimed Job.

    The loop runs concurrently with EvaluationJobExecutor.

    It stops when:
      1. Job execution finishes.
      2. The lease is no longer owned.
      3. Heartbeat raises an exception.

    A heartbeat failure is signalled through
    lease_lost_event so the Worker can report it.

    Executor database writes must still enforce
    worker_id + attempt_count + valid lease.
    """

    if not job.worker_id:
        raise ValueError(
            "Claimed Job has no worker_id"
        )

    if job.attempt_count < 1:
        raise ValueError(
            "Invalid Job attempt_count"
        )

    if lease_seconds <= 0:
        raise ValueError(
            "lease_seconds must be positive"
        )

    interval = lease_seconds / 3

    logger.info(
        "Heartbeat started: job=%s attempt=%s interval=%.1fs",
        job.job_id,
        job.attempt_count,
        interval,
    )

    while not stop_event.is_set():

        # Wait for the next heartbeat deadline.
        #
        # If the Executor finishes early, stop_event
        # wakes this loop immediately.
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval,
            )

            break

        except asyncio.TimeoutError:
            pass

        # Stop if execution has already finished.
        if stop_event.is_set():
            break

        try:
            renewed = await store.heartbeat(
                job_id=job.job_id,
                worker_id=job.worker_id,
                attempt_count=job.attempt_count,
                lease_seconds=lease_seconds,
            )

        except Exception:
            logger.exception(
                "Heartbeat error: job=%s attempt=%s",
                job.job_id,
                job.attempt_count,
            )

            # The lease is now unconfirmed.
            # Do not assume that the Worker owns it.
            lease_lost_event.set()
            return

        if not renewed:
            logger.warning(
                "Heartbeat rejected: job=%s "
                "worker=%s attempt=%s",
                job.job_id,
                job.worker_id,
                job.attempt_count,
            )

            lease_lost_event.set()
            return

        logger.debug(
            "Heartbeat renewed: job=%s attempt=%s",
            job.job_id,
            job.attempt_count,
        )

    logger.debug(
        "Heartbeat stopped: job=%s",
        job.job_id,
    )


# ============================================================
# 3. Execute one claimed Job with heartbeat
# ============================================================

async def run_claimed_job(
    *,
    job: EvaluationJob,
    job_store: EvaluationJobStore,
    executor: EvaluationJobExecutor,
    lease_seconds: int = LEASE_SECONDS,
) -> None:
    """
    Run one claimed Job and maintain its lease.

    The Executor performs actual evaluation.

    The heartbeat task renews its lease independently.

    Every task is responsible for database operations
    through short-lived connections and transactions.
    """

    if job.status != "running":
        raise ValueError(
            "Only a running Job may be executed"
        )

    if not job.worker_id:
        raise ValueError(
            "Claimed Job has no worker_id"
        )

    stop_event = asyncio.Event()
    lease_lost_event = asyncio.Event()

    # Start the heartbeat before the Executor.
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(
            store=job_store,
            job=job,
            stop_event=stop_event,
            lease_lost_event=lease_lost_event,
            lease_seconds=lease_seconds,
        ),
        name=f"heartbeat-{job.job_id}",
    )

    logger.info(
        "Job execution started: "
        "job=%s worker=%s attempt=%s cases=%s",
        job.job_id,
        job.worker_id,
        job.attempt_count,
        job.total_cases,
    )

    try:
        result = await executor.execute(job)

        if lease_lost_event.is_set():
            logger.warning(
                "Job execution ended after heartbeat "
                "became unconfirmed: job=%s",
                job.job_id,
            )

        logger.info(
            "Job execution finished: "
            "job=%s status=%s progress=%s/%s",
            job.job_id,
            result.status,
            result.processed_cases,
            result.total_cases,
        )

    except JobOwnershipError:
        # A stale Worker must not change the Job
        # or Experiment terminal state.
        logger.warning(
            "Job ownership lost: "
            "job=%s worker=%s attempt=%s",
            job.job_id,
            job.worker_id,
            job.attempt_count,
        )

    except asyncio.CancelledError:
        # Do not swallow process shutdown.
        #
        # The unfinished Job will retain its
        # database state until lease recovery.
        logger.warning(
            "Job execution interrupted: job=%s",
            job.job_id,
        )

        raise

    except Exception:
        # The Executor should attempt a fenced
        # mark_failed() for ordinary failures.
        #
        # If that fails because PostgreSQL is
        # unavailable, lease recovery will handle
        # the abandoned Job later.
        logger.exception(
            "Job execution failed: job=%s",
            job.job_id,
        )

    finally:
        # Notify heartbeat to exit immediately.
        stop_event.set()

        # Wait for the heartbeat task to finish
        # before returning to the main Worker loop.
        try:
            await heartbeat_task

        except asyncio.CancelledError:
            heartbeat_task.cancel()
            raise

        except Exception:
            logger.exception(
                "Heartbeat task terminated unexpectedly: "
                "job=%s",
                job.job_id,
            )


# ============================================================
# 4. Recover expired jobs
# ============================================================

async def recover_expired_jobs(
    *,
    store: EvaluationJobStore,
    max_attempts: int = MAX_ATTEMPTS,
    limit: int = RECOVERY_BATCH_SIZE,
) -> None:
    """
    Recover expired running or cancel_requested Jobs.

    Expected transitions:
      running + expired -> queued
      running + exhausted attempts -> failed
      cancel_requested + expired -> cancelled

    Actual transitions are performed atomically
    inside PostgresEvaluationJobStore.
    """

    recovered_jobs = await store.recover_expired(
        max_attempts=max_attempts,
        limit=limit,
    )

    for job in recovered_jobs:
        logger.warning(
            "Recovered expired Job: "
            "job=%s status=%s attempt=%s",
            job.job_id,
            job.status,
            job.attempt_count,
        )


# ============================================================
# 5. Main Worker polling loop
# ============================================================

async def run_worker(
    *,
    poll_interval: float = POLL_INTERVAL,
    lease_seconds: int = LEASE_SECONDS,
    recovery_interval: float = RECOVERY_INTERVAL,
    max_attempts: int = MAX_ATTEMPTS,
) -> None:
    """
    Start a standalone evaluation Worker.

    Responsibilities:
      1. Open database connections.
      2. Build Harness and Experiment services.
      3. Periodically recover expired Jobs.
      4. Atomically claim the next queued Job.
      5. Execute it with an independent heartbeat.
      6. Repeat until the process stops.

    Only one Job is executed at a time per Worker.
    Multiple Worker processes can run concurrently.
    """

    if poll_interval <= 0:
        raise ValueError(
            "poll_interval must be positive"
        )

    if recovery_interval <= 0:
        raise ValueError(
            "recovery_interval must be positive"
        )

    if lease_seconds <= 0:
        raise ValueError(
            "lease_seconds must be positive"
        )

    if max_attempts < 1:
        raise ValueError(
            "max_attempts must be at least 1"
        )

    database_url = get_database_url()
    worker_id = generate_worker_id()

    logger.info(
        "Worker starting: worker=%s",
        worker_id,
    )

    # --------------------------------------------------------
    # Open independent PostgreSQL connection pools
    # --------------------------------------------------------

    async with (
        PostgresRunStore(database_url) as run_store,
        PostgresExperimentStore(database_url)
            as experiment_store,
        PostgresEvaluationJobStore(database_url)
            as job_store,
    ):

        # Initialize or validate existing schemas.
        await run_store.initialize()
        await experiment_store.initialize()
        await job_store.initialize()

        # ----------------------------------------------------
        # Build existing Harness components
        # ----------------------------------------------------

        experiment_service = ExperimentService(
            experiment_store=experiment_store,
            run_store=run_store,
        )

        harness_runner = build_harness_runner(
            run_store=run_store,
        )

        executor = EvaluationJobExecutor(
            job_store=job_store,
            experiment_service=experiment_service,
            harness_runner=harness_runner,
        )

        logger.info(
            "Worker ready: worker=%s",
            worker_id,
        )

        # First recovery happens immediately.
        next_recovery_at = 0.0

        # ----------------------------------------------------
        # Continuous polling
        # ----------------------------------------------------

        while True:

            try:
                now = monotonic()

                # --------------------------------------------
                # A. Recover expired Jobs periodically
                # --------------------------------------------

                if now >= next_recovery_at:

                    # Set the next deadline before recovery
                    # to avoid tight repeated attempts.
                    next_recovery_at = (
                        now + recovery_interval
                    )

                    await recover_expired_jobs(
                        store=job_store,
                        max_attempts=max_attempts,
                        limit=RECOVERY_BATCH_SIZE,
                    )

                # --------------------------------------------
                # B. Atomically claim one queued Job
                # --------------------------------------------

                job = await job_store.claim_next(
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )

                if job is None:
                    await asyncio.sleep(
                        poll_interval
                    )
                    continue

                logger.info(
                    "Job claimed: "
                    "job=%s worker=%s attempt=%s",
                    job.job_id,
                    worker_id,
                    job.attempt_count,
                )

                # --------------------------------------------
                # C. Execute Job and renew its lease
                # --------------------------------------------

                await run_claimed_job(
                    job=job,
                    job_store=job_store,
                    executor=executor,
                    lease_seconds=lease_seconds,
                )

                # After a completed execution,
                # immediately poll the next Job.

            except asyncio.CancelledError:
                logger.info(
                    "Worker shutting down: %s",
                    worker_id,
                )
                raise

            except Exception:
                # A transient queue/database error
                # must not terminate the Worker.
                logger.exception(
                    "Worker polling error: %s",
                    worker_id,
                )

                await asyncio.sleep(
                    poll_interval
                )


# ============================================================
# 6. Program entry point
# ============================================================

def main() -> None:
    """
    Entry point:

        python -m app.worker
    """

    backend_dir = (
        Path(__file__).resolve().parents[1]
    )

    # The standalone Worker does not receive
    # uvicorn's --env-file argument.
    load_dotenv(
        dotenv_path=backend_dir / ".env"
    )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s "
            "%(message)s"
        ),
    )

    logger.info(
        "Starting Evaluation Worker process"
    )

    try:
        asyncio.run(
            run_worker()
        )

    except KeyboardInterrupt:
        logger.info(
            "Worker stopped by keyboard interrupt"
        )


if __name__ == "__main__":
    main()

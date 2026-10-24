from app.adapters.intelligent.published import bind_published_runner, METRIC_SEMANTICS

import logging

from app.harness.experiment_service import (
    ExperimentService,
)
from app.harness.runner import (
    HarnessRunner,
)

from app.jobs.errors import (
    JobOwnershipError,
)
from app.jobs.models import (
    EvaluationJob,
    EvaluationJobStatus,
)
from app.jobs.store import (
    EvaluationJobStore,
)


logger = logging.getLogger(__name__)


class EvaluationJobExecutor:
    """
    Execute a claimed Evaluation Job.

    Responsibilities:
    - Verify worker ownership and lease
    - Reuse an existing Experiment
    - Resume from committed Case Checkpoints
    - Execute remaining TestCases
    - Persist Case progress
    - Reconcile Experiment Run links
    - Handle cooperative cancellation
    - Finalize Job and Experiment states

    The Executor does not claim jobs, renew leases,
    or recover expired jobs.

    Those responsibilities belong to the Worker
    and EvaluationJobStore.
    """

    def __init__(
        self,
        *,
        job_store: EvaluationJobStore,
        experiment_service: ExperimentService,
        harness_runner: HarnessRunner,
        adapter_registry=None,
    ):
        """Keep job_store/experiment_service/base harness_runner and optional adapter_registry; no per-case model work."""
        self.adapter_registry = adapter_registry
        self.job_store = job_store
        self.experiment_service = experiment_service
        self.harness_runner = harness_runner

    # =========================================================
    # 1. Verify worker execution authority
    # =========================================================

    async def _get_execution_status(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
    ) -> EvaluationJobStatus:
        """
        Read current execution status from PostgreSQL.

        A None result means:
        - lease expired, or
        - worker_id mismatch, or
        - attempt_count mismatch, or
        - job is no longer executable.

        Never trust the old EvaluationJob snapshot
        returned by claim_next().
        """

        status = (
            await self.job_store.get_execution_status(
                job_id=job_id,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
        )

        if status is None:
            raise JobOwnershipError(
                f"Execution authority lost: "
                f"job_id={job_id}, "
                f"worker_id={worker_id}, "
                f"attempt={attempt_count}"
            )

        return status

    # =========================================================
    # 2. Reconcile Experiment terminal state
    # =========================================================

    async def _sync_experiment_terminal(
        self,
        *,
        experiment_id: str | None,
        target_status: str,
    ) -> None:
        """
        Best-effort reconciliation after the Job
        has successfully entered a terminal state.

        The existing Experiment model does not yet
        have a dedicated cancelled state.

        Therefore cancelled is temporarily mapped
        to Experiment.failed.

        Any failure here is logged rather than
        overwriting the already committed Job state.

        V0.13.6 production hardening should add
        durable reconciliation for this operation.
        """

        if experiment_id is None:
            return

        try:
            if target_status == "completed":
                await self.experiment_service.complete(
                    experiment_id
                )

            elif target_status in (
                "failed",
                "cancelled",
            ):
                await self.experiment_service.fail(
                    experiment_id
                )

            else:
                raise ValueError(
                    f"Unsupported terminal status: "
                    f"{target_status}"
                )

        except Exception:
            logger.exception(
                "Experiment terminal sync failed: "
                "experiment=%s target=%s",
                experiment_id,
                target_status,
            )

    # =========================================================
    # 3. Finish a cancelled Job
    # =========================================================

    async def _finish_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt_count: int,
        experiment_id: str | None,
    ) -> EvaluationJob:
        """
        Confirm cancellation with a fenced
        PostgreSQL state transition.

        Only the current worker attempt can
        change cancel_requested -> cancelled.
        """

        cancelled_job = (
            await self.job_store.mark_cancelled(
                job_id=job_id,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
        )

        logger.info(
            "Evaluation Job cancelled: "
            "job=%s attempt=%s progress=%s/%s",
            job_id,
            attempt_count,
            cancelled_job.processed_cases,
            cancelled_job.total_cases,
        )

        await self._sync_experiment_terminal(
            experiment_id=experiment_id,
            target_status="cancelled",
        )

        return cancelled_job

    # =========================================================
    # 4. Create or reuse an Experiment
    # =========================================================

    async def _get_or_create_experiment(
        self,
        *,
        job: EvaluationJob,
        worker_id: str,
        attempt_count: int,
    ) -> str:
        """
        Reuse the Experiment associated with the Job.

        If no Experiment is attached, create one
        and persist the association.

        Note:
        Experiment creation should ultimately
        be idempotent by evaluation_job_id, to
        eliminate the create-before-attach
        crash window.
        """

        if job.experiment_id is not None:
            logger.info(
                "Resuming existing Experiment: "
                "job=%s experiment=%s",
                job.job_id,
                job.experiment_id,
            )

            return job.experiment_id

        payload = job.payload

        experiment = await (
            self.experiment_service.create(
                name=payload.name,
                dataset_version=payload.dataset_version,
                agent_version=payload.agent_version,
                model_name=payload.model_name,
                prompt_version=payload.prompt_version,
                metadata={
                    **payload.metadata,
                    "evaluation_job_id": job.job_id,
                    **({"intelligent_adapter": {
                        "adapter_id": payload.adapter_id, "adapter_version": payload.adapter_version,
                        "mapping_digest": payload.adapter_mapping_digest, "metric_semantics": METRIC_SEMANTICS,
                    }} if payload.adapter_id is not None else {}),
                },
            )
        )

        experiment_id = experiment.experiment_id

        await self.job_store.attach_experiment(
            job_id=job.job_id,
            worker_id=worker_id,
            attempt_count=attempt_count,
            experiment_id=experiment_id,
        )

        logger.info(
            "Experiment attached: "
            "job=%s experiment=%s",
            job.job_id,
            experiment_id,
        )

        return experiment_id

    # =========================================================
    # 5. Validate committed Case Checkpoints
    # =========================================================

    async def _load_checkpoints(
        self,
        job: EvaluationJob,
    ) -> dict[str, dict]:
        """
        Load previously committed Case results.

        Checkpoint count must match persisted
        Job progress.

        This intentionally rejects old partial Jobs
        without Checkpoints, instead of blindly
        rerunning already processed Cases.
        """

        existing_results = (
            await self.job_store.get_case_results(
                job.job_id
            )
        )

        processed = (
            job.completed_cases
            + job.failed_cases
        )

        if processed != len(existing_results):
            raise RuntimeError(
                "Job progress / checkpoint mismatch: "
                f"job={job.job_id}, "
                f"processed={processed}, "
                f"checkpoints={len(existing_results)}"
            )

        expected_case_ids = {
            case.id
            for case in job.payload.cases
        }

        unknown_case_ids = (
            set(existing_results)
            - expected_case_ids
        )

        if unknown_case_ids:
            raise RuntimeError(
                "Checkpoint contains unknown cases: "
                f"{sorted(unknown_case_ids)}"
            )

        succeeded = sum(
            item["outcome"] == "succeeded"
            for item in existing_results.values()
        )

        failed = sum(
            item["outcome"] == "failed"
            for item in existing_results.values()
        )

        if (
            succeeded != job.completed_cases
            or failed != job.failed_cases
        ):
            raise RuntimeError(
                "Checkpoint outcomes do not match "
                f"Job counters: {job.job_id}"
            )

        return existing_results

    # =========================================================
    # 6. Ensure Run belongs to the Experiment
    # =========================================================

    async def _ensure_run_linked(
        self,
        *,
        experiment_id: str,
        run_id: str,
    ) -> None:
        """
        Idempotently associate a Run with an Experiment.

        Requires ExperimentService.ensure_run_linked()
        to be implemented as a database-level
        idempotent operation.
        """

        await self.experiment_service.ensure_run_linked(
            experiment_id=experiment_id,
            run_id=run_id,
        )

    # =========================================================
    # 7. Main execution
    # =========================================================

    async def execute(
        self,
        job: EvaluationJob,
    ) -> EvaluationJob:
        """
        Execute or resume one claimed Job.

        The caller must provide the EvaluationJob
        returned by PostgresEvaluationJobStore.claim_next().
        """

        if job.status != "running":
            raise ValueError(
                "Executor requires a running Job"
            )

        if not job.worker_id:
            raise ValueError(
                "Running Job has no worker_id"
            )

        if job.attempt_count < 1:
            raise ValueError(
                "Running Job has invalid attempt_count"
            )

        job_id = job.job_id
        worker_id = job.worker_id
        attempt_count = job.attempt_count

        experiment_id = job.experiment_id

        logger.info(
            "Starting Evaluation Job: "
            "job=%s worker=%s attempt=%s",
            job_id,
            worker_id,
            attempt_count,
        )

        try:
            # -------------------------------------------------
            # Step 1: Verify current execution authority
            # -------------------------------------------------

            status = await self._get_execution_status(
                job_id=job_id,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )

            job_runner = await bind_published_runner(self.harness_runner, job, self.adapter_registry)

            # -------------------------------------------------
            # Step 2: Load committed Case Checkpoints
            # -------------------------------------------------

            existing_results = (
                await self._load_checkpoints(job)
            )

            logger.info(
                "Job checkpoint loaded: "
                "job=%s committed=%s total=%s",
                job_id,
                len(existing_results),
                job.total_cases,
            )

            # -------------------------------------------------
            # Step 3: Handle cancellation before startup
            # -------------------------------------------------

            if (
                status == "cancel_requested"
                and len(existing_results) < job.total_cases
            ):
                return await self._finish_cancelled(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                    experiment_id=experiment_id,
                )

            # -------------------------------------------------
            # Step 4: Create or reuse Experiment
            # -------------------------------------------------

            experiment_id = (
                await self._get_or_create_experiment(
                    job=job,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )
            )

            # -------------------------------------------------
            # Step 5: Reconcile previously committed Runs
            # -------------------------------------------------

            for case in job.payload.cases:
                checkpoint = existing_results.get(
                    case.id
                )

                if checkpoint is None:
                    continue

                await self._get_execution_status(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )

                if job.payload.adapter_id is not None:
                    persisted = await self.experiment_service.run_store.get(checkpoint["run_id"])
                    binding = persisted.metadata.get("intelligent_adapter", {}) if persisted else {}
                    if any(binding.get(key) != expected for key, expected in {
                        "adapter_id": job.payload.adapter_id, "adapter_version": job.payload.adapter_version,
                        "mapping_digest": job.payload.adapter_mapping_digest,
                    }.items()):
                        raise RuntimeError("Checkpoint mapping binding does not match immutable Job")
                await self._ensure_run_linked(
                    experiment_id=experiment_id,
                    run_id=checkpoint["run_id"],
                )

            # -------------------------------------------------
            # Step 6: Execute remaining Cases
            # -------------------------------------------------

            for case in job.payload.cases:

                # Recheck lease and ownership before
                # any new execution starts.
                status = await self._get_execution_status(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )

                if case.id in existing_results:
                    logger.info(
                        "Skipping committed Case: "
                        "job=%s case=%s",
                        job_id,
                        case.id,
                    )
                    continue

                # Cancel only when unprocessed
                # Cases remain.
                if status == "cancel_requested":
                    return await self._finish_cancelled(
                        job_id=job_id,
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                        experiment_id=experiment_id,
                    )

                logger.info(
                    "Executing Case: "
                    "job=%s case=%s attempt=%s",
                    job_id,
                    case.id,
                    attempt_count,
                )

                # ---------------------------------------------
                # Execute one Case through existing Harness
                # ---------------------------------------------

                report = await job_runner.run(
                    [case]
                )

                if len(report.results) != 1:
                    raise RuntimeError(
                        "Expected exactly one CaseResult"
                    )

                result = report.results[0]

                if result.run_id is None:
                    raise RuntimeError(
                        "CaseResult has no run_id"
                    )

                outcome = (
                    "failed"
                    if result.error is not None
                    else "succeeded"
                )

                # ---------------------------------------------
                # Atomically commit Checkpoint + Progress
                # ---------------------------------------------

                updated_job = (
                    await self.job_store.record_case_result(
                        job_id=job_id,
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                        case_id=case.id,
                        run_id=result.run_id,
                        outcome=outcome,
                    )
                )

                # ---------------------------------------------
                # Read canonical persisted Checkpoint
                # ---------------------------------------------

                persisted_results = (
                    await self.job_store.get_case_results(
                        job_id
                    )
                )

                checkpoint = persisted_results.get(
                    case.id
                )

                if checkpoint is None:
                    raise RuntimeError(
                        "Case Checkpoint missing after commit: "
                        f"{case.id}"
                    )

                # When record_case_result handles an
                # idempotent conflict, the committed
                # run_id is authoritative, not the
                # newly produced result.run_id.
                await self._get_execution_status(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )

                await self._ensure_run_linked(
                    experiment_id=experiment_id,
                    run_id=checkpoint["run_id"],
                )

                existing_results[case.id] = checkpoint

                logger.info(
                    "Case committed: "
                    "job=%s case=%s outcome=%s "
                    "progress=%s/%s",
                    job_id,
                    case.id,
                    checkpoint["outcome"],
                    updated_job.processed_cases,
                    updated_job.total_cases,
                )

            # -------------------------------------------------
            # Step 7: Verify all Cases have been committed
            # -------------------------------------------------

            if len(existing_results) != job.total_cases:
                raise RuntimeError(
                    "Cannot complete Job: "
                    f"committed={len(existing_results)}, "
                    f"total={job.total_cases}"
                )

            # -------------------------------------------------
            # Step 8: Commit Job terminal state first
            # -------------------------------------------------

            # mark_completed() must verify:
            # - worker_id
            # - attempt_count
            # - lease_expires_at
            # - all Cases accounted for
            #
            # A late cancel_requested may still become
            # completed when every Case has finished.

            completed_job = (
                await self.job_store.mark_completed(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )
            )

            # -------------------------------------------------
            # Step 9: Reconcile Experiment terminal state
            # -------------------------------------------------

            await self._sync_experiment_terminal(
                experiment_id=experiment_id,
                target_status="completed",
            )

            logger.info(
                "Evaluation Job completed: "
                "job=%s experiment=%s "
                "success=%s failed=%s",
                job_id,
                experiment_id,
                completed_job.completed_cases,
                completed_job.failed_cases,
            )

            return completed_job

        # =====================================================
        # Lost lease / stale Worker
        # =====================================================

        except JobOwnershipError:
            logger.warning(
                "Worker lost execution authority: "
                "job=%s worker=%s attempt=%s",
                job_id,
                worker_id,
                attempt_count,
            )

            # Critical:
            # Do not mark Job failed.
            # Do not change Experiment status.
            #
            # A newer Worker attempt may already
            # own this Job.

            raise

        # =====================================================
        # Normal execution failure
        # =====================================================

        except Exception as exc:
            logger.exception(
                "Evaluation Job execution failed: "
                "job=%s attempt=%s",
                job_id,
                attempt_count,
            )

            # Try to persist failure using the
            # current fencing token.
            #
            # If ownership was lost, this update
            # must be rejected by PostgreSQL.

            try:
                await self.job_store.mark_failed(
                    job_id=job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                    error=(
                        "Evaluation execution failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

            except JobOwnershipError:
                logger.warning(
                    "Failure update rejected: "
                    "worker no longer owns job=%s",
                    job_id,
                )

                # Never modify Experiment state
                # after losing Job ownership.
                raise

            except Exception:
                logger.exception(
                    "Could not persist failure state: "
                    "job=%s",
                    job_id,
                )
                raise

            # Only synchronize Experiment after
            # the fenced Job failure is committed.
            await self._sync_experiment_terminal(
                experiment_id=experiment_id,
                target_status="failed",
            )

            raise

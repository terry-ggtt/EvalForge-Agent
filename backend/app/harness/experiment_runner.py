from app.evaluator.contracts import EvaluatorSelection

import asyncio

from typing import (
    Any,
    Iterable,
)

from app.harness.contracts import (
    CaseResult,
    TestCase,
)

from app.harness.experiment import (
    EvaluationExperiment,
)

from app.harness.experiment_service import (
    ExperimentService,
)

from app.harness.runner import (
    HarnessRunner,
)


class ExperimentExecutionError(
    RuntimeError
):
    pass


class ExperimentRunner:
    """
    Orchestrates one complete evaluation
    experiment.

    Lifecycle:

        create experiment
            ↓
        run dataset
            ↓
        persist runs
            ↓
        attach runs
            ↓
        complete experiment

    On orchestration failure:

        mark experiment failed
        re-raise original error
    """

    def __init__(
        self,
        *,
        harness_runner:
            HarnessRunner,

        experiment_service:
            ExperimentService,
    ):
        self.harness_runner = (
            harness_runner
        )

        self.experiment_service = (
            experiment_service
        )

    async def run(
        self,
        *,
        cases: Iterable[
            TestCase
        ],

        name: str,

        dataset_version: str,

        agent_version: str,

        model_name: (
            str | None
        ) = None,

        prompt_version: (
            str | None
        ) = None,

        metadata: (
            dict[str, Any]
            | None
        ) = None,
        evaluators: list[EvaluatorSelection] | None = None,
    ) -> EvaluationExperiment:
        """Run cases under name/dataset_version/agent_version using the existing Experiment lifecycle.

        model_name/prompt_version and metadata retain their existing meaning.
        Optional evaluators binds a task-local plan before Experiment creation,
        then supplies the known Experiment identity to SDK contexts. Returns the
        completed experiment; orchestration errors/cancellation still fail it and
        propagate. Per-evaluator failures remain persisted Case outcomes.
        """
        runner = self.harness_runner
        if evaluators is not None:
            runner = self.harness_runner.with_evaluators(evaluators)
            metadata = {**(metadata or {}), "evaluator_plan": runner.evaluator_execution.summary}
        experiment = (
            await self
            .experiment_service
            .create(
                name=
                    name,

                dataset_version=
                    dataset_version,

                agent_version=
                    agent_version,

                model_name=
                    model_name,

                prompt_version=
                    prompt_version,

                metadata=
                    metadata,
            )
        )

        if evaluators is not None:
            runner.evaluation_identity = {"experiment_id": experiment.experiment_id}
        try:

            report = (
                await runner
                .run(
                    cases
                )
            )

            await self._attach_results(
                experiment_id=
                    experiment
                    .experiment_id,

                results=
                    report.results,
            )

            return (
                await self
                .experiment_service
                .complete(
                    experiment
                    .experiment_id
                )
            )

        except asyncio.CancelledError:

            await self._safe_fail(
                experiment
                .experiment_id
            )

            raise

        except Exception:

            await self._safe_fail(
                experiment
                .experiment_id
            )

            raise

    async def _attach_results(
        self,
        *,
        experiment_id: str,
        results: list[
            CaseResult
        ],
    ) -> None:

        for result in results:

            run_id = result.run_id

            if run_id is None:

                raise (
                    ExperimentExecutionError(
                        "HarnessRunner returned "
                        "a CaseResult without "
                        "run_id."
                    )
                )

            await (
                self.experiment_service
                .add_run(
                    experiment_id=
                        experiment_id,

                    run_id=
                        run_id,
                )
            )

    async def _safe_fail(
        self,
        experiment_id: str,
    ) -> None:

        try:

            await (
                self.experiment_service
                .fail(
                    experiment_id
                )
            )

        except Exception:
            # Never hide the original
            # execution failure.
            pass
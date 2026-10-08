import asyncio
from collections.abc import Iterable
from copy import deepcopy

from app.adapters.base import (
    AgentAdapter,
)

from app.adapters.errors import (
    AgentExecutionError,
)

from app.evaluator.base import (
    BaseEvaluator,
)

from app.harness.attempt import (
    AttemptContext,
)

from app.harness.context import (
    RunContext,
)

from app.harness.contracts import (
    AgentRequest,
    AgentResult,
    CaseResult,
    EvaluationReport,
    TestCase,
)

from app.harness.policy import (
    ExecutionPolicy,
)

from app.harness.retry import (
    RetryPolicy,
)

from app.harness.retry_decider import (
    DefaultRetryDecider,
    RetryDecider,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)


class HarnessRunner:

    def __init__(
        self,
        adapter: AgentAdapter,
        evaluators: list[
            BaseEvaluator
        ],
        policy:
            ExecutionPolicy | None = None,
        retry_policy:
            RetryPolicy | None = None,
        retry_decider:
            RetryDecider | None = None,
        run_store:
            RunStore | None = None,
    ):
        if not evaluators:
            raise ValueError(
                "At least one evaluator "
                "is required."
            )

        self.adapter = adapter

        self.evaluators = (
            evaluators
        )

        self.policy = (
            policy
            or ExecutionPolicy()
        )

        self.retry_policy = (
            retry_policy
            or RetryPolicy()
        )

        self.retry_decider = (
            retry_decider
            or DefaultRetryDecider()
        )

        self.run_store = (
            run_store
        )

    async def run(
        self,
        dataset: Iterable[
            TestCase | dict
        ],
    ) -> EvaluationReport:

        cases = [
            (
                raw_case

                if isinstance(
                    raw_case,
                    TestCase,
                )

                else TestCase.model_validate(
                    raw_case
                )
            )

            for raw_case
            in dataset
        ]

        semaphore = (
            asyncio.Semaphore(
                self.policy
                .max_concurrency
            )
        )

        async def guarded_run(
            index: int,
            case: TestCase,
        ):
            async with semaphore:

                result = (
                    await self._run_case(
                        case
                    )
                )

                return (
                    index,
                    result,
                )

        tasks = [
            asyncio.create_task(
                guarded_run(
                    index,
                    case,
                )
            )

            for index, case
            in enumerate(cases)
        ]

        completed = (
            await asyncio.gather(
                *tasks
            )
        )

        completed.sort(
            key=lambda item:
                item[0]
        )

        results = [
            result

            for _, result
            in completed
        ]

        scored_results = [
            result.score

            for result
            in results
        ]

        average_score = (
            sum(
                scored_results
            )
            / len(
                scored_results
            )

            if scored_results

            else 0.0
        )

        return EvaluationReport(
            results=
                results,

            average_score=
                average_score,
        )

    async def _run_case(
        self,
        case: TestCase,
    ) -> CaseResult:

        context = (
            RunContext.create(
                case_id=
                    case.id,

                metadata=
                    case.metadata,
            )
        )

        identity = {
            "run_id":
                context.run_id,

            "case_id":
                context.case_id,
        }

        context.trace.agent_start(
            case.input_text,

            metadata=
                identity,
        )

        agent_result: (
            AgentResult | None
        ) = None

        stage = "agent"

        try:
            request = AgentRequest(
                input_text=
                    case.input_text,

                metadata={
                    **deepcopy(
                        context.metadata
                    ),

                    **identity,
                },
            )

            agent_result = (
                await self._run_agent(
                    request,
                    context,
                )
            )

            context.trace.extend_agent_events(
                agent_result.trace
            )

            context.trace.agent_end(
                context.elapsed_ms(),

                metadata=
                    identity,
            )

            agent_result.trace = (
                context.trace.events
            )

            agent_result.metadata = {
                **agent_result.metadata,
                **identity,
            }

            stage = "evaluation"

            metric_results = []

            for evaluator in (
                self.evaluators
            ):

                metric = (
                    await evaluator
                    .evaluate(
                        case,
                        agent_result,
                    )
                )

                metric_results.append(
                    metric
                )

            scored_metrics = [
                metric.score

                for metric
                in metric_results

                if metric.score
                is not None
            ]

            score = (
                sum(
                    scored_metrics
                )
                / len(
                    scored_metrics
                )

                if scored_metrics

                else 0.0
            )

            result = CaseResult(
                run_id=
                    context.run_id,

                case_id=
                    case.id,

                input_text=
                    case.input_text,

                expected_output=
                    case.expected_output,

                actual_output=
                    agent_result
                    .output_text,

                metrics=
                    metric_results,

                score=
                    score,

                trace=
                    context.trace.events,
            )

            await self._persist_run(
                case=case,
                result=result,
                context=context,
            )

            return result

        except Exception as exc:

            if isinstance(
                exc,
                AgentExecutionError,
            ):
                context.trace.extend_agent_events(
                    exc.trace
                )

            source = (
                self._unwrap_agent_error(
                    exc
                )
            )

            timed_out = (
                stage == "agent"
                and isinstance(
                    exc,
                    TimeoutError,
                )
                and isinstance(
                    exc.__cause__,
                    asyncio.CancelledError,
                )
            )

            if timed_out:

                message = (
                    "Agent execution "
                    "timed out after "
                    f"{self.policy.timeout_seconds} "
                    "seconds"
                )

                source = TimeoutError(
                    message
                )

            else:

                message = (
                    str(exc)

                    if isinstance(
                        exc,
                        AgentExecutionError,
                    )

                    else (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
                )

            events = (
                context.trace.events
            )

            last = (
                events[-1]
                if events
                else None
            )

            if (
                last is not None

                and last.type
                == "error"

                and last.payload.get(
                    "error_type"
                )
                == type(
                    source
                ).__name__

                and last.payload.get(
                    "message"
                )
                == str(source)
            ):

                error_event = last

                error_event.payload[
                    "elapsed_ms"
                ] = (
                    context.elapsed_ms()
                )

            else:

                error_event = (
                    context.trace.error(
                        source,
                        context.elapsed_ms(),
                    )
                )

            error_event.payload.setdefault(
                "metadata",
                {},
            ).update(
                {
                    **identity,

                    "scope":
                        "run",

                    "stage":
                        stage,

                    "timeout":
                        timed_out,
                }
            )

            if (
                agent_result
                is not None
            ):

                agent_result.trace = (
                    context.trace.events
                )

            result = CaseResult(
                run_id=
                    context.run_id,

                case_id=
                    case.id,

                input_text=
                    case.input_text,

                expected_output=
                    case.expected_output,

                actual_output=(
                    agent_result.output_text

                    if agent_result
                    is not None

                    else None
                ),

                score=
                    0.0,

                trace=
                    context.trace.events,

                error=
                    message,
            )

            await self._persist_run(
                case=case,
                result=result,
                context=context,
            )

            return result

    async def _run_agent(
        self,
        request: AgentRequest,
        context: RunContext,
    ) -> AgentResult:

        timeout = (
            self.policy
            .timeout_seconds
        )

        if timeout is None:

            return await (
                self._run_agent_with_retry(
                    request,
                    context,
                )
            )

        return await asyncio.wait_for(
            self._run_agent_with_retry(
                request,
                context,
            ),

            timeout=
                timeout,
        )

    async def _run_agent_with_retry(
        self,
        request: AgentRequest,
        context: RunContext,
    ) -> AgentResult:

        policy = (
            self.retry_policy
        )

        for attempt_number in range(
            1,
            policy.max_attempts + 1,
        ):

            attempt = (
                AttemptContext.create(
                    attempt_number=
                        attempt_number
                )
            )

            context.current_attempt = (
                attempt
            )

            context.trace.attempt_start(
                attempt_id=
                    attempt.attempt_id,

                attempt_number=
                    attempt
                    .attempt_number,
            )

            delay = 0.0

            try:
                result = (
                    await self.adapter.run(
                        request,
                        context,
                    )
                )

                context.trace.attempt_end(
                    attempt_id=
                        attempt
                        .attempt_id,

                    attempt_number=
                        attempt
                        .attempt_number,

                    elapsed_ms=
                        attempt
                        .elapsed_ms(),

                    success=
                        True,
                )

                return result

            except asyncio.CancelledError:

                context.trace.attempt_end(
                    attempt_id=
                        attempt
                        .attempt_id,

                    attempt_number=
                        attempt
                        .attempt_number,

                    elapsed_ms=
                        attempt
                        .elapsed_ms(),

                    success=
                        False,

                    cancelled=
                        True,
                )

                raise

            except Exception as exc:

                if isinstance(
                    exc,
                    AgentExecutionError,
                ):

                    context.trace.extend_agent_events(
                        exc.trace
                    )

                source = (
                    self._unwrap_agent_error(
                        exc
                    )
                )

                context.trace.attempt_end(
                    attempt_id=
                        attempt
                        .attempt_id,

                    attempt_number=
                        attempt
                        .attempt_number,

                    elapsed_ms=
                        attempt
                        .elapsed_ms(),

                    success=
                        False,

                    error_type=
                        type(
                            source
                        ).__name__,

                    error_message=
                        str(source),
                )

                has_more_attempts = (
                    attempt_number
                    < policy.max_attempts
                )

                retryable = (
                    self.retry_decider
                    .should_retry(
                        source
                    )
                )

                if (
                    not has_more_attempts
                    or not retryable
                ):
                    raise

                delay = (
                    policy
                    .delay_for_attempt(
                        attempt_number
                    )
                )

                context.trace.retry(
                    previous_attempt_id=
                        attempt
                        .attempt_id,

                    next_attempt_number=
                        attempt_number + 1,

                    delay_seconds=
                        delay,

                    reason=(
                        f"{type(source).__name__}: "
                        f"{source}"
                    ),
                )

            finally:

                context.current_attempt = (
                    None
                )

            if delay > 0:

                await asyncio.sleep(
                    delay
                )

        raise RuntimeError(
            "Retry loop ended "
            "unexpectedly."
        )

    async def _persist_run(
        self,
        *,
        case: TestCase,
        result: CaseResult,
        context: RunContext,
    ) -> None:

        if self.run_store is None:
            return

        record = (
            RunRecord.from_execution(
                case=
                    case,

                result=
                    result,

                metadata=
                    context.metadata,
            )
        )

        await self.run_store.save(
            record
        )

    @staticmethod
    def _unwrap_agent_error(
        exc: Exception,
    ) -> Exception:

        source = exc

        while (
            isinstance(
                source,
                AgentExecutionError,
            )

            and source.__cause__
            is not None
        ):

            source = (
                source.__cause__
            )

        return source
from collections import (
    Counter,
)

import json

from app.evaluator.trace_scope import (
    final_successful_attempt_events,
)

from app.harness.comparison import (
    MetricComparison,
    RunComparison,
    ToolBehaviorComparison,
    ToolCallSnapshot,
)

from app.harness.contracts import (
    MetricResult,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)


class RunComparisonError(
    ValueError
):
    pass


class ComparisonRunNotFoundError(
    LookupError
):
    pass


class ComparisonService:
    """
    Compare persisted Harness runs.

    This service is storage-agnostic.

    It works with:
    - InMemoryRunStore
    - PostgresRunStore
    - any future RunStore
    """

    def __init__(
        self,
        store: RunStore,
    ):
        self.store = store

    async def compare(
        self,
        baseline_run_id: str,
        candidate_run_id: str,
        *,
        require_same_case: bool = True,
    ) -> RunComparison:

        baseline = (
            await self.store.get(
                baseline_run_id
            )
        )

        if baseline is None:

            raise (
                ComparisonRunNotFoundError(
                    "Baseline run not found: "
                    f"{baseline_run_id}"
                )
            )

        candidate = (
            await self.store.get(
                candidate_run_id
            )
        )

        if candidate is None:

            raise (
                ComparisonRunNotFoundError(
                    "Candidate run not found: "
                    f"{candidate_run_id}"
                )
            )

        return self.compare_records(
            baseline,
            candidate,
            require_same_case=
                require_same_case,
        )

    @classmethod
    def compare_records(
        cls,
        baseline: RunRecord,
        candidate: RunRecord,
        *,
        require_same_case: bool = True,
    ) -> RunComparison:

        baseline_case_id = (
            baseline.case.id
        )

        candidate_case_id = (
            candidate.case.id
        )

        if (
            require_same_case
            and baseline_case_id
            != candidate_case_id
        ):
            raise RunComparisonError(
                "Cannot compare runs from "
                "different cases: "
                f"{baseline_case_id!r} "
                "vs "
                f"{candidate_case_id!r}"
            )

        baseline_score = (
            baseline.result.score
        )

        candidate_score = (
            candidate.result.score
        )

        score_delta = (
            cls._numeric_delta(
                baseline_score,
                candidate_score,
            )
        )

        metrics = (
            cls._compare_metrics(
                baseline,
                candidate,
            )
        )

        tool_behavior = (
            cls._compare_tool_behavior(
                baseline,
                candidate,
            )
        )

        return RunComparison(
            baseline_run_id=
                baseline.run_id,

            candidate_run_id=
                candidate.run_id,

            case_id=(
                baseline_case_id
                if baseline_case_id
                == candidate_case_id
                else None
            ),

            baseline_status=
                baseline.status,

            candidate_status=
                candidate.status,

            baseline_score=
                baseline_score,

            candidate_score=
                candidate_score,

            score_delta=
                score_delta,

            metrics=
                metrics,

            tool_behavior=
                tool_behavior,
        )

    @classmethod
    def _compare_metrics(
        cls,
        baseline: RunRecord,
        candidate: RunRecord,
    ) -> list[
        MetricComparison
    ]:

        baseline_metrics = (
            cls._metric_map(
                baseline.result.metrics
            )
        )

        candidate_metrics = (
            cls._metric_map(
                candidate.result.metrics
            )
        )

        metric_names = sorted(
            set(
                baseline_metrics
            )
            | set(
                candidate_metrics
            )
        )

        comparisons: list[
            MetricComparison
        ] = []

        for name in metric_names:

            baseline_metric = (
                baseline_metrics.get(
                    name
                )
            )

            candidate_metric = (
                candidate_metrics.get(
                    name
                )
            )

            baseline_score = (
                baseline_metric.score
                if baseline_metric
                is not None
                else None
            )

            candidate_score = (
                candidate_metric.score
                if candidate_metric
                is not None
                else None
            )

            baseline_value = (
                baseline_metric.value
                if baseline_metric
                is not None
                else None
            )

            candidate_value = (
                candidate_metric.value
                if candidate_metric
                is not None
                else None
            )

            baseline_unit = (
                baseline_metric.unit
                if baseline_metric
                is not None
                else None
            )

            candidate_unit = (
                candidate_metric.unit
                if candidate_metric
                is not None
                else None
            )

            value_comparable = (
                baseline_value
                is not None
                and candidate_value
                is not None
                and baseline_unit
                == candidate_unit
            )

            value_delta = (
                cls._numeric_delta(
                    baseline_value,
                    candidate_value,
                )
                if value_comparable
                else None
            )

            comparisons.append(
                MetricComparison(
                    name=
                        name,

                    baseline_score=
                        baseline_score,

                    candidate_score=
                        candidate_score,

                    score_delta=
                        cls._numeric_delta(
                            baseline_score,
                            candidate_score,
                        ),

                    baseline_value=
                        baseline_value,

                    candidate_value=
                        candidate_value,

                    value_delta=
                        value_delta,

                    baseline_unit=
                        baseline_unit,

                    candidate_unit=
                        candidate_unit,

                    value_comparable=
                        value_comparable,
                )
            )

        return comparisons

    @classmethod
    def _compare_tool_behavior(
        cls,
        baseline: RunRecord,
        candidate: RunRecord,
    ) -> ToolBehaviorComparison:

        baseline_calls = (
            cls._extract_tool_calls(
                baseline
            )
        )

        candidate_calls = (
            cls._extract_tool_calls(
                candidate
            )
        )

        baseline_signatures = [
            cls._tool_signature(
                call
            )
            for call in baseline_calls
        ]

        candidate_signatures = [
            cls._tool_signature(
                call
            )
            for call in candidate_calls
        ]

        baseline_counter = Counter(
            baseline_signatures
        )

        candidate_counter = Counter(
            candidate_signatures
        )

        added = (
            candidate_counter
            - baseline_counter
        )

        removed = (
            baseline_counter
            - candidate_counter
        )

        return (
            ToolBehaviorComparison(
                baseline_calls=
                    baseline_calls,

                candidate_calls=
                    candidate_calls,

                same_sequence=(
                    baseline_signatures
                    == candidate_signatures
                ),

                added_call_count=
                    sum(
                        added.values()
                    ),

                removed_call_count=
                    sum(
                        removed.values()
                    ),
            )
        )

    @staticmethod
    def _extract_tool_calls(
        record: RunRecord,
    ) -> list[
        ToolCallSnapshot
    ]:

        trace = (
            final_successful_attempt_events(
                record.result.trace
            )
        )

        calls: list[
            ToolCallSnapshot
        ] = []

        for event in trace:

            if event.type != "tool_call":
                continue

            tool_name = str(
                event.payload.get(
                    "tool_name",
                    "",
                )
            )

            arguments = (
                event.payload.get(
                    "arguments",
                    {},
                )
            )

            if not isinstance(
                arguments,
                dict,
            ):
                arguments = {
                    "raw":
                        arguments
                }

            calls.append(
                ToolCallSnapshot(
                    tool_name=
                        tool_name,

                    arguments=
                        arguments,
                )
            )

        return calls

    @staticmethod
    def _tool_signature(
        call: ToolCallSnapshot,
    ) -> str:

        arguments = json.dumps(
            call.arguments,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

        return (
            f"{call.tool_name}:"
            f"{arguments}"
        )

    @staticmethod
    def _metric_map(
        metrics: list[
            MetricResult
        ],
    ) -> dict[
        str,
        MetricResult,
    ]:

        return {
            metric.name:
                metric

            for metric
            in metrics
        }

    @staticmethod
    def _numeric_delta(
        baseline:
            float | int | None,
        candidate:
            float | int | None,
    ) -> float | None:

        if (
            baseline is None
            or candidate is None
        ):
            return None

        return (
            float(candidate)
            - float(baseline)
        )
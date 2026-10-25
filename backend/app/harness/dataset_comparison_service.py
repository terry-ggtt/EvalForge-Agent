from app.evaluator.comparison import plugin_regression, plan_producers, paired_statistics
from app.harness.regression_gate import MetricGateRule
from app.harness.metric_semantics import MetricSemanticsError

from app.harness.metric_semantics import ensure_metric_semantics
import asyncio

from collections import (
    defaultdict,
)

from app.harness.comparison_service import (
    ComparisonService,
)

from app.harness.dataset_comparison import (
    AggregateMetricComparison,
    CaseComparisonReport,
    DatasetComparisonReport,
)

from app.harness.regression_detector import (
    RegressionDetector,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)


class DatasetComparisonError(
    ValueError
):
    pass


class DatasetRunNotFoundError(
    LookupError
):
    pass


class DatasetComparisonService:
    """
    Compare two collections of persisted
    Harness runs case-by-case.

    Pairing rule:

        baseline.case.id
            ==
        candidate.case.id
    """

    def __init__(
        self,
        store: RunStore,
        detector: RegressionDetector,
    ):
        self.store = store

        self.detector = detector

    async def compare(
        self,
        *,
        baseline_run_ids: list[str],
        candidate_run_ids: list[str],
        metric_rules: list[MetricGateRule] | None = None,
    ) -> DatasetComparisonReport:
        """Compare persisted baseline_run_ids/candidate_run_ids by Case ID and metric name.

        metric_rules optionally compiles plugin per-Case tolerances using the
        existing detector; omitted rules use zero plugin degradation tolerance.
        Returns paired aggregates and findings. Raises existing missing-run,
        duplicate-Case or metric-semantics errors before a Gate can pass.
        """
        baseline_records = (
            await self._load_records(
                baseline_run_ids,
                side="baseline",
            )
        )

        candidate_records = (
            await self._load_records(
                candidate_run_ids,
                side="candidate",
            )
        )

        ensure_metric_semantics([*baseline_records, *candidate_records])

        baseline_by_case = (
            self._index_by_case(
                baseline_records,
                side="baseline",
            )
        )

        candidate_by_case = (
            self._index_by_case(
                candidate_records,
                side="candidate",
            )
        )

        baseline_case_ids = set(
            baseline_by_case
        )

        candidate_case_ids = set(
            candidate_by_case
        )

        matched_case_ids = sorted(
            baseline_case_ids
            & candidate_case_ids
        )

        missing_in_baseline = sorted(
            candidate_case_ids
            - baseline_case_ids
        )

        missing_in_candidate = sorted(
            baseline_case_ids
            - candidate_case_ids
        )

        case_reports: list[
            CaseComparisonReport
        ] = []

        matched_baseline_records: list[
            RunRecord
        ] = []

        matched_candidate_records: list[
            RunRecord
        ] = []

        for case_id in matched_case_ids:

            baseline = (
                baseline_by_case[
                    case_id
                ]
            )

            candidate = (
                candidate_by_case[
                    case_id
                ]
            )

            comparison = (
                ComparisonService
                .compare_records(
                    baseline,
                    candidate,
                )
            )

            regression = plugin_regression(comparison, self.detector, metric_rules)

            case_reports.append(
                CaseComparisonReport(
                    case_id=
                        case_id,

                    baseline_run_id=
                        baseline.run_id,

                    candidate_run_id=
                        candidate.run_id,

                    regression=
                        regression,
                )
            )

            matched_baseline_records.append(
                baseline
            )

            matched_candidate_records.append(
                candidate
            )

        baseline_average_score = (
            self._average_scores(
                matched_baseline_records
            )
        )

        candidate_average_score = (
            self._average_scores(
                matched_candidate_records
            )
        )

        average_score_delta = (
            self._delta(
                baseline_average_score,
                candidate_average_score,
            )
        )

        if any(record.metadata.get("evaluator_plan") is not None
               for record in matched_baseline_records + matched_candidate_records):
            score_pairs = list(zip(matched_baseline_records, matched_candidate_records))
            if all(a.result.score is not None and b.result.score is not None for a, b in score_pairs):
                baseline_average_score, candidate_average_score, average_score_delta = paired_statistics(
                    [a.result.score for a, b in score_pairs], [b.result.score for a, b in score_pairs])
            else:
                # Overall quality is unknown when the paired cohort is incomplete.
                baseline_average_score = candidate_average_score = average_score_delta = None

        regression_case_count = sum(
            1
            for case_report
            in case_reports
            if (
                case_report
                .regression
                .has_regression
            )
        )

        compared_case_count = len(
            case_reports
        )

        regression_rate = (
            regression_case_count
            / compared_case_count

            if compared_case_count
            > 0

            else 0.0
        )

        metrics = (
            self._aggregate_metrics(
                case_reports
            )
        )

        plugin_record = next((record for record in [*baseline_records, *candidate_records]
                              if record.metadata.get("evaluator_plan") is not None), None)
        return DatasetComparisonReport(
            evaluator_plan_digest=plugin_record.metadata["evaluator_plan"]["digest"] if plugin_record else None,
            expected_evaluator_ids=sorted(plan_producers(plugin_record)) if plugin_record else [],
            baseline_run_count=
                len(
                    baseline_records
                ),

            candidate_run_count=
                len(
                    candidate_records
                ),

            compared_case_count=
                compared_case_count,

            missing_in_baseline=
                missing_in_baseline,

            missing_in_candidate=
                missing_in_candidate,

            baseline_average_score=
                baseline_average_score,

            candidate_average_score=
                candidate_average_score,

            average_score_delta=
                average_score_delta,

            regression_case_count=
                regression_case_count,

            regression_rate=
                regression_rate,

            metrics=
                metrics,

            cases=
                case_reports,
        )

    async def _load_records(
        self,
        run_ids: list[str],
        *,
        side: str,
    ) -> list[RunRecord]:

        if not run_ids:
            return []

        records = await asyncio.gather(
            *[
                self.store.get(
                    run_id
                )
                for run_id
                in run_ids
            ]
        )

        result: list[
            RunRecord
        ] = []

        for run_id, record in zip(
            run_ids,
            records,
            strict=True,
        ):

            if record is None:

                raise (
                    DatasetRunNotFoundError(
                        f"{side} run "
                        "not found: "
                        f"{run_id}"
                    )
                )

            result.append(
                record
            )

        return result

    @staticmethod
    def _index_by_case(
        records: list[RunRecord],
        *,
        side: str,
    ) -> dict[
        str,
        RunRecord,
    ]:

        result: dict[
            str,
            RunRecord,
        ] = {}

        for record in records:

            case_id = (
                record.case.id
            )

            if not case_id:

                raise DatasetComparisonError(
                    f"{side} run "
                    f"{record.run_id!r} "
                    "has no case_id."
                )

            if case_id in result:

                raise DatasetComparisonError(
                    f"Duplicate case_id "
                    f"{case_id!r} "
                    f"found in {side} runs."
                )

            result[
                case_id
            ] = record

        return result

    @staticmethod
    def _average_scores(
        records: list[RunRecord],
    ) -> float | None:

        scores = [
            float(
                record.result.score
            )

            for record
            in records

            if record.result.score
            is not None
        ]

        if not scores:
            return None

        return (
            sum(scores)
            / len(scores)
        )

    @staticmethod
    def _delta(
        baseline: float | None,
        candidate: float | None,
    ) -> float | None:

        if (
            baseline is None
            or candidate is None
        ):
            return None

        return (
            candidate
            - baseline
        )

    @staticmethod
    def _aggregate_metrics(
        case_reports: list[
            CaseComparisonReport
        ],
    ) -> list[
        AggregateMetricComparison
    ]:

        """Aggregate case_reports by metric name over valid pairs.

        Returns the original paired arithmetic means and observation counts,
        with optional SDK provenance and the full matched Case denominator.
        Inconsistent plugin evidence or unrepresentable means raise
        MetricSemanticsError; missing observations remain None.
        """
        metrics_by_name = defaultdict(
            list
        )

        for case_report in (
            case_reports
        ):

            comparison = (
                case_report
                .regression
                .comparison
            )

            for metric in (
                comparison.metrics
            ):

                metrics_by_name[
                    metric.name
                ].append(
                    metric
                )

        aggregates: list[
            AggregateMetricComparison
        ] = []

        for name in sorted(
            metrics_by_name
        ):

            metrics = (
                metrics_by_name[
                    name
                ]
            )

            baseline_scores: list[
                float
            ] = []

            candidate_scores: list[
                float
            ] = []

            for metric in metrics:

                if (
                    metric.baseline_score
                    is not None
                    and metric.candidate_score
                    is not None
                ):

                    baseline_scores.append(
                        float(
                            metric.baseline_score
                        )
                    )

                    candidate_scores.append(
                        float(
                            metric.candidate_score
                        )
                    )

            baseline_score_mean = (
                DatasetComparisonService
                ._mean(
                    baseline_scores
                )
            )

            candidate_score_mean = (
                DatasetComparisonService
                ._mean(
                    candidate_scores
                )
            )

            score_delta_mean = (
                DatasetComparisonService
                ._delta(
                    baseline_score_mean,
                    candidate_score_mean,
                )
            )

            comparable_values = [
                metric
                for metric
                in metrics
                if (
                    metric.value_comparable
                    and metric.baseline_value
                    is not None
                    and metric.candidate_value
                    is not None
                )
            ]

            units = {
                metric.baseline_unit

                for metric
                in comparable_values
            }

            value_comparable = (
                bool(
                    comparable_values
                )
                and len(units) == 1
            )

            if value_comparable:

                baseline_values = [
                    float(
                        metric.baseline_value
                    )

                    for metric
                    in comparable_values
                ]

                candidate_values = [
                    float(
                        metric.candidate_value
                    )

                    for metric
                    in comparable_values
                ]

                baseline_value_mean = (
                    DatasetComparisonService
                    ._mean(
                        baseline_values
                    )
                )

                candidate_value_mean = (
                    DatasetComparisonService
                    ._mean(
                        candidate_values
                    )
                )

                value_delta_mean = (
                    DatasetComparisonService
                    ._delta(
                        baseline_value_mean,
                        candidate_value_mean,
                    )
                )

                value_unit = next(
                    iter(units)
                )

                value_count = len(
                    comparable_values
                )

            else:

                baseline_value_mean = (
                    None
                )

                candidate_value_mean = (
                    None
                )

                value_delta_mean = None

                value_unit = None

                value_count = 0

            semantics = next((metric.semantics for metric in metrics if metric.semantics is not None), None)
            if semantics is not None:
                if any(metric.semantics != semantics for metric in metrics):
                    raise MetricSemanticsError("Plugin aggregate statistical definitions disagree")
                baseline_score_mean, candidate_score_mean, score_delta_mean = paired_statistics(
                    baseline_scores, candidate_scores)
                if value_comparable:
                    baseline_value_mean, candidate_value_mean, value_delta_mean = paired_statistics(
                        [metric.baseline_value for metric in comparable_values],
                        [metric.candidate_value for metric in comparable_values])
            aggregates.append(
                AggregateMetricComparison(
                    semantics=semantics,
                    matched_case_count=len(case_reports) if semantics is not None else None,
                    name=
                        name,

                    score_count=
                        len(
                            baseline_scores
                        ),

                    baseline_score_mean=
                        baseline_score_mean,

                    candidate_score_mean=
                        candidate_score_mean,

                    score_delta_mean=
                        score_delta_mean,

                    value_count=
                        value_count,

                    value_unit=
                        value_unit,

                    value_comparable=
                        value_comparable,

                    baseline_value_mean=
                        baseline_value_mean,

                    candidate_value_mean=
                        candidate_value_mean,

                    value_delta_mean=
                        value_delta_mean,
                )
            )

        return aggregates

    @staticmethod
    def _mean(
        values: list[float],
    ) -> float | None:

        if not values:
            return None

        return (
            sum(values)
            / len(values)
        )
import asyncio

from datetime import (
    datetime,
    timezone,
)

from app.harness.run_query import (
    RunQuery,
    RunSummary,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)


class InMemoryRunStore(
    RunStore
):

    def __init__(
        self,
    ):
        self._records: dict[
            str,
            RunRecord,
        ] = {}

        self._lock = (
            asyncio.Lock()
        )

    async def save(
        self,
        record: RunRecord,
    ) -> None:

        async with self._lock:

            self._records.pop(
                record.run_id,
                None,
            )

            self._records[
                record.run_id
            ] = record.model_copy(
                deep=True
            )

    async def get(
        self,
        run_id: str,
    ) -> RunRecord | None:

        async with self._lock:

            record = (
                self._records.get(
                    run_id
                )
            )

            if record is None:
                return None

            return record.model_copy(
                deep=True
            )

    async def list_records(
        self,
        *,
        limit: int = 100,
    ) -> list[RunRecord]:

        if limit <= 0:
            return []

        async with self._lock:

            records = list(
                self._records.values()
            )

            records.reverse()

            return [
                record.model_copy(
                    deep=True
                )
                for record
                in records[:limit]
            ]

    async def search(
        self,
        query: RunQuery,
    ) -> list[RunSummary]:

        async with self._lock:

            records = (
                self._filter_records(
                    query
                )
            )

            reverse = (
                query.order
                == "started_at_desc"
            )

            records.sort(
                key=self._started_at_key,
                reverse=reverse,
            )

            page = records[
                query.offset:
                query.offset
                + query.limit
            ]

            return [
                RunSummary.from_record(
                    record
                )
                for record
                in page
            ]

    async def count(
        self,
        query: RunQuery,
    ) -> int:

        async with self._lock:

            return len(
                self._filter_records(
                    query
                )
            )

    def _filter_records(
        self,
        query: RunQuery,
    ) -> list[RunRecord]:

        result: list[
            RunRecord
        ] = []

        for record in (
            self._records.values()
        ):

            if (
                query.case_id
                is not None
                and record.case.id
                != query.case_id
            ):
                continue

            if (
                query.status
                is not None
                and record.status
                != query.status
            ):
                continue

            if (
                query.started_from
                is not None
                and (
                    record.started_at
                    is None
                    or record.started_at
                    < query.started_from
                )
            ):
                continue

            if (
                query.started_to
                is not None
                and (
                    record.started_at
                    is None
                    or record.started_at
                    > query.started_to
                )
            ):
                continue

            score = (
                record.result.score
            )

            if (
                query.min_score
                is not None
                and (
                    score is None
                    or score
                    < query.min_score
                )
            ):
                continue

            if (
                query.max_score
                is not None
                and (
                    score is None
                    or score
                    > query.max_score
                )
            ):
                continue

            result.append(
                record
            )

        return result

    @staticmethod
    def _started_at_key(
        record: RunRecord,
    ) -> datetime:

        return (
            record.started_at
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        )
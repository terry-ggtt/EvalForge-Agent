from app.harness.contracts import (
    TraceEvent,
)

from app.harness.run_record import (
    RunRecord,
)

from app.harness.run_store import (
    RunStore,
)

from app.harness.timeline import (
    RunTimeline,
    build_run_timeline,
)


class RunNotFoundError(
    LookupError
):
    pass


class RunReplayService:

    def __init__(
        self,
        store: RunStore,
    ):
        self.store = store

    async def load(
        self,
        run_id: str,
    ) -> RunRecord:

        record = await self.store.get(
            run_id
        )

        if record is None:

            raise RunNotFoundError(
                f"Run not found: "
                f"{run_id}"
            )

        return record

    async def events(
        self,
        run_id: str,
    ) -> list[TraceEvent]:

        record = await self.load(
            run_id
        )

        return [
            event.model_copy(
                deep=True
            )

            for event
            in record.result.trace
        ]

    async def timeline(
        self,
        run_id: str,
    ) -> RunTimeline:

        record = await self.load(
            run_id
        )

        return build_run_timeline(
            record
        )
from app.harness.run_query import (
    RunQuery,
    RunQueryResult,
)

from app.harness.run_store import (
    RunStore,
)


class RunQueryService:
    """
    Read-side service for persisted Harness runs.
    """

    def __init__(
        self,
        store: RunStore,
    ):
        self.store = store

    async def search(
        self,
        query: RunQuery,
    ) -> RunQueryResult:

        items = (
            await self.store.search(
                query
            )
        )

        total = (
            await self.store.count(
                query
            )
        )

        return RunQueryResult(
            items=
                items,

            total=
                total,

            limit=
                query.limit,

            offset=
                query.offset,
        )
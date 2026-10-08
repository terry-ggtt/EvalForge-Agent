from abc import (
    ABC,
    abstractmethod,
)

from app.harness.run_query import (
    RunQuery,
    RunSummary,
)

from app.harness.run_record import (
    RunRecord,
)


class RunStore(ABC):
    """
    Persistence boundary for Harness runs.
    """

    @abstractmethod
    async def save(
        self,
        record: RunRecord,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        run_id: str,
    ) -> RunRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list_records(
        self,
        *,
        limit: int = 100,
    ) -> list[RunRecord]:
        """
        Return full records.

        Mainly useful for compatibility,
        tests and small local datasets.
        """
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: RunQuery,
    ) -> list[RunSummary]:
        """
        Return lightweight summaries matching
        the supplied query.
        """
        raise NotImplementedError

    @abstractmethod
    async def count(
        self,
        query: RunQuery,
    ) -> int:
        """
        Count all records matching the filters.

        limit/offset are ignored.
        """
        raise NotImplementedError
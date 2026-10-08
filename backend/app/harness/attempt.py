from dataclasses import dataclass
import time
from uuid import uuid4


@dataclass
class AttemptContext:

    attempt_id: str

    attempt_number: int

    started_at: float

    @classmethod
    def create(
        cls,
        attempt_number: int,
    ) -> "AttemptContext":

        return cls(
            attempt_id=str(uuid4()),
            attempt_number=attempt_number,
            started_at=time.perf_counter(),
        )

    def elapsed_ms(self) -> float:

        return (
            time.perf_counter()
            - self.started_at
        ) * 1000
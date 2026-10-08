from pydantic import BaseModel, Field


class RetryPolicy(BaseModel):

    max_attempts: int = Field(
        default=1,
        ge=1,
    )

    initial_delay_seconds: float = Field(
        default=0.5,
        ge=0,
    )

    backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
    )

    max_delay_seconds: float = Field(
        default=10.0,
        ge=0,
    )

    def delay_for_attempt(
        self,
        attempt_number: int,
    ) -> float:
        """
        Return the backoff delay after a failed attempt.

        attempt_number=1:
            delay before attempt #2

        attempt_number=2:
            delay before attempt #3
        """

        if attempt_number <= 0:
            return 0.0

        delay = (
            self.initial_delay_seconds
            * (
                self.backoff_multiplier
                ** (
                    attempt_number - 1
                )
            )
        )

        return min(
            delay,
            self.max_delay_seconds,
        )
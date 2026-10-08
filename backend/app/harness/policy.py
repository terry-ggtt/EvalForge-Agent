from pydantic import BaseModel, Field


class ExecutionPolicy(BaseModel):

    max_concurrency: int = Field(
        default=5,
        ge=1,
    )

    timeout_seconds: float | None = Field(
        default=60.0,
        gt=0,
    )
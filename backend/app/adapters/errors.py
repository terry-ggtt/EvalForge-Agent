from app.harness.contracts import TraceEvent


class AgentExecutionError(RuntimeError):

    def __init__(
        self,
        message: str,
        trace: list[TraceEvent],
    ):
        super().__init__(message)
        self.trace = trace

class MappingFailure(Exception):
    """Deterministic normalization failed; never an answer-quality failure or a transient agent retry."""

    def __init__(self, code: str) -> None:
        """Keep safe normalization code; return None without embedding raw response values."""
        super().__init__("Mapping failed: " + code)
        self.code = code

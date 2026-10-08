from app.harness.contracts import TraceEvent


class AgentExecutionError(RuntimeError):

    def __init__(
        self,
        message: str,
        trace: list[TraceEvent],
    ):
        super().__init__(message)
        self.trace = trace
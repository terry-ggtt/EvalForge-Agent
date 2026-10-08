class DatasetNormalizationError(ValueError):
    """
    Raised when a raw dataset case cannot be converted
    into the Harness canonical TestCase schema.
    """
    def __init__(
        self,
        message: str,
        *,
        raw_case:dict |None = None,
    ):
        super().__init__(message)
        self.raw_case = raw_case
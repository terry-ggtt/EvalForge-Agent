class EvaluationJobNotFoundError(LookupError):
    pass
class JobOwnershipError(RuntimeError):
    """
    The job no longer belongs to
    the current worker or is in
    an incompatible state.
    """
    pass

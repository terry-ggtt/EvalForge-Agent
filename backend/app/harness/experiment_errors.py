class ExperimentNotFoundError(
    LookupError
):
    pass


class ExperimentRunNotFoundError(
    LookupError
):
    pass


class ExperimentStateError(
    RuntimeError
):
    pass


class ExperimentRunConflictError(
    ValueError
):
    pass


class ExperimentMembershipConflictError(
    RuntimeError
):
    pass
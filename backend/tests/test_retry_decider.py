from app.harness.retry_decider import (
    DefaultRetryDecider,
)


class FakeHttpError(Exception):

    def __init__(
        self,
        status_code: int,
    ):
        self.status_code = status_code


def test_retry_transient_http_errors():

    decider = DefaultRetryDecider()

    for status in (
        429,
        502,
        503,
        504,
    ):
        assert decider.should_retry(
            FakeHttpError(status)
        )


def test_do_not_retry_client_errors():

    decider = DefaultRetryDecider()

    for status in (
        400,
        401,
        403,
        404,
    ):
        assert not decider.should_retry(
            FakeHttpError(status)
        )


def test_retry_connection_error():

    decider = DefaultRetryDecider()

    assert decider.should_retry(
        ConnectionError(
            "connection lost"
        )
    )


def test_do_not_retry_value_error():

    decider = DefaultRetryDecider()

    assert not decider.should_retry(
        ValueError(
            "invalid arguments"
        )
    )
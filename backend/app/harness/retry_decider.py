from abc import ABC, abstractmethod
from typing import Any


class RetryDecider(ABC):
    """
    Decide whether an exception represents
    a transient failure that may be retried.

    This class only answers:

        "Should this error be retried?"

    It does NOT decide:

    - how many times to retry
    - how long to wait
    - when the next attempt starts

    Those responsibilities belong to
    RetryPolicy and HarnessRunner.
    """

    @abstractmethod
    def should_retry(
        self,
        exc: Exception,
    ) -> bool:
        raise NotImplementedError


class DefaultRetryDecider(
    RetryDecider
):
    """
    Conservative default retry strategy.

    Retry only failures that are likely
    to be temporary:

    - timeout
    - connection/network failures
    - selected HTTP server/rate-limit errors

    Do not retry programming errors,
    validation errors, authentication errors,
    permission errors, etc.
    """

    RETRYABLE_STATUS_CODES = {
        429,
        502,
        503,
        504,
    }

    def should_retry(
        self,
        exc: Exception,
    ) -> bool:

        # 1. Generic transient failures
        if isinstance(
            exc,
            (
                TimeoutError,
                ConnectionError,
            ),
        ):
            return True

        # 2. Some network libraries expose
        # lower-level failures as OSError.
        #
        # Do not make every OSError retryable
        # blindly unless you actually need it.
        #
        # For V0.9 we keep the default
        # strategy conservative.

        # 3. HTTP/provider exceptions often
        # expose status_code directly or
        # through a response object.
        status_code = (
            self._extract_status_code(
                exc
            )
        )

        if (
            status_code
            in self.RETRYABLE_STATUS_CODES
        ):
            return True

        return False

    @staticmethod
    def _extract_status_code(
        exc: Exception,
    ) -> int | None:
        """
        Try to extract an HTTP status code
        without depending on a specific
        provider SDK.

        Supported common shapes:

        exc.status_code

        exc.response.status_code
        """

        status_code = getattr(
            exc,
            "status_code",
            None,
        )

        if isinstance(
            status_code,
            int,
        ):
            return status_code

        response: Any = getattr(
            exc,
            "response",
            None,
        )

        if response is not None:

            status_code = getattr(
                response,
                "status_code",
                None,
            )

            if isinstance(
                status_code,
                int,
            ):
                return status_code

        return None
from app.harness.retry import (
    RetryPolicy,
)


def test_exponential_backoff():

    policy = RetryPolicy(
        max_attempts=5,
        initial_delay_seconds=0.5,
        backoff_multiplier=2,
        max_delay_seconds=2,
    )

    assert (
        policy.delay_for_attempt(1)
        == 0.5
    )

    assert (
        policy.delay_for_attempt(2)
        == 1.0
    )

    assert (
        policy.delay_for_attempt(3)
        == 2.0
    )

    assert (
        policy.delay_for_attempt(4)
        == 2.0
    )
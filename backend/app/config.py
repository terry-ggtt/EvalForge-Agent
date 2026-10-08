import os


def get_database_url() -> str:
    """
    Return the PostgreSQL DSN used by
    the running Harness application.

    Tests use TEST_POSTGRES_DSN.

    The actual API service uses:
        HARNESS_DATABASE_URL
    """

    database_url = os.getenv(
        "HARNESS_DATABASE_URL"
    )

    if not database_url:
        raise RuntimeError(
            "HARNESS_DATABASE_URL "
            "is not configured."
        )

    return database_url
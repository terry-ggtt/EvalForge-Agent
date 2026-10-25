from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evalforge_evaluator_sdk import EvaluatorPluginConfig


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


def get_evaluator_plugin_config() -> EvaluatorPluginConfig:
    """Read server-only EVALFORGE_EVALUATOR_PLUGINS JSON; return a deny-by-default SDK policy.

    Missing configuration allows no third-party imports. Invalid JSON, unknown
    fields or ambiguous allowlists raise a safe RuntimeError. No module is
    loaded, no package installed and no connection/credential is provided.
    """
    from evalforge_evaluator_sdk import EvaluatorPluginConfig

    raw = os.environ.get("EVALFORGE_EVALUATOR_PLUGINS", "{}")
    try:
        return EvaluatorPluginConfig.model_validate_json(raw)
    except ValueError:
        raise RuntimeError("Invalid EVALFORGE_EVALUATOR_PLUGINS configuration") from None

from abc import ABC, abstractmethod
from typing import Any


class ToolArgumentMatcher(ABC):
    """
    Decide how similar expected tool arguments
    are to actual tool arguments.

    Return a score between 0.0 and 1.0.
    """

    @abstractmethod
    def match(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> float:
        raise NotImplementedError


class ExactToolArgumentMatcher(
    ToolArgumentMatcher
):
    """
    Exact argument matching.

    All keys and values must be identical.
    """

    def match(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> float:

        return (
            1.0
            if expected == actual
            else 0.0
        )


class PartialToolArgumentMatcher(
    ToolArgumentMatcher
):
    """
    Give partial credit based on expected fields.

    Example:

    expected:
        {
            "query": "RAG",
            "top_k": 5
        }

    actual:
        {
            "query": "RAG",
            "top_k": 10
        }

    score:
        1 / 2 = 0.5
    """

    def match(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> float:

        expected_fields = self._flatten(
            expected
        )

        actual_fields = self._flatten(
            actual
        )

        if not expected_fields:
            return 1.0

        matched = 0

        for path, expected_value in (
            expected_fields.items()
        ):
            actual_value = (
                actual_fields.get(path)
            )

            if (
                path in actual_fields
                and actual_value
                == expected_value
            ):
                matched += 1

        return (
            matched
            / len(expected_fields)
        )

    def _flatten(
        self,
        value: dict[str, Any],
        prefix: str = "",
    ) -> dict[str, Any]:

        result: dict[str, Any] = {}

        for key, item in value.items():

            path = (
                f"{prefix}.{key}"
                if prefix
                else key
            )

            if isinstance(item, dict):

                result.update(
                    self._flatten(
                        item,
                        prefix=path,
                    )
                )

            else:
                result[path] = item

        return result
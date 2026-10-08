from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizedUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


def normalize_usage(
    usage: dict[str, Any],
) -> NormalizedUsage:

    input_tokens = int(
        usage.get(
            "input_tokens",
            usage.get(
                "prompt_tokens",
                0,
            ),
        )
        or 0
    )

    output_tokens = int(
        usage.get(
            "output_tokens",
            usage.get(
                "completion_tokens",
                0,
            ),
        )
        or 0
    )

    total_tokens = int(
        usage.get(
            "total_tokens",
            input_tokens + output_tokens,
        )
        or 0
    )

    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
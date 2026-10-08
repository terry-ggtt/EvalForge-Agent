from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """
    Price per 1 million tokens.
    """

    input_per_million: float

    output_per_million: float


class PricingCatalog:

    def __init__(
        self,
        prices: dict[
            str,
            ModelPricing,
        ],
    ):
        self._prices = prices

    def get(
        self,
        model: str,
    ) -> ModelPricing | None:

        return self._prices.get(
            model
        )
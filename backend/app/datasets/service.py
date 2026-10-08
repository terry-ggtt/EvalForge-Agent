from app.datasets.loader import (
    DatasetLoader,
)

from app.datasets.base import (
    CaseNormalizer,
)

from app.harness.contracts import (
    TestCase,
)


class DatasetService:

    def __init__(
        self,
        loader: DatasetLoader,
        normalizer: CaseNormalizer,
    ):
        self.loader = loader
        self.normalizer = normalizer


    def load_cases(
        self,
        source: str,
    ) -> list[TestCase]:

        raw_cases = (
            self.loader.load(
                source
            )
        )

        return (
            self.normalizer.normalize_many(
                raw_cases
            )
        )
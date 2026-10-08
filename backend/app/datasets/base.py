from abc import ABC, abstractmethod
from typing import Any

from app.harness.contracts import TestCase


class CaseNormalizer(ABC):

    @abstractmethod
    def normalize(
        self,
        raw_case: dict[str, Any],
    ) -> TestCase:
        """
        Convert one external raw case into the
        Harness canonical TestCase format.
        """
        raise NotImplementedError

    def normalize_many(
        self,
        raw_cases: list[dict[str, Any]],
    ) -> list[TestCase]:

        return [
            self.normalize(raw_case)
            for raw_case in raw_cases
        ]
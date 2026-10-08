from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DatasetLoader(ABC):
    """
    Load external dataset sources into raw cases.

    Output format:

    list[dict[str, Any]]
    """

    @abstractmethod
    def load(
        self,
        source: str | Path,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError
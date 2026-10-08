import csv
from pathlib import Path
from typing import Any

from app.datasets.loader import (
    DatasetLoader,
)


class CsvDatasetLoader(
    DatasetLoader
):

    def load(
        self,
        source: str | Path,
    ) -> list[dict[str, Any]]:

        path = Path(source)

        with path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as f:

            reader = csv.DictReader(
                f
            )

            return list(reader)